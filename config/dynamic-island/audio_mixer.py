from _ctypes import COMError
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PureWindowsPath

import psutil
from pycaw.api.audiopolicy import IAudioSessionControl2
from pycaw.pycaw import AudioSession
from PySide6.QtCore import QFileInfo, QRectF, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFileIconProvider

from icons import icon
from palette import BASE, LAVENDER, MAUVE, MUTED, OVERLAY, PINK, SURFACE, SURFACE2, TEXT
from player import pill, text


PANEL = QRectF(510, 110, 196, 301)
VOLUME = QRectF(550, 166, 111, 25)
MUTE = QRectF(524, 166, 23, 25)
ROWS = QRectF(523, 220, 171, 176)
ROW_HEIGHT = 29
VISIBLE_ROWS = int(ROWS.height() // ROW_HEIGHT)
RIGHT = Qt.AlignmentFlag.AlignRight
DEMI = QFont.Weight.DemiBold
SESSION_ERRORS = (COMError, OSError, psutil.Error)


@dataclass
class AppVolume:
    name: str
    executable: str
    level: int
    muted: bool
    controls: list


@lru_cache(maxsize=32)
def _app_icon(executable):
    return QFileIconProvider().icon(QFileInfo(executable))


def _session_app(session):
    pid = session.ProcessId
    if not pid:
        return ('system', 'Âm thanh hệ thống', '')
    process = session.Process
    if process is None:
        return None
    name = process.name()
    try:
        executable = process.exe()
    except (OSError, psutil.Error):
        executable = ''
    display_name = session.DisplayName
    title = display_name if display_name and not display_name.startswith('@') else PureWindowsPath(name).stem
    return (executable.casefold() if executable else (name.casefold(), pid), title, executable)


def _slider(painter, rect, level, muted, hovered=False):
    y = rect.center().y()
    color = OVERLAY if muted else PINK if hovered else LAVENDER
    start = rect.left()
    if level is None:
        pill(painter, QRectF(start, y - 2, rect.width(), 4), 2, SURFACE2)
        return
    end = start + rect.width() * level / 100
    if end - start > 5:
        pill(painter, QRectF(start, y - 2, end - start - 5, 4), 2, color)
    if rect.right() - end > 5:
        pill(painter, QRectF(end + 5, y - 2, rect.right() - end - 5, 4), 2, SURFACE2)
    pill(painter, QRectF(end - 1.5, y - 7, 3, 14), 1.5, color)


def _value(painter, rect, level, muted):
    text(painter, '—' if level is None else f'{level}%', rect, 11, MUTED if muted else TEXT, align=RIGHT)


class AudioMixer:
    def __init__(self):
        self.apps = {}
        self.offset = 0

    def refresh(self, output):
        output.refresh()
        previous = self.apps
        self.apps = {}
        if output.device is not None:
            self._read_sessions(output.device)
        # Keep live rows in place as sessions appear or expire.
        ordered = {key: self.apps[key] for key in previous if key in self.apps}
        ordered.update((key, row) for key, row in self.apps.items() if key not in ordered)
        first = next(iter(tuple(previous)[self.offset:]), None)
        self.apps = ordered
        if first in ordered:
            self.offset = tuple(ordered).index(first)
        self.offset = min(self.offset, self.max_offset)

    def _read_sessions(self, device):
        try:
            enumerator = device.AudioSessionManager.GetSessionEnumerator()
            count = enumerator.GetCount()
        except SESSION_ERRORS:
            return
        for index in range(count):
            try:
                session = AudioSession(enumerator.GetSession(index).QueryInterface(IAudioSessionControl2))
                if session.State == 2:
                    continue
                app = _session_app(session)
                if app is None:
                    continue
                key, name, executable = app
                control = session.SimpleAudioVolume
                level = round(control.GetMasterVolume() * 100)
                muted = bool(control.GetMute())
            except SESSION_ERRORS:
                continue
            row = self.apps.get(key)
            if row is None:
                self.apps[key] = AppVolume(name, executable, level, muted, [control])
            else:
                row.controls.append(control)
                row.level = max(row.level, level)
                row.muted &= muted

    @property
    def max_offset(self):
        return max(0, len(self.apps) - VISIBLE_ROWS)

    def scroll(self, delta):
        before = self.offset
        self.offset = min(self.max_offset, max(0, self.offset - (1 if delta > 0 else -1)))
        return self.offset != before

    def _rows(self):
        visible = tuple(self.apps.items())[self.offset:self.offset + VISIBLE_ROWS]
        for i, (key, row) in enumerate(visible):
            y = ROWS.top() + i * ROW_HEIGHT
            yield key, row, QRectF(524, y + 2, 23, 24), QRectF(550, y + 2, 111, 24)

    def action_at(self, point):
        for key, _, button, slider in self._rows():
            if button.contains(point):
                return ('app_mute', key)
            if slider.contains(point):
                return ('app_volume', key)
        return None

    @staticmethod
    def is_action(action):
        return isinstance(action, tuple) and action[0] in ('app_mute', 'app_volume')

    def tooltip(self, action):
        row = self.apps.get(action[1])
        if row is None:
            return ''
        if action[0] == 'app_volume':
            return f'{row.name} · {row.level}%'
        return f'{"Bật" if row.muted else "Tắt"} tiếng {row.name}'

    def _apply(self, key, operation, value):
        row = self.apps.get(key)
        if row is None:
            return
        available = []
        for control in row.controls:
            try:
                getattr(control, operation)(value, None)
            except SESSION_ERRORS:
                continue
            available.append(control)
        if not available:
            self.apps.pop(key, None)
            self.offset = min(self.offset, self.max_offset)
            return
        row.controls = available
        if operation == 'SetMute':
            row.muted = value
        else:
            row.level = round(value * 100)

    def set_level(self, key, level):
        self._apply(key, 'SetMasterVolume', max(0, min(100, level)) / 100)

    def toggle_mute(self, key):
        row = self.apps.get(key)
        if row is not None:
            self._apply(key, 'SetMute', not row.muted)

    def draw(self, painter, output, hover, volume_preview=None, app_drag=None, app_preview=None):
        pill(painter, PANEL, 22, BASE)
        text(painter, 'Audio Mixer', QRectF(526, 122, 163, 22), 14, TEXT, DEMI)
        output_name = output.device.FriendlyName if output.device is not None else None
        text(painter, output_name or 'Đầu ra mặc định', QRectF(526, 146, 163, 17), 10, MUTED)
        if hover == 'mute' and output.level is not None:
            pill(painter, MUTE, 8, SURFACE)
        icon(painter, 'mute' if output.muted else 'volume', MUTE.center().x(), MUTE.center().y(), 16, MUTED)
        level = volume_preview if volume_preview is not None else output.level
        _slider(painter, VOLUME, level, output.muted, hover == 'volume' or volume_preview is not None)
        _value(painter, QRectF(665, VOLUME.top(), 28, VOLUME.height()), level, output.muted)
        pill(painter, QRectF(526, 194, 164, 1), 0.5, SURFACE)
        text(painter, 'Ứng dụng', QRectF(526, 198, 146, 18), 10, MUTED)

        if not self.apps:
            text(painter, 'Chưa có phiên âm thanh', QRectF(526, 249, 162, 48), 11, OVERLAY,
                 align=Qt.AlignmentFlag.AlignHCenter)
        for key, row, button, slider in self._rows():
            hot_button = hover == ('app_mute', key)
            if hot_button or row.muted:
                pill(painter, button, 8, SURFACE)
            app_icon = _app_icon(row.executable) if row.executable and not row.muted else None
            if app_icon and not app_icon.isNull():
                app_icon.paint(painter, button.adjusted(3, 3, -3, -3).toRect())
            else:
                icon(painter, 'mute' if row.muted else 'volume',
                     button.center().x(), button.center().y(), 14, PINK if row.muted else MAUVE)
            value = app_preview if app_drag == ('app_volume', key) else row.level
            _slider(painter, slider, value, row.muted, hover == ('app_volume', key) or app_drag == ('app_volume', key))
            _value(painter, QRectF(665, slider.top(), 28, slider.height()), value, row.muted)
        if self.max_offset:
            height = ROWS.height() * VISIBLE_ROWS / len(self.apps)
            y = ROWS.top() + (ROWS.height() - height) * self.offset / self.max_offset
            pill(painter, QRectF(699, y, 2, height), 1, SURFACE2)
