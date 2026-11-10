"""Exercise mixed activity layout, real local IPC, and read-only Codex lifecycle detection."""

import msvcrt
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_previews import album_art, capture, island_dir

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from PySide6.QtCore import QPointF
from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from activities import CodexActivity, CodexTurn, NotificationReceiver
from live_activity import OUTPUT_VOLUME, SUMMARY
from media import MediaState


def eventually(predicate, milliseconds=3300):
    end = time.monotonic() + milliseconds / 1000
    while time.monotonic() < end:
        if predicate():
            return
        QTest.qWait(30)
    assert predicate()


def check_codex():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        locks = root / 'thread-writer-locks'
        locks.mkdir()
        thread = str(uuid4())
        lock = locks / (thread + '.lock')
        lock.touch()
        now = int(time.time())
        worker = CodexActivity(root)
        updates = []
        worker.changed.connect(lambda active, ended: updates.append((active, ended)))
        db = sqlite3.connect(worker.history)
        db.execute('CREATE TABLE thread_turns (thread_id, turn_id, root_turn_id, started_at, status, rollout_ordinal)')
        db.execute('INSERT INTO thread_turns VALUES (?, ?, ?, ?, ?, ?)',
                   (thread, 'first', 'first', now, 'inProgress', 1))
        db.commit()
        with lock.open('r+b') as handle:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            worker.start()
            try:
                eventually(lambda: len(updates) == 1)
                assert updates[-1] == ((CodexTurn(thread, 'first', now, 'inProgress'),), ())
                db.execute("UPDATE thread_turns SET status = 'completed'")
                db.commit()
                eventually(lambda: len(updates) == 2)
                assert updates[-1] == ((), (CodexTurn(thread, 'first', now, 'completed'),))
                db.execute('INSERT INTO thread_turns VALUES (?, ?, ?, ?, ?, ?)',
                           (thread, 'second', 'second', now, 'inProgress', 2))
                db.commit()
                eventually(lambda: len(updates) == 3)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                eventually(lambda: len(updates) == 4)
                assert updates[-1] == ((), ())  # Abandoned turn has no success message.
            finally:
                worker.stop()
                db.close()


def main():
    app = QApplication([])
    source = SourceFileLoader('island', str(island_dir / 'island.pyw'))
    spec = spec_from_loader(source.name, source)
    island = module_from_spec(spec)
    source.exec_module(island)
    with patch.object(island.Island, '_warm_up', lambda self: None):
        widget = island.Island(lambda *_: None, lambda: None)
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    widget.show()
    app.processEvents()

    def assert_opens(point):
        with patch.object(widget.dashboard, 'sample'), patch.object(widget, '_refresh_avatar'):
            QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=point.toPoint())
        assert widget.expanded and widget.dashboard.tab == 'Dashboard'
        widget._set_expanded(False)
        eventually(lambda: not widget.animation.isActive())

    started = int(time.time()) - 18
    turn = CodexTurn(str(uuid4()), 'turn', started, 'inProgress')
    music = MediaState(1, 'A Quiet Orbit', 'Studio Meridian', playing=True)
    widget.set_media(music)
    widget.art = album_art()
    widget.set_media(music)
    widget.set_codex((turn,), ())
    QTest.qWait(190)
    assert widget.slot_sizes == (186.0, 130.0, 0.0, 0.0, 0.0)
    assert widget.codex_clock.isActive()
    output = Path(sys.argv[2])
    output.mkdir(parents=True, exist_ok=True)
    capture(widget, output / 'music-and-codex.png', crop_width=352)

    with TemporaryDirectory() as directory:
        receiver = NotificationReceiver(Path(directory))
        receiver.received.connect(widget.show_notification)
        sender = QLocalSocket()
        sender.connectToServer(receiver.server.serverName())
        assert sender.waitForConnected(600)
        sender.write(b'{"app":"Windows Test","count":1}\n')
        sender.flush()
        eventually(lambda: widget.notification.isActive())
        QTest.qWait(190)
        single_width = widget.slot_sizes[-1]
        assert single_width == widget._notice_banner_width() < 166
        capture(widget, output / 'single-notification.png', crop_width=522)
        widget.show_notification('Another app', 2)
        QTest.qWait(190)
        assert widget.notice == ('Another app', 3)
        assert widget.notification.interval() == 5000
        assert widget.slot_sizes == (186.0, 130.0, 0.0, 0.0, widget._notice_banner_width())
        assert widget.slot_sizes[-1] > single_width
        capture(widget, output / 'music-codex-and-notice.png', crop_width=522)
        media_rect, codex_rect, _, _, notice_rect = widget._compact_rects(widget._surface_rect())
        for rect in (media_rect, codex_rect, notice_rect):
            assert_opens(rect.center())
        widget.notification.stop()
        widget._retarget()
        receiver.server.close()

    widget.set_media(MediaState())
    QTest.qWait(190)
    assert widget.slot_sizes == (0.0, 150.0, 0.0, 0.0, 0.0)
    capture(widget, output / 'codex-only.png', crop_width=184)
    assert_opens(widget._surface_rect().center())
    widget.set_media(music)
    ended = CodexTurn(turn.thread_id, turn.turn_id, started, 'interrupted')
    widget.set_codex((), (ended,))
    assert widget.codex_chip.status == 'interrupted'
    assert not widget.codex_clock.isActive()
    eventually(lambda: widget.slot_sizes == (250.0, 0.0, 0.0, 0.0, 0.0))
    widget.set_media(MediaState())
    eventually(lambda: widget.slot_sizes == (0.0,) * 5)
    assert_opens(widget._surface_rect().center())
    check_live_panel(widget, output)
    widget.hide()
    widget.dashboard.metrics.close()
    check_codex()
    print('Mixed activity, grouped notifications, menu clicks, interruption and stale-lock cleanup passed.')


