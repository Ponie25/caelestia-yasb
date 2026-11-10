"""Local activity sources for the compact Island."""

from base64 import b64decode
from binascii import Error as Base64Error
from contextlib import closing
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import json
import logging
import msvcrt
import os
from pathlib import Path
import re
import sqlite3
from threading import Event, Thread

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QLocalServer, QLocalSocket


@dataclass(frozen=True)
class CodexTurn:
    thread_id: str
    turn_id: str
    started: int
    status: str


class Overlapped(ctypes.Structure):
    _fields_ = [('internal', ctypes.c_size_t), ('internal_high', ctypes.c_size_t),
                ('offset', wintypes.DWORD), ('offset_high', wintypes.DWORD), ('event', wintypes.HANDLE)]


class CodexActivity(QObject):
    changed = Signal(object, object)

    def __init__(self, directory=None):
        super().__init__()
        self.directory = directory or Path(os.environ.get('CODEX_HOME') or (Path.home() / '.codex'))
        self.history = self.directory / 'thread_history_1.sqlite'
        self.stopping = Event()
        self.native = ctypes.WinDLL('kernel32', use_last_error=True)
        lock_args = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                     ctypes.POINTER(Overlapped)]
        self.native.LockFileEx.argtypes = lock_args[:1] + [wintypes.DWORD] + lock_args[1:]
        self.native.UnlockFileEx.argtypes = lock_args
        self.thread = Thread(target=self._run, daemon=True, name='Island Codex activity')

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread.is_alive():
            self.thread.join(timeout=0.4)

    def _is_held(self, path):
        try:
            with path.open('rb') as file:
                handle = msvcrt.get_osfhandle(file.fileno())
                offset = Overlapped()
                # A nonblocking shared probe fails if Codex owns its exclusive writer lock.
                if not self.native.LockFileEx(handle, 1, 0, 1, 0, ctypes.byref(offset)):
                    return ctypes.get_last_error() == 33  # ERROR_LOCK_VIOLATION
                self.native.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(offset))
        except OSError:
            pass
        return False

    def _active_threads(self):
        return {path.stem for path in (self.directory / 'thread-writer-locks').glob('*.lock')
                if re.fullmatch(r'[0-9a-fA-F-]{36}', path.stem) and self._is_held(path)}

    def _latest(self, thread_ids):
        # Select only the lifecycle fields. The database also contains message bodies.
        uri = self.history.resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=0.12)) as db:
            query = """SELECT turn_id, started_at, status, root_turn_id FROM thread_turns
                       WHERE thread_id = ? ORDER BY rollout_ordinal DESC LIMIT 1"""
            result = {}
            for thread in thread_ids:
                row = db.execute(query, (thread,)).fetchone()
                if row and row[1] and row[3] in (None, row[0]):
                    result[thread] = CodexTurn(thread, row[0], row[1], row[2])
            return result

    def _run(self):
        active = {}
        failures = 0
        while not self.stopping.is_set():
            try:
                held = self._active_threads()
                if not held and not active:
                    self.stopping.wait(2.0)
                    continue
                states = self._latest(held | active.keys())
                running = {key: turn for key, turn in states.items()
                           if key in held and turn.status == 'inProgress'}
                ended = tuple(states[key] for key, turn in active.items()
                              if key not in running and key in states
                              and states[key].turn_id == turn.turn_id
                              and states[key].status in ('completed', 'interrupted', 'failed'))
                if running != active or ended:
                    ordered = tuple(sorted(running.values(), key=lambda turn: (turn.started, turn.thread_id)))
                    self.changed.emit(ordered, ended)
                active = running
                failures = 0
            except (OSError, sqlite3.Error):
                # An absent or changed Codex schema leaves this source idle.
                failures += 1
                if active and failures >= 3:
                    active = {}
                    self.changed.emit((), ())
            self.stopping.wait(1.0)


class NotificationReceiver(QObject):
    received = Signal(str, int, QImage)
    snapshot = Signal(object)
    MAX_PACKET = 2 * 1024 * 1024

    def __init__(self, root):
        super().__init__()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._connect)
        key = hashlib.sha256(os.fsencode(os.path.normcase(str(root.resolve())))).hexdigest()[:20]
        self.pipe = 'caelestia-yasb-' + key
        if not self.server.listen(self.pipe):
            logging.warning('Island notification listener could not start: %s', self.server.errorString())

    def request(self, notification_id=None):
        message = {'refresh': True} if notification_id is None else {'dismiss': notification_id}
        self._send(message)

    def clear(self):
        self._send({'clear': True})

    def _send(self, message):
        payload = json.dumps(message).encode('ascii') + b'\n'
        socket = QLocalSocket(self)

        def send():
            socket.write(payload)
            socket.disconnectFromServer()

        socket.connected.connect(send)
        socket.disconnected.connect(socket.deleteLater)
        socket.errorOccurred.connect(socket.deleteLater)
        socket.connectToServer(self.pipe + '-commands')

    def _connect(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.setReadBufferSize(self.MAX_PACKET)
            socket.readyRead.connect(lambda sock=socket: self._read(sock))
            socket.disconnected.connect(socket.deleteLater)
            timer = QTimer(socket, interval=1200, singleShot=True)
            timer.timeout.connect(socket.abort)
            timer.start()
            self._read(socket)

    def _read(self, socket):
        if socket.canReadLine():
            try:
                message = json.loads(bytes(socket.readLine(self.MAX_PACKET)))
                if message.get('kind') == 'snapshot':
                    self._snapshot(message.get('items'))
                else:
                    app, count = message.get('app'), message.get('count')
                    if isinstance(app, str) and type(count) is int and 0 < count <= 999:
                        app = ' '.join(app.split())[:64]
                        image = QImage()
                        encoded = message.get('icon', '')
                        if isinstance(encoded, str) and len(encoded) <= 16384:
                            try:
                                image = QImage.fromData(b64decode(encoded, validate=True), 'PNG')
                            except (Base64Error, ValueError):
                                pass
                        self.received.emit(app, count, image)
            except (AttributeError, UnicodeError, ValueError):
                pass
            socket.disconnectFromServer()
        elif socket.bytesAvailable() >= self.MAX_PACKET:
            socket.abort()

    def _snapshot(self, items):
        if items is None:
            self.snapshot.emit(None)
        elif isinstance(items, list):
            rows = []
            for item in items:
                if not isinstance(item, dict) or type(item.get('id')) is not int:
                    continue
                if not all(isinstance(item.get(key), str) for key in ('app', 'title', 'body')):
                    continue
                at = item.get('at')
                rows.append({'id': item['id'], 'app': item['app'][:80] or 'Windows',
                             'title': item['title'][:220], 'body': item['body'][:900],
                             'at': at if type(at) is int and 0 < at < 4102444800 else 0})
            self.snapshot.emit(tuple(rows))
