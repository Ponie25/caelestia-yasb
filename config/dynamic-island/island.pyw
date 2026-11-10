import asyncio
import ctypes
from ctypes import wintypes
import logging
from logging.handlers import RotatingFileHandler
import math
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'runtime'), str(ROOT)]

from PySide6.QtCore import QPointF, QRectF, Qt, QLockFile, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget
from winrt.windows.system import User, UserPictureSize

from activities import CodexActivity, NotificationReceiver
from audio_mixer import ROWS
import player
from dashboard import Dashboard, HEIGHT, PANEL_WIDTH, TAB_RECTS, WIDTH
import tab_views
from glass import GlassLayer
from icons import icon
from live_activity import OUTPUT_VOLUME, clock_text
from media import MediaState, MediaWorker, read_image_bytes
from palette import CRUST, LAVENDER, MAUVE, MANTLE, PINK, SURFACE2
from volume import OutputVolume


NOTICE_LABEL = 'New Notification !'
NOTICE_PADDING = 8
NOTICE_ICON_SIZE = 20
NOTICE_GAP = 8


async def _account_picture():
    picture = await User.get_default().get_picture_async(UserPictureSize.SIZE208X208)
    return await read_image_bytes(picture) if picture else b''


class Dock:
    """Find the live YASB bar on the primary screen in physical pixels."""

    def __init__(self):
        self.native = ctypes.WinDLL('user32', use_last_error=True)
        self.bar = None
        self.native.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
        self.native.FindWindowExW.restype = wintypes.HWND
        self.native.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.native.IsWindowVisible.argtypes = [wintypes.HWND]
        self.native.IsZoomed.argtypes = [wintypes.HWND]
        self.native.GetForegroundWindow.restype = wintypes.HWND
        self.native.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.native.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.native.GetAsyncKeyState.restype = ctypes.c_short

    def pressed_buttons(self):
        return {button for button in (0x01, 0x02, 0x04) if self.native.GetAsyncKeyState(button) < 0}

    def _bounds(self, hwnd):
        bounds = wintypes.RECT()
        if hwnd and self.native.IsWindowVisible(hwnd) and self.native.GetWindowRect(hwnd, ctypes.byref(bounds)):
            return bounds
        return None

    def anchor(self, screen):
        geometry = screen.geometry()
        scale = screen.devicePixelRatio()
        width = round(geometry.width() * scale)
        height = round(geometry.height() * scale)

        def is_primary_bar(rect):
            return rect and rect.top <= 120 * scale and 0 <= rect.bottom <= 160 * scale and rect.left <= width // 2 < rect.right

        bounds = self._bounds(self.bar)
        if not is_primary_bar(bounds):
            self.bar = None
            hwnd = self.native.FindWindowExW(None, None, None, 'YasbBar')
            while hwnd:
                candidate = self._bounds(hwnd)
                if is_primary_bar(candidate):
                    self.bar, bounds = hwnd, candidate
                    break
                hwnd = self.native.FindWindowExW(None, hwnd, None, 'YasbBar')
        if not self.bar:
            return None

        foreground = self.native.GetForegroundWindow()
        active = self._bounds(foreground)
        if active and not self.native.IsZoomed(foreground) and (
            active.left <= 2 and active.top <= 2 and active.right >= width - 2 and active.bottom >= height - 2
        ):
            name = ctypes.create_unicode_buffer(96)
            self.native.GetClassNameW(foreground, name, len(name))
            if name.value not in ('Progman', 'WorkerW', 'Shell_TrayWnd'):
                return None

        center = geometry.x() + round((bounds.left + bounds.right) / (2 * scale))
        top = geometry.y() + round(bounds.top / scale)
        bar_height = round((bounds.bottom - bounds.top) / scale)
        return center, top + max(0, (bar_height - 28) // 2)


def rounded(rect, radius):
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class Island(QWidget):
    refresh_notifications = Signal()
    avatar_loaded = Signal(QImage)
    WIDTH = WIDTH
    HEIGHT = HEIGHT
    PILL_HEIGHT = 32

    def __init__(self, command, release_pause):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowTitle('YASB Dynamic Island')
        self.setAccessibleName('Dynamic Island — điều khiển phương tiện')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedSize(self.WIDTH, self.PILL_HEIGHT)
        self.command = command
        self.release_pause = release_pause
        self.dock = Dock()
        self.glass = GlassLayer()
        self.volume = OutputVolume()
        self.dashboard = Dashboard()
        self.dashboard.weather.changed.connect(self.update)
        self.dashboard.metrics.changed.connect(self.update)
        self.dashboard.live.changed.connect(self._activity_changed)
        self.dashboard.live.timer_finished.connect(self._timer_finished)
        self.avatar_loaded.connect(self._set_avatar, Qt.ConnectionType.QueuedConnection)
        self._avatar_loading = False
        self.state = MediaState()
        self.art = QImage()
        self.compact_media = ('', QImage())
        self.codex_turns = ()
        self.codex_chip = None
        self.notice = ('', 0)
        self.notice_icon = QImage()
        self.notice_kind = 'notification'
        self.output_id = None
        self.output_label = ''
        self.pulse_started = 0.0
        self.pulse_duration = 0.5
        self.slot_sizes = self.slot_origin = self.slot_target = (0.0,) * 5
        self.expanded = False
        self.hovered = False
        self.hot_action = None
        self.press_action = None
        self.drawer_frame = None
        self.buttons = set()
        self.drag = None
        self.preview = None
        self.pending_seek = None
        self.last_volume_change = 0.0
        self.motion = (116.0, 28.0, 0.0, 0.0, 0.0)
        self.origin = self.target = self.motion
        self.started = 0.0
        self.duration = 0.0
        self.animation = QTimer(self, interval=8, timerType=Qt.TimerType.PreciseTimer)
        self.animation.timeout.connect(self._step)
        self.tab_frames = QTimer(self, interval=8, timerType=Qt.TimerType.PreciseTimer)
        self.tab_frames.timeout.connect(self._step_tab)
        self.meter = QTimer(self, interval=34)
        self.meter.timeout.connect(self._repaint_media)
        self.outside_click = QTimer(self, interval=12, timerType=Qt.TimerType.PreciseTimer)
        self.outside_click.timeout.connect(self._dismiss_on_click_away)
        self.volume_poll = QTimer(self, interval=1000)
        self.volume_poll.timeout.connect(self._refresh_volume)
        self.dashboard_poll = QTimer(self, interval=1000)
        self.dashboard_poll.timeout.connect(self._refresh_dashboard)
        self.anchor_timer = QTimer(self, interval=400)
        self.anchor_timer.timeout.connect(self.follow_bar)
        self.codex_clock = QTimer(self, interval=1000)
        self.codex_clock.timeout.connect(self.update)
        self.codex_done = QTimer(self, interval=1900, singleShot=True)
        self.codex_done.timeout.connect(self._retarget)
        self.notification = QTimer(self, interval=5000, singleShot=True)
        self.notification.timeout.connect(self._retarget)
        self.timer_done = QTimer(self, interval=2400, singleShot=True)
        self.timer_done.timeout.connect(self._retarget)
        self.output_notice = QTimer(self, interval=2200, singleShot=True)
        self.output_notice.timeout.connect(self._retarget)
        self.output_refresh = QTimer(self, interval=140, singleShot=True)
        self.output_refresh.timeout.connect(self._output_changed)
        self.volume.device_changed.connect(self.output_refresh.start, Qt.ConnectionType.QueuedConnection)
        self.pulse = QTimer(self, interval=16)
        self.pulse.timeout.connect(self._step_pulse)
        QTimer.singleShot(180, self._warm_up)

    def _warm_up(self):
        self.glass.prepare()
        if self.dashboard.avatar.isNull():
            self._refresh_avatar()
        self.dashboard.metrics.sample(details=True)
        if not self.expanded:
            for tab in TAB_RECTS:
                self.dashboard.tab = tab
                self._drawer_snapshot()
            self.dashboard.tab = 'Dashboard'

    def _refresh_avatar(self):
        if not self._avatar_loading:
            self._avatar_loading = True
            threading.Thread(target=self._load_avatar, daemon=True, name='Windows account picture').start()

    def _load_avatar(self):
        try:
            data = asyncio.run(asyncio.wait_for(_account_picture(), 2.0))
        except (OSError, RuntimeError, asyncio.TimeoutError):
            logging.debug('Windows account picture unavailable', exc_info=True)
            data = b''
        self.avatar_loaded.emit(QImage.fromData(data) if data else QImage())

    def _set_avatar(self, image):
        self._avatar_loading = False
        if image != self.dashboard.avatar:
            self.dashboard.avatar = image
            self.drawer_frame = None
            if self.expanded and self.dashboard.tab == 'Dashboard':
                self.update()

    def _repaint_media(self):
        if not self.animation.isActive() and not self.tab_frames.isActive():
            self.update()

    def _step_tab(self):
        if self.dashboard.progress() >= 1.0:
            self.tab_frames.stop()
        self.update()

    def follow_bar(self):
        screen = QApplication.primaryScreen()
        anchor = self.dock.anchor(screen) if screen else None
        if anchor:
            center, y = anchor
            self.move(center - self.WIDTH // 2, y)
            if not self.isVisible():
                self.show()
                self._sync_meter()
            self._sync_glass()
        elif self.isVisible():
            self.hide()
            self.hovered = False
            self._set_expanded(False)
            self._sync_meter()

    def hideEvent(self, event):
        self.glass.hide()
        self.dashboard.animate_cat(False)
        self.dashboard_poll.stop()
        self.tab_frames.stop()
        self.codex_clock.stop()
        self.pulse.stop()
        super().hideEvent(event)

    def _sync_meter(self):
        shows_progress = not self.expanded or self.dashboard.tab in ('Dashboard', 'Media')
        animate_meter = self.isVisible() and self.state.playing and shows_progress
        self.dashboard.animate_cat(animate_meter and self.expanded and self.dashboard.tab == 'Dashboard')
        if animate_meter and not self.meter.isActive():
            self.meter.start()
        elif not animate_meter:
            self.meter.stop()
        show_clock = self.isVisible() and not self.expanded and bool(self.codex_turns)
        if show_clock and not self.codex_clock.isActive():
            self.codex_clock.start()
        elif not show_clock:
            self.codex_clock.stop()

    def set_media(self, state):
        if self._track_key(state) != self._track_key(self.state):
            if self.drag == 'seek':
                self.drag = None
                self.preview = None
            self.pending_seek = None
        if self.pending_seek and abs(state.elapsed() - self.pending_seek[0]) < 1.0:
            self.pending_seek = None
        if state.artwork != self.state.artwork:
            self.art = QImage.fromData(state.artwork) if state.artwork else QImage()
            if not self.art.isNull():
                self.art = self.art.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                           Qt.TransformationMode.SmoothTransformation)
        self.state = state
        if state.playing:
            self.compact_media = state.title, self.art
        self._retarget()
        self._sync_meter()
        self.update()

    def set_codex(self, turns, ended):
        previous = self.codex_chip
        self.codex_turns = turns
        self.dashboard.live.turns = turns
        if ended:
            self.dashboard.live.ended = ended
        if turns:
            self.codex_done.stop()
            self.codex_chip = turns[0]
        elif ended:
            self.codex_chip = next((turn for turn in ended if previous and turn.turn_id == previous.turn_id),
                                   ended[-1])
            self.codex_done.start()
        self._retarget()
        self._sync_meter()
        self.update()

    def show_notification(self, app, count, image=None):
        if self.notification.isActive():
            count = min(999, count + self.notice[1])
        self.notice = app, count
        self.notice_icon = image if image is not None else QImage()
        self.notice_kind = 'notification'
        if not self.notification.isActive():
            self._start_pulse(1.0)
        self.output_notice.stop()
        self.notification.start()
        self._retarget()
        self.update()

    def _activity_changed(self):
        if not self.dashboard.live.finished:
            self.timer_done.stop()
        self._retarget()
        self.update()

    def _timer_finished(self):
        QApplication.beep()
        self.timer_done.start()
        self._start_pulse()
        self._activity_changed()

    def start_audio_watch(self):
        self.volume.watch()
        if self.volume.device is not None:
            self.output_id = self.volume.device.id
            self.dashboard.live.output = self.volume.device.FriendlyName

    def _output_changed(self):
        self.volume.refresh()
        picker_open = self.expanded and self.dashboard.tab == 'Live Activity' and self.dashboard.live.output_open
        if picker_open:
            self._sync_live_output(devices=True)
            self.update()
        device = self.volume.device
        key = device.id if device is not None else None
        if key == self.output_id:
            return
        self.output_id = key
        self.dashboard.live.output = device.FriendlyName if device is not None else ''
        self.output_label = self.dashboard.live.output or 'Đầu ra đã ngắt'
        if not self.notification.isActive():
            self.notice_kind = 'output'
            self.output_notice.start()
            self._start_pulse()
        if not picker_open:
            self._refresh_volume()
        self._activity_changed()

    def _start_pulse(self, duration=0.5):
        if self.isVisible() and not self.expanded:
            self.pulse_started = time.monotonic()
            self.pulse_duration = duration
            self.pulse.start()

    def _step_pulse(self):
        if time.monotonic() - self.pulse_started >= self.pulse_duration:
            self.pulse.stop()
        self.update()

    def _slot_widths(self):
        media = self.state.playing
        codex = bool(self.codex_turns) or self.codex_done.isActive()
        countdown = self.dashboard.live.deadline is not None or self.timer_done.isActive()
        stopwatch = self.dashboard.live.stopwatch_start is not None
        notice = self.notification.isActive()
        output = self.output_notice.isActive()
        count = sum((media, codex, countdown, stopwatch))
        media_width = 152.0 if notice and count > 2 else 186.0 if count > 1 else 250.0
        return (media_width if media else 0.0,
                130.0 if codex and count > 1 else 150.0 if codex else 0.0,
                (69.0 if count > 1 else 134.0) if countdown else 0.0,
                (69.0 if count > 1 else 134.0) if stopwatch else 0.0,
                self._notice_banner_width() if notice else (34.0 if count else 166.0) if output else 0.0)

    def _retarget(self):
        slots = self._slot_widths()
        if self.expanded:
            target = (float(PANEL_WIDTH), float(self.HEIGHT), 0.0, 1.0, 0.0)
        else:
            width = sum(slots)
            lift = 14.0 if width else 12.0
            target = ((width or 116.0) + lift * self.hovered, 28.0, float(bool(width)), 0.0, float(self.hovered))
        if target == self.target and (slots == self.slot_target or self.expanded):
            if self.expanded:
                self.slot_sizes = self.slot_target = slots
            return
        if target[1] > 28.0:
            self.duration = 0.29
        elif self.motion[1] > 28.0:
            self.duration = 0.23
        else:
            self.duration = 0.16
        self.origin, self.target = self.motion, target
        self.slot_origin, self.slot_target = self.slot_sizes, slots
        self.started = time.perf_counter()
        if self.isVisible():
            self.animation.start()
        else:
            self.motion = target
            self.slot_sizes = slots
            self.animation.stop()
            if not self.expanded:
                self.setFixedHeight(self.PILL_HEIGHT)

    def _step(self):
        elapsed = (time.perf_counter() - self.started) / self.duration
        if elapsed >= 1.0:
            self.motion = self.target
            self.slot_sizes = self.slot_target
            self.animation.stop()
            self.drawer_frame = None
            if not self.expanded:
                self.setFixedHeight(self.PILL_HEIGHT)
        else:
            t = 1.0 - (1.0 - elapsed) ** 4
            self.motion = tuple(a + (b - a) * t for a, b in zip(self.origin, self.target))
            self.slot_sizes = tuple(a + (b - a) * t for a, b in zip(self.slot_origin, self.slot_target))
        self._sync_glass()
        self.update()

    def _surface_rect(self):
        width, height = self.motion[:2]
        return QRectF((self.WIDTH - width) / 2, 0.5, width, height - 1)

    def _surface(self):
        rect = self._surface_rect()
        return rounded(rect, min(19, rect.height() / 2))

    def _sync_glass(self):
        if self.isVisible() and self.glass.hwnd and self.motion[3] > 0.92:
            front = int(self.winId())
            rect = self._surface_rect()
            self.glass.sync(front, self.dock._bounds(front), rect, min(19, rect.height() / 2), self.devicePixelRatioF())
        else:
            self.glass.hide()

    def _pointer_inside(self):
        return self._surface().contains(QPointF(self.mapFromGlobal(QCursor.pos())))

    def _set_hovered(self, inside):
        if inside != self.hovered:
            self.hovered = inside
            self._retarget()

    def _set_expanded(self, expanded):
        was_expanded = self.expanded
        self.expanded = expanded
        self.drawer_frame = None
        if expanded:
            self.setFixedHeight(self.HEIGHT)
            if not self.glass.hwnd and not self.glass.failed:
                QTimer.singleShot(0, self.glass.prepare)
            self.dashboard.opened()
            self.refresh_notifications.emit()
            self._refresh_avatar()
            self.dashboard_poll.start()
            self.buttons = self.dock.pressed_buttons()
            self.outside_click.start()
            self.volume_poll.start()
        else:
            self.outside_click.stop()
            self.volume_poll.stop()
            self.dashboard_poll.stop()
            self.tab_frames.stop()
            self.buttons.clear()
            self.drag = None
            self.preview = None
            self.pending_seek = None
            if was_expanded:
                self.release_pause()
        self._retarget()
        self._sync_meter()

    def _refresh_volume(self):
        if not self.expanded or self.drag is not None or self.press_action is not None:
            return
        if self.dashboard.tab == 'Media':
            self.dashboard.audio.refresh(self.volume)
            self.update()
        elif self.dashboard.tab == 'Live Activity' and self.dashboard.live.output_open:
            self.volume.refresh()
            self._sync_live_output()
            self.update()

    def _sync_live_output(self, devices=False):
        live = self.dashboard.live
        device = self.volume.device
        live.set_outputs(self.volume.outputs() if devices else live.outputs, device.id if device else None,
                         self.volume.level, self.volume.muted)

    def _live_output_action(self, action):
        live = self.dashboard.live
        match action[1]:
            case 'output':
                live.output_open = not live.output_open
                live.confirm_clear = live.output_error = False
                if live.output_open:
                    self.volume.refresh()
                    self._sync_live_output(devices=True)
            case 'output_device':
                device_id = action[2]
                if device_id != live.output_id and any(key == device_id for key, _ in live.outputs):
                    live.output_error = not self.volume.select_output(device_id)
                    self._output_changed()
            case 'output_mute':
                self.volume.toggle_mute()
                self._sync_live_output()
        self.update()

    def _refresh_dashboard(self):
        self.dashboard.sample()
        self.update()

    def _dismiss_on_click_away(self):
        buttons = self.dock.pressed_buttons()
        if buttons - self.buttons and self.drag is None and not self._pointer_inside():
            self.hovered = False
            self._set_expanded(False)
        else:
            self.buttons = buttons

    def enterEvent(self, event):
        self._set_hovered(self._surface().contains(event.position()))

    def leaveEvent(self, event):
        self._set_hovered(False)
        self.hot_action = None
        if self.expanded:
            self.update()

    def mouseMoveEvent(self, event):
        point = event.position()
        if self.drag is not None:
            self._update_drag(point)
            return
        inside = self._surface().contains(point)
        self._set_hovered(inside)
        action = self._action_at(point)
        nav = self.dashboard.is_dashboard_action(action)
        app_audio = self.dashboard.audio.is_action(action)
        live = self.dashboard.live.is_action(action)
        clickable = inside and (not self.expanded or nav or app_audio or live
                                or player.enabled(action, self.state, self.volume))
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
        hint = {'month_prev': 'Tháng trước', 'month_next': 'Tháng sau', 'today': 'Về tháng hiện tại', 'drive': 'Đổi ổ đĩa',
                'refresh': 'Cập nhật dự báo'}.get(action, '') if nav else player.tooltip(action, self.state, self.volume)
        if app_audio:
            hint = self.dashboard.audio.tooltip(action)
        elif live:
            hint = self.dashboard.live.tooltip(action)
        elif action == 'open':
            hint = ''
            if self.notification.isActive() and self._compact_rects(self._surface_rect())[-1].contains(point):
                app, count = self.notice
                hint = f'{app or "Thông báo Windows"} · {count} mới'
            elif self.output_notice.isActive() and self._compact_rects(self._surface_rect())[-1].contains(point):
                hint = self.output_label
        if hint != self.toolTip():
            self.setToolTip(hint)
        if self.expanded and action != self.hot_action:
            self.hot_action = action
            self.update()

    def _action_at(self, point):
        if self.expanded:
            return self.dashboard.action_at(point, self.state) if self.motion[3] >= 0.95 else None
        # Every segment in the collapsed pill shares the menu's click target.
        return 'open'

    @staticmethod
    def _track_key(state):
        return state.generation, state.title, state.artist, state.start

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._surface().contains(event.position()):
            return
        action = self._action_at(event.position())
        self.press_action = action
        if action == 'volume':
            self.volume.refresh()
        if action in ('seek', 'volume') and player.enabled(action, self.state, self.volume):
            self.drag = action
            self._update_drag(event.position())
        elif action == ('live', 'output_volume') and self.volume.level is not None:
            self.drag = 'live_volume'
            self._update_drag(event.position())
        elif self.dashboard.audio.is_action(action) and action[0] == 'app_volume':
            self.drag = action
            self._update_drag(event.position())
        event.accept()

    def _update_drag(self, point):
        rect = {'seek': tab_views.SEEK, 'live_volume': OUTPUT_VOLUME}.get(self.drag, tab_views.VOLUME)
        ratio = min(1.0, max(0.0, (point.x() - rect.left()) / rect.width()))
        if self.drag == 'seek':
            self.preview = ratio * self.state.duration
        else:
            self.preview = round(ratio * 100)
            if self.drag == 'live_volume':
                self.dashboard.live.volume_level = self.preview
            now = time.monotonic()
            if now - self.last_volume_change >= 0.04:
                self._write_drag_volume()
                self.last_volume_change = now
        self.update()

    def _write_drag_volume(self):
        if self.drag in ('volume', 'live_volume'):
            self.volume.set_level(self.preview)
            if self.drag == 'live_volume':
                self._sync_live_output()
        else:
            self.dashboard.audio.set_level(self.drag[1], self.preview)

    def _finish_drag(self, point):
        self._update_drag(point)
        if self.drag == 'seek' and player.enabled('seek', self.state, self.volume):
            self.command(self.state.generation, 'seek', self.state.start + self.preview)
            self.pending_seek = self.preview, time.monotonic() + 0.8
        elif self.drag != 'seek':
            self._write_drag_volume()
        self.drag = None
        self.preview = None
        self.update()

    def mouseReleaseEvent(self, event):
        point = event.position()
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pressed, self.press_action = self.press_action, None
        if self.drag is not None:
            self._finish_drag(point)
            return
        if not self._surface().contains(point):
            return
        action = self._action_at(point)
        if pressed != action:
            return
        if action in ('close', 'open'):
            if self.expanded:
                compact_width = sum(self._slot_widths()) or 116.0
                self.hovered = abs(point.x() - self.WIDTH / 2) < compact_width / 2
            self._set_expanded(not self.expanded)
        elif action in TAB_RECTS:
            self._switch_tab(action)
        elif self.dashboard.live.is_action(action):
            if action[1] in ('output', 'output_device', 'output_mute'):
                self._live_output_action(action)
            else:
                if action[1] in ('codex', 'center'):
                    self._set_expanded(False)
                self.dashboard.live.activate(action)
        elif self.dashboard.is_dashboard_action(action):
            self.dashboard.activate(action)
            self.update()
        elif self.dashboard.audio.is_action(action) and action[0] == 'app_mute':
            self.dashboard.audio.toggle_mute(action[1])
            self.update()
        elif player.enabled(action, self.state, self.volume):
            if action == 'mute':
                self.volume.toggle_mute()
                self.update()
            elif action == 'shuffle':
                self.command(self.state.generation, action, not self.state.shuffle)
            elif action == 'repeat':
                self.command(self.state.generation, action, player.REPEAT_NEXT[self.state.repeat])
            elif action in ('previous', 'toggle', 'next'):
                self.command(self.state.generation, action, 0.0)

    def _switch_tab(self, tab):
        if tab == 'Media' and tab != self.dashboard.tab:
            self.dashboard.audio.refresh(self.volume)
        elif tab == 'Live Activity' and tab != self.dashboard.tab:
            self.refresh_notifications.emit()
        if self.dashboard.switch(tab, self.state, self.art, self.volume, self.devicePixelRatioF()):
            self.tab_frames.start()
            self._sync_meter()
            self.update()

    def wheelEvent(self, event):
        if not self.expanded or self.drag is not None:
            return
        delta = event.angleDelta()
        vertical = delta.y() or event.pixelDelta().y()
        action = self._action_at(event.position())
        if vertical and action in ('volume', ('live', 'output_volume')) and self.volume.level is not None:
            self.volume.set_level(max(0, min(100, self.volume.level + (3 if vertical > 0 else -3))))
            if action != 'volume':
                self._sync_live_output()
            self.update()
            event.accept()
        elif vertical and self.dashboard.tab == 'Media' and ROWS.contains(event.position()):
            if self.dashboard.audio.scroll(vertical):
                self.update()
            event.accept()
        elif vertical and self.dashboard.tab == 'Live Activity' and self.dashboard.live.scroll(
                event.position(), vertical, pixels=not bool(delta.y())):
            event.accept()
        elif delta.x() and not self.tab_frames.isActive():
            tabs = tuple(TAB_RECTS)
            i = tabs.index(self.dashboard.tab) + (1 if delta.x() < 0 else -1)
            if 0 <= i < len(tabs):
                self._switch_tab(tabs[i])
                event.accept()

    def _wave(self, painter, x, y, color, playing=False):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        now = time.monotonic()
        for i, rest in enumerate((4, 7, 10, 6)):
            height = 3 + (rest + 1) * (0.52 + 0.48 * math.sin(now * (6 + i) + i)) if playing else rest
            painter.drawRoundedRect(QRectF(x + i * 4, y - height / 2, 2, height), 1, 1)

    def _compact_rects(self, rect):
        x = rect.center().x() - sum(self.slot_sizes) / 2
        result = []
        for width in self.slot_sizes:
            result.append(QRectF(x, rect.top(), width, 27.0))
            x += width
        return result

    def _draw_compact(self, painter, rect):
        opacity = painter.opacity()
        occupied = False
        for kind, slot in zip(('media', 'codex', 'timer', 'watch', 'notification'), self._compact_rects(rect)):
            if slot.width() < 2:
                continue
            painter.save()
            painter.setClipRect(slot, Qt.ClipOperation.IntersectClip)
            painter.setOpacity(opacity * min(1.0, slot.width() / 42))
            if occupied:
                painter.setPen(QPen(QColor(SURFACE2), 1))
                painter.drawLine(QPointF(slot.left() + 0.5, 8), QPointF(slot.left() + 0.5, 20))
            if kind == 'media':
                title, art = self.compact_media
                player.artwork(painter, art, QRectF(slot.left() + 8, 4, 20, 20), 6)
                player.text(painter, title, QRectF(slot.left() + 35, 1, max(0.0, slot.width() - 66), 26),
                            12, player.INK, QFont.Weight.DemiBold)
                if slot.width() >= 72:
                    self._wave(painter, slot.right() - 24, 14, PINK, self.state.playing)
            elif kind == 'codex' and self.codex_chip:
                turn = self.codex_chip
                label_width = slot.width() - 32
                weight = QFont.Weight.DemiBold
                if turn.status == 'inProgress':
                    minutes, seconds = divmod(max(0, int(time.time()) - turn.started), 60)
                    extra = f' +{len(self.codex_turns) - 1}' if len(self.codex_turns) > 1 else ''
                    label = f'Codex{extra}'
                    glyph, accent = 'terminal', MAUVE
                    clock = f'{minutes:02}:{seconds:02}'
                    clock_width = QFontMetrics(player._font(11, weight)).horizontalAdvance(clock) + 2
                    clock_left = slot.right() - 10 - clock_width
                    label_width = clock_left - slot.left() - 33
                    player.text(painter, clock, QRectF(clock_left, 1, clock_width, 26),
                                11, player.INK, weight, Qt.AlignmentFlag.AlignRight)
                elif turn.status == 'completed':
                    label, glyph, accent = 'Codex · Xong', 'check', MAUVE
                else:
                    label = 'Codex · Lỗi' if turn.status == 'failed' else 'Codex · Đã dừng'
                    glyph, accent = 'stop', PINK
                icon(painter, glyph, slot.left() + 15, 14, 14, accent)
                player.text(painter, label, QRectF(slot.left() + 27, 1, max(0.0, label_width), 26),
                            11, player.INK, weight)
            elif kind == 'notification':
                if self.notice_kind == 'notification':
                    self._draw_notice_banner(painter, slot)
                else:
                    icon(painter, 'headphones', slot.left() + 14, 14, 13, LAVENDER)
                    label = '' if occupied else self.output_label
                    player.text(painter, label, QRectF(slot.left() + 24, 1, max(0.0, slot.width() - 27), 26),
                                11, LAVENDER, QFont.Weight.DemiBold)
            elif kind in ('timer', 'watch'):
                live = self.dashboard.live
                if kind == 'timer':
                    done = live.finished
                    glyph, label, color = ('check' if done else 'hourglass'), 'Hẹn giờ', PINK
                    value = 'Xong' if done else clock_text(live.countdown)
                else:
                    glyph, label, color = 'stopwatch', 'Bấm giờ', LAVENDER
                    value = clock_text(live.stopwatch)
                icon(painter, glyph, slot.left() + 14, 14, 13, color)
                if slot.width() >= 110:
                    player.text(painter, label, QRectF(slot.left() + 26, 1, 62, 26), 11, player.INK, QFont.Weight.DemiBold)
                player.text(painter, value, QRectF(slot.left() + 24, 1, max(0.0, slot.width() - 33), 26),
                            11, color, QFont.Weight.DemiBold, Qt.AlignmentFlag.AlignRight)
            painter.restore()
            occupied = True

    def _notice_text_metrics(self):
        weight = QFont.Weight.DemiBold
        label_width = QFontMetrics(player._font(11, weight)).horizontalAdvance(NOTICE_LABEL) + 2
        count = f'+{min(99, self.notice[1])}' if self.notice[1] > 1 else ''
        count_width = QFontMetrics(player._font(10, weight)).horizontalAdvance(count) + 2 if count else 0
        return label_width, count, count_width

    def _notice_banner_width(self):
        label_width, count, count_width = self._notice_text_metrics()
        return (2 * NOTICE_PADDING + NOTICE_ICON_SIZE + NOTICE_GAP + label_width
                + (NOTICE_GAP + count_width if count else 0))

    def _draw_notice_banner(self, painter, slot):
        label_width, count, count_width = self._notice_text_metrics()
        content_width = NOTICE_ICON_SIZE + NOTICE_GAP + label_width + (NOTICE_GAP + count_width if count else 0)
        x = slot.center().x() - content_width / 2
        app = self.notice[0]
        target = QRectF(x, 4, NOTICE_ICON_SIZE, NOTICE_ICON_SIZE)
        if not self.notice_icon.isNull():
            player.artwork(painter, self.notice_icon, target, 5)
        elif app:
            player.pill(painter, target, 5, SURFACE2)
            player.text(painter, app[0].upper(), target, 11, PINK, QFont.Weight.DemiBold,
                        Qt.AlignmentFlag.AlignHCenter)
        else:
            icon(painter, 'bell', target.center().x(), 14, 14, PINK)
        text_x = target.right() + NOTICE_GAP
        player.text(painter, NOTICE_LABEL, QRectF(text_x, 1, label_width, 26),
                    11, PINK, QFont.Weight.DemiBold)
        if count:
            player.text(painter, count, QRectF(text_x + label_width + NOTICE_GAP, 1, count_width, 26),
                        10, MAUVE, QFont.Weight.DemiBold)

    def _drawer_snapshot(self):
        scale = self.devicePixelRatioF()
        image = QImage(round(self.WIDTH * scale), round(self.HEIGHT * scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.dashboard.draw(painter, self.state, self.art, self.volume, None)
        painter.end()
        return image

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        surface = self._surface()
        _, _, compact, expanded, highlight = self.motion
        glass_mix = max(0.0, (expanded - 0.92) / 0.08) if self.glass.visible else 0.0
        reveal = min(1.0, expanded / 0.55)
        fill = QColor(MANTLE if expanded > 0.4 else CRUST)
        # A layered window needs a nonzero alpha to keep the pill's click area.
        fill.setAlpha(max(1, round((255 - 58 * glass_mix) * reveal)))
        painter.fillPath(surface, fill)
        if glass_mix > 0.01:
            rect = surface.boundingRect()
            reflection = QLinearGradient(rect.topLeft(), rect.bottomRight())
            for position, strength, color in ((0.0, 132, PINK), (0.33, 62, MAUVE), (0.65, 34, MAUVE), (1.0, 82, PINK)):
                stop = QColor(color)
                stop.setAlpha(round(27 + (strength - 27) * glass_mix))
                reflection.setColorAt(position, stop)
            painter.strokePath(surface, QPen(QBrush(reflection), 0.85))
        else:
            edge = QColor(MAUVE if highlight > 0.3 else SURFACE2)
            edge.setAlpha(round(112 + 78 * highlight))
            painter.strokePath(surface, QPen(edge, 1))
        if self.pulse.isActive() and not self.expanded:
            fade = max(0.0, 1.0 - (time.monotonic() - self.pulse_started) / self.pulse_duration)
            edge = QColor(PINK)
            edge.setAlpha(round(205 * fade))
            painter.strokePath(surface, QPen(edge, 1.35))
        painter.setClipPath(surface)
        idle = max(0.0, 1.0 - compact - expanded)
        if idle > 0.01:
            painter.setOpacity(idle)
            icon(painter, 'grid', self.WIDTH / 2, 14, 13, MAUVE)
        if compact > 0.01:
            painter.setOpacity(compact * (1.0 - expanded))
            self._draw_compact(painter, surface.boundingRect())
        if expanded > 0.4:
            painter.setOpacity(((expanded - 0.4) / 0.6) ** 2)
            if self.animation.isActive() and not self.tab_frames.isActive():
                if self.drawer_frame is None:
                    self.drawer_frame = self._drawer_snapshot()
                painter.drawImage(QPointF(0, -9 * (1 - expanded)), self.drawer_frame)
                return
            hover = self._action_at(QPointF(self.mapFromGlobal(QCursor.pos())))
            seek = self.preview if self.drag == 'seek' else None
            if seek is None and self.pending_seek and self.pending_seek[1] > time.monotonic():
                seek = self.pending_seek[0]
            audio_preview = (self.drag, self.preview) if self.dashboard.audio.is_action(self.drag) else None
            self.dashboard.draw(painter, self.state, self.art, self.volume, hover, seek,
                                self.preview if self.drag == 'volume' else None, audio_preview)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[RotatingFileHandler(ROOT / 'island.log', maxBytes=256_000,
                                                     backupCount=1, encoding='utf-8')])
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(ROOT / 'instance.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        return 0
    worker = MediaWorker()
    island = Island(worker.command, worker.release_pause)
    codex = CodexActivity()
    notifications = NotificationReceiver(ROOT)
    codex.changed.connect(island.set_codex, Qt.ConnectionType.QueuedConnection)
    notifications.received.connect(island.show_notification)
    notifications.snapshot.connect(island.dashboard.live.set_notifications)
    island.dashboard.live.dismiss_requested.connect(notifications.request)
    island.dashboard.live.clear_requested.connect(notifications.clear)
    island.refresh_notifications.connect(notifications.request)
    worker.changed.connect(island.set_media, Qt.ConnectionType.QueuedConnection)
    app.aboutToQuit.connect(codex.stop)
    app.aboutToQuit.connect(worker.stop)
    app.aboutToQuit.connect(island.volume.stop)
    app.aboutToQuit.connect(island.glass.close)
    app.aboutToQuit.connect(island.dashboard.metrics.close)
    island.follow_bar()
    island.anchor_timer.start()
    codex.start()
    island.start_audio_watch()
    notifications.request()
    logging.info('Dynamic Island started')
    try:
        return app.exec()
    finally:
        lock.unlock()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        logging.exception('Dynamic Island exited unexpectedly')
        raise
