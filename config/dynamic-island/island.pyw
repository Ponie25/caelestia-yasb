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
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget
from winrt.windows.system import User, UserPictureSize

from audio_mixer import ROWS
import player
from dashboard import Dashboard, HEIGHT, PANEL_WIDTH, TAB_RECTS, WIDTH
import tab_views
from glass import GlassLayer
from icons import icon
from media import MediaState, MediaWorker, read_image_bytes
from palette import CRUST, MAUVE, MANTLE, PINK, SURFACE2
from volume import OutputVolume


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
        self.avatar_loaded.connect(self._set_avatar, Qt.ConnectionType.QueuedConnection)
        self._avatar_loading = False
        self.state = MediaState()
        self.art = QImage()
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
        super().hideEvent(event)

    def _sync_meter(self):
        shows_progress = not self.expanded or self.dashboard.tab in ('Dashboard', 'Media')
        animate_meter = self.isVisible() and self.state.playing and shows_progress
        self.dashboard.animate_cat(animate_meter and self.expanded and self.dashboard.tab == 'Dashboard')
        if animate_meter and not self.meter.isActive():
            self.meter.start()
        elif not animate_meter:
            self.meter.stop()

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
        self._retarget()
        self._sync_meter()
        self.update()

    def _retarget(self):
        if self.expanded:
            target = (float(PANEL_WIDTH), float(self.HEIGHT), 0.0, 1.0, 0.0)
        else:
            width, lift = (250.0, 18.0) if self.state.playing else (116.0, 14.0)
            target = (width + lift * self.hovered, 28.0, float(self.state.playing), 0.0, float(self.hovered))
        if target == self.target:
            return
        if target[1] > 28.0:
            self.duration = 0.29
        elif self.motion[1] > 28.0:
            self.duration = 0.23
        else:
            self.duration = 0.16
        self.origin, self.target = self.motion, target
        self.started = time.perf_counter()
        if self.isVisible():
            self.animation.start()
        else:
            self.motion = target
            self.animation.stop()
            if not self.expanded:
                self.setFixedHeight(self.PILL_HEIGHT)

    def _step(self):
        elapsed = (time.perf_counter() - self.started) / self.duration
        if elapsed >= 1.0:
            self.motion = self.target
            self.animation.stop()
            self.drawer_frame = None
            if not self.expanded:
                self.setFixedHeight(self.PILL_HEIGHT)
        else:
            t = 1.0 - (1.0 - elapsed) ** 4
            self.motion = tuple(a + (b - a) * t for a, b in zip(self.origin, self.target))
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
        if self.expanded and self.dashboard.tab == 'Media' and self.drag is None and self.press_action is None:
            self.dashboard.audio.refresh(self.volume)
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
        clickable = inside and (not self.expanded or nav or app_audio or player.enabled(action, self.state, self.volume))
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
        hint = {'month_prev': 'Tháng trước', 'month_next': 'Tháng sau', 'today': 'Về tháng hiện tại', 'drive': 'Đổi ổ đĩa',
                'refresh': 'Cập nhật dự báo'}.get(action, '') if nav else player.tooltip(action, self.state, self.volume)
        if app_audio:
            hint = self.dashboard.audio.tooltip(action)
        if hint != self.toolTip():
            self.setToolTip(hint)
        if self.expanded and action != self.hot_action:
            self.hot_action = action
            self.update()

    def _action_at(self, point):
        return self.dashboard.action_at(point, self.state) if self.expanded and self.motion[3] >= 0.95 else None

    @staticmethod
    def _track_key(state):
        return state.generation, state.title, state.artist, state.start

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._surface().contains(event.position()):
            return
        action = self._action_at(event.position())
        self.press_action = action if self.expanded else 'open'
        if action == 'volume':
            self.volume.refresh()
        if action in ('seek', 'volume') and player.enabled(action, self.state, self.volume):
            self.drag = action
            self._update_drag(event.position())
        elif self.dashboard.audio.is_action(action) and action[0] == 'app_volume':
            self.drag = action
            self._update_drag(event.position())
        event.accept()

    def _update_drag(self, point):
        rect = tab_views.SEEK if self.drag == 'seek' else tab_views.VOLUME
        ratio = min(1.0, max(0.0, (point.x() - rect.left()) / rect.width()))
        if self.drag == 'seek':
            self.preview = ratio * self.state.duration
        else:
            self.preview = round(ratio * 100)
            now = time.monotonic()
            if now - self.last_volume_change >= 0.04:
                self._write_drag_volume()
                self.last_volume_change = now
        self.update()

    def _write_drag_volume(self):
        if self.drag == 'volume':
            self.volume.set_level(self.preview)
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
        if pressed != (action if self.expanded else 'open'):
            return
        if action == 'close' or not self.expanded:
            if self.expanded:
                compact_width = 250.0 if self.state.playing else 116.0
                self.hovered = abs(point.x() - self.WIDTH / 2) < compact_width / 2
            self._set_expanded(not self.expanded)
        elif action in TAB_RECTS:
            self._switch_tab(action)
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
        if self.dashboard.switch(tab, self.state, self.art, self.volume, self.devicePixelRatioF()):
            self.tab_frames.start()
            self._sync_meter()
            self.update()

    def wheelEvent(self, event):
        if not self.expanded or self.drag is not None:
            return
        delta = event.angleDelta()
        vertical = delta.y() or event.pixelDelta().y()
        if vertical and self._action_at(event.position()) == 'volume' and self.volume.level is not None:
            self.volume.set_level(max(0, min(100, self.volume.level + (3 if vertical > 0 else -3))))
            self.update()
            event.accept()
        elif vertical and self.dashboard.tab == 'Media' and ROWS.contains(event.position()):
            if self.dashboard.audio.scroll(vertical):
                self.update()
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

    def _compact(self, painter, rect):
        if rect.width() > 250:
            rect = QRectF(rect.center().x() - 125, rect.top(), 250, rect.height())
        player.artwork(painter, self.art, QRectF(rect.left() + 8, 4, 20, 20), 6)
        player.text(painter, self.state.title, QRectF(rect.left() + 36, 1, rect.width() - 72, 26),
                    12, player.INK, QFont.Weight.DemiBold)
        self._wave(painter, rect.right() - 24, 14, PINK, True)

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
        painter.setClipPath(surface)
        idle = max(0.0, 1.0 - compact - expanded)
        if idle > 0.01:
            painter.setOpacity(idle)
            icon(painter, 'grid', self.WIDTH / 2, 14, 13, MAUVE)
        if compact > 0.01 and self.state.playing:
            painter.setOpacity(compact * (1.0 - expanded))
            self._compact(painter, surface.boundingRect())
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
    worker.changed.connect(island.set_media, Qt.ConnectionType.QueuedConnection)
    app.aboutToQuit.connect(worker.stop)
    app.aboutToQuit.connect(island.glass.close)
    app.aboutToQuit.connect(island.dashboard.metrics.close)
    island.follow_bar()
    island.anchor_timer.start()
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