def check_live_panel(widget, output):
    live = widget.dashboard.live
    with patch.object(widget.dashboard, 'sample'), patch.object(widget, '_refresh_avatar'):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=widget._surface_rect().center().toPoint())
    assert widget.expanded
    widget.outside_click.stop()
    eventually(lambda: not widget.animation.isActive())
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=SUMMARY.center().toPoint())
    eventually(lambda: not widget.tab_frames.isActive())
    assert widget.dashboard.tab == 'Live Activity'

    def click(action):
        _, rect, _ = next(item for item in live._controls() if item[0] == action)
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())

    click(('live', 'preset', 15))
    click(('live', 'adjust', 1))
    assert live.countdown == 16 * 60
    click(('live', 'timer'))
    click(('live', 'timer'))
    assert live.deadline is None and live.paused > 15 * 60
    click(('live', 'timer'))
    click(('live', 'watch'))
    assert live.deadline and live.stopwatch_start is not None
    click(('live', 'lap'))
    assert live.lap is not None
    widget.set_codex((CodexTurn('test', 'test', int(time.time()) - 35, 'inProgress'),), ())
    widget.set_media(MediaState(8, 'A Quiet Orbit', 'Studio Meridian', playing=True))
    assert all(width > 0 for width in widget._slot_widths()[:4])
    with patch.object(QApplication, 'beep') as beep:
        live.deadline = time.time() - 1
        live._tick()
        beep.assert_called_once()
    assert live.finished and widget.timer_done.isActive()
    click(('live', 'timer_reset'))
    assert not widget.timer_done.isActive()
    click(('live', 'watch'))
    assert live.stopwatch_start is None
    click(('live', 'watch_reset'))
    assert live.stopwatch == 0

    rows = tuple({'id': i, 'app': 'Windows test', 'title': f'Test message {i}',
                  'body': 'Multiline message\n' + ('AnUnbrokenWordThatMustWrap' * 33 + '\n') * 3 if i == 1 else 'Example only',
                  'at': 0} for i in range(10))
    live.set_notifications(rows)
    assert live.scroll(QPointF(420, 160), -120) and live.notice_offset == 1
    click(('live', 'notice', 1))
    assert live.selected == 1
    assert live._detail_end() > 0
    live.scroll(QPointF(420, 245), -120)
    assert live.detail_offset > 0
    capture(widget, output / 'notice-detail.png')
    dismissed = []
    live.dismiss_requested.connect(dismissed.append)
    click(('live', 'dismiss', 1))
    assert dismissed == [1]
    live.set_notifications((rows[0], *rows[2:]))
    assert live.selected is None
    cleared = []
    live.clear_requested.connect(lambda: cleared.append(True))
    click(('live', 'ask_clear'))
    click(('live', 'cancel_clear'))
    assert not cleared
    click(('live', 'ask_clear'))
    click(('live', 'clear'))
    assert cleared == [True]
    capture(widget, output / 'live-panel-test.png')

    class FakeOutput:
        level, muted = 48, False
        device = SimpleNamespace(id='a', FriendlyName='Loa')

        def refresh(self):
            pass

        def outputs(self):
            return ('a', 'Loa'), ('b', 'Tai nghe USB')

        def select_output(self, key):
            self.device = SimpleNamespace(id=key, FriendlyName=dict(self.outputs())[key])
            return True

        def set_level(self, value):
            self.level = value

        def toggle_mute(self):
            self.muted = not self.muted

    widget.volume = FakeOutput()
    click(('live', 'output'))
    assert live.output_open and live.output_id == 'a'
    click(('live', 'output_device', 'b'))
    assert live.output_id == 'b'
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=OUTPUT_VOLUME.center().toPoint())
    assert widget.volume.level == live.volume_level == 50
    click(('live', 'output_mute'))
    assert live.volume_muted
    capture(widget, output / 'audio-output.png')
    widget._set_expanded(False)


if __name__ == '__main__':
    main()
