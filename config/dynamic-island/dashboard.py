from datetime import date, datetime, timedelta
from pathlib import Path
import time

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QMovie, QPainter, QPen

from audio_mixer import AudioMixer
from icons import icon
from live_activity import LiveActivity, SUMMARY
from palette import BASE, LAVENDER, MANTLE, MAUVE, MUTED, OVERLAY, PINK, SURFACE, SURFACE2, TEXT
import player
from player import pill, text
from resources import Metrics
import tab_views
from weather import CITY, Weather, condition


WIDTH = 728
HEIGHT = 456
PANEL_WIDTH = 712
TABS = (('Dashboard', 'grid'), ('Media', 'music'), ('Performance', 'gauge'),
        ('Weather', 'cloud'), ('Live Activity', 'activity'))
TAB_RECTS = {name: QRectF(22 + 130 * i, 12, 124, 47) for i, (name, _) in enumerate(TABS)}
CLOSE = QRectF(679, 22, 26, 26)
WEATHER = QRectF(22, 77, 207, 97)
SYSTEM = QRectF(239, 77, 267, 97)
AVATAR = QRectF(251, 88, 72, 75)
CLOCK = QRectF(22, 184, 88, 255)
CALENDAR = QRectF(120, 184, 288, 255)
LEVELS = QRectF(418, 184, 88, 255)
MEDIA = QRectF(516, 77, 190, 362)
CAT = QRectF(552, 332, 118, 68)
MONTH_PREV = QRectF(134, 196, 27, 27)
MONTH_NEXT = QRectF(367, 196, 27, 27)
TODAY = QRectF(166, 196, 196, 27)
MINI_TRANSPORT = {'previous': 573, 'toggle': 611, 'next': 649}
MINI_Y = 313
BODY = QRectF(22, 72, 684, 370)
TAB_DURATION = 0.18
WEEK = ('T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN')
RESOURCES = (('CPU', 'cpu', MAUVE), ('RAM', 'ram', LAVENDER), ('Ổ đĩa', 'disk', PINK))
CENTER = Qt.AlignmentFlag.AlignHCenter
RIGHT = Qt.AlignmentFlag.AlignRight
DEMI = QFont.Weight.DemiBold


def _card(painter, rect, radius=19, tone=BASE):
    pill(painter, rect, radius, tone)


def _line(painter, x0, y, x1, color=SURFACE):
    painter.setPen(QPen(QColor(color), 1))
    painter.drawLine(QPointF(x0, y), QPointF(x1, y))


def _label(painter, value, x, y, width, height=22, size=13, color=TEXT, weight=QFont.Weight.Normal, align=None):
    text(painter, value, QRectF(x, y, width, height), size, color, weight, align or Qt.AlignmentFlag.AlignLeft)


def _button(painter, rect, glyph, hovered, color=MUTED):
    if hovered:
        pill(painter, rect, 8, SURFACE)
    icon(painter, glyph, rect.center().x(), rect.center().y(), 15, color)


def _fmt_uptime(seconds):
    minutes = max(0, int(seconds) // 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    return f'{days} ngày {hours} giờ' if days else f'{hours} giờ {minutes:02} phút'


class Dashboard:
    def __init__(self):
        self.tab = 'Dashboard'
        self.month = date.today().replace(day=1)
        self.metrics = Metrics()
        self.weather = Weather()
        self.avatar = QImage()
        self.cat = QMovie(str(Path(__file__).resolve().parent / 'assets' / 'bongocat.gif'))
        self.cat.setCacheMode(QMovie.CacheMode.CacheAll)
        self.cat.jumpToFrame(0)
        self.transition = None
        self.audio = AudioMixer()
        self.live = LiveActivity()

    def opened(self):
        self.tab = 'Dashboard'
        self.transition = None
        self.live.output_open = self.live.confirm_clear = False
        self.sample()

    def sample(self):
        self.metrics.sample(details=self.tab == 'Performance')
        self.weather.refresh()

    def animate_cat(self, enabled):
        state = self.cat.state()
        if enabled and state == QMovie.MovieState.NotRunning:
            self.cat.start()
        elif enabled and state == QMovie.MovieState.Paused:
            self.cat.setPaused(False)
        elif not enabled and state == QMovie.MovieState.Running:
            self.cat.setPaused(True)

    def action_at(self, point, state):
        if CLOSE.contains(point):
            return 'close'
        for name, rect in TAB_RECTS.items():
            if rect.contains(point):
                return name
        if self.transition and self.progress() < 0.45:
            return None
        if self.tab == 'Media':
            return tab_views.media_target(point, state) or self.audio.action_at(point)
        if self.tab == 'Live Activity':
            return self.live.action_at(point)
        if self.tab == 'Weather' and tab_views.WEATHER_REFRESH.contains(point):
            return 'refresh'
        if self.tab == 'Performance' and len(self.metrics.drives) > 1 and tab_views.DRIVE_SWITCH.contains(point):
            return 'drive'
        if self.tab != 'Dashboard':
            return None
        for action, rect in (('Weather', WEATHER), ('Performance', LEVELS), ('month_prev', MONTH_PREV),
                             ('month_next', MONTH_NEXT), ('today', TODAY)):
            if rect.contains(point):
                return action
        if SUMMARY.contains(point):
            return 'Live Activity'
        if MEDIA.contains(point):
            if state.title:
                for action, x in MINI_TRANSPORT.items():
                    if QRectF(x - 16, MINI_Y - 15, 32, 30).contains(point):
                        return action
            return 'Media'
        return None

    @staticmethod
    def is_dashboard_action(action):
        return action in TAB_RECTS or action in ('refresh', 'month_prev', 'month_next', 'today', 'drive')

    def activate(self, action):
        if action == 'refresh':
            self.weather.refresh(force=True)
        elif action == 'drive':
            self.metrics.cycle_drive()
        elif action == 'today':
            self.month = date.today().replace(day=1)
        elif action == 'month_next':
            self.month = (self.month + timedelta(days=32)).replace(day=1)
        elif action == 'month_prev':
            self.month = (self.month - timedelta(days=1)).replace(day=1)

    def switch(self, tab, state, art, volume, scale):
        if self.tab == tab:
            return False
        direction = 1 if tuple(TAB_RECTS).index(tab) > tuple(TAB_RECTS).index(self.tab) else -1
        from_indicator = self.indicator()
        outgoing = self._snapshot(scale, lambda p: self._page(p, state, art, volume, None, None, None))
        if self.tab == 'Live Activity':
            self.live.confirm_clear = False
        self.tab = tab
        if tab == 'Weather':
            self.weather.refresh()
        elif tab == 'Performance':
            self.metrics.sample(details=True)
        incoming = self._snapshot(scale, lambda p: self._body(p, state, art, volume, None, None, None))
        self.transition = (outgoing, incoming, time.perf_counter(), direction, from_indicator)
        return True

    @staticmethod
    def _snapshot(scale, draw):
        image = QImage(round(BODY.width() * scale), round(BODY.height() * scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(-BODY.x(), -BODY.y())
        draw(painter)
        painter.end()
        return image

    def progress(self):
        if not self.transition:
            return 1.0
        t = min(1.0, (time.perf_counter() - self.transition[2]) / TAB_DURATION)
        return t * t * (3 - 2 * t)

    def indicator(self):
        end = TAB_RECTS[self.tab].center().x()
        if not self.transition:
            return end
        start = self.transition[4]
        return start + (end - start) * self.progress()

    def draw(self, painter, state, art, volume, hover, seek_preview=None, volume_preview=None, audio_preview=None):
        for name, glyph in TABS:
            rect = TAB_RECTS[name]
            active = name == self.tab
            if active or name == hover:
                _card(painter, rect, 10, SURFACE if active else BASE)
            accent = PINK if active else MUTED
            icon(painter, glyph, rect.center().x(), 27, 17, accent)
            _label(painter, name, rect.left(), 36, rect.width(), 19, 12, TEXT if active else MUTED, DEMI, CENTER)
        _line(painter, 22, 65, 706)
        pill(painter, QRectF(self.indicator() - 34, 61, 68, 2), 1, MAUVE)
        _button(painter, CLOSE, 'close', hover == 'close')
        self._page(painter, state, art, volume, hover, seek_preview, volume_preview, audio_preview)

    def _page(self, painter, state, art, volume, hover, seek_preview, volume_preview, audio_preview=None):
        t = self.progress()
        if self.transition and t < 1.0:
            outgoing, incoming, _, direction, _ = self.transition
            painter.save()
            opacity = painter.opacity()
            painter.setClipRect(BODY, Qt.ClipOperation.IntersectClip)
            painter.setOpacity(opacity * (1 - t))
            painter.drawImage(QPointF(BODY.x() - 28 * t * direction, BODY.y()), outgoing)
            painter.setOpacity(opacity * t)
            painter.drawImage(QPointF(BODY.x() + 28 * (1 - t) * direction, BODY.y()), incoming)
            painter.restore()
        else:
            self.transition = None
            self._body(painter, state, art, volume, hover, seek_preview, volume_preview, audio_preview)

    def _body(self, painter, state, art, volume, hover, seek_preview, volume_preview, audio_preview=None):
        if self.tab == 'Dashboard':
            self._overview(painter, state, art, hover)
        elif self.tab == 'Media':
            tab_views.media_view(painter, state, art, hover, seek_preview)
            app_drag, app_preview = audio_preview or (None, None)
            self.audio.draw(painter, volume, hover, volume_preview, app_drag, app_preview)
        elif self.tab == 'Performance':
            tab_views.performance_view(painter, self.metrics, hover)
        elif self.tab == 'Weather':
            tab_views.weather_view(painter, self.weather, hover, WEEK)
        else:
            self.live.draw(painter, hover)

    def _overview(self, painter, state, art, hover):
        _card(painter, WEATHER, 28, SURFACE if hover == 'Weather' else BASE)
        forecast = self.weather.forecast
        glyph, condition_text = condition(forecast.code) if forecast else ('cloud', 'Đang tải' if self.weather.loading else 'Xem dự báo')
        icon(painter, glyph, 71, 126, 47, LAVENDER)
        _label(painter, f'{forecast.temperature:.0f}°C' if forecast else '—°C', 112, 90, 104, 40, 30, PINK, DEMI)
        _label(painter, f'{CITY} · {condition_text}', 111, 133, 106, 21, 11, TEXT)

        _card(painter, SYSTEM, 21)
        if self.avatar.isNull():
            _card(painter, AVATAR, 21, SURFACE)
            icon(painter, 'user', AVATAR.center().x(), AVATAR.center().y(), 38, MAUVE)
        else:
            player.artwork(painter, self.avatar, AVATAR, 21)
        entries = (('windows', self.metrics.windows), ('desktop', self.metrics.desktop),
                   ('clock', f'Đã chạy {_fmt_uptime(time.time() - self.metrics.boot)}'))
        for i, (glyph, value) in enumerate(entries):
            y = 91 + 24 * i
            icon(painter, glyph, 343, y + 11, 12, (MAUVE, LAVENDER, PINK)[i])
            _label(painter, value, 358, y, 136, 22, 12)

        now = datetime.now()
        _card(painter, CLOCK, 16)
        _label(painter, now.strftime('%H'), 22, 237, 88, 55, 42, TEXT, DEMI, CENTER)
        for x in (58, 66, 74):
            pill(painter, QRectF(x - 1.6, 298, 3.2, 3.2), 1.6, MAUVE)
        _label(painter, now.strftime('%M'), 22, 307, 88, 55, 42, TEXT, DEMI, CENTER)
        _label(painter, WEEK[now.weekday()], 22, 368, 88, 23, 14, PINK, DEMI, CENTER)

        self._calendar(painter, hover)
        _card(painter, LEVELS, 16, SURFACE if hover == 'Performance' else BASE)
        for i, ((_, glyph, accent), value) in enumerate(zip(RESOURCES, self.metrics.percent)):
            x = 439 + i * 23
            pill(painter, QRectF(x - 3.5, 206, 7, 195), 3.5, SURFACE2)
            if value is not None and value > 0:
                height = max(3, 195 * value / 100)
                pill(painter, QRectF(x - 3.5, 401 - height, 7, height), 3.5, accent)
            icon(painter, glyph, x, 417, 14, accent)
        self._media_mini(painter, state, art, hover)

    def _calendar(self, painter, hover):
        _card(painter, CALENDAR, 19)
        _button(painter, MONTH_PREV, 'left', hover == 'month_prev')
        _button(painter, MONTH_NEXT, 'right', hover == 'month_next')
        if hover == 'today':
            pill(painter, TODAY, 8, SURFACE)
        _label(painter, f'Tháng {self.month.month} · {self.month.year}', 167, 196, 194, 27, 13, LAVENDER, DEMI, CENTER)
        for i, day in enumerate(WEEK):
            _label(painter, day, 133 + 38 * i, 228, 34, 21, 11, MUTED, DEMI, CENTER)
        first = self.month - timedelta(days=self.month.weekday())
        today = date.today()
        for i in range(42):
            day = first + timedelta(days=i)
            x, y = 133 + 38 * (i % 7), 252 + 28 * (i // 7)
            color = TEXT if day.month == self.month.month else OVERLAY
            if day == today:
                pill(painter, QRectF(x + 5, y, 24, 24), 12, MAUVE)
                color = MANTLE
            _label(painter, str(day.day), x, y, 34, 24, 12, color, DEMI if day == today else QFont.Weight.Normal, CENTER)

    def _media_mini(self, painter, state, art, hover):
        _card(painter, MEDIA, 34, SURFACE if hover == 'Media' else BASE)
        ring = QRectF(548, 97, 126, 126)
        pen = QPen(QColor(SURFACE2), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(ring, 225 * 16, -270 * 16)
        if state.duration and state.title:
            pen.setColor(QColor(MAUVE))
            painter.setPen(pen)
            painter.drawArc(ring, 225 * 16, -round(270 * 16 * state.elapsed() / state.duration))
        player.artwork(painter, art, QRectF(558, 107, 106, 106), 53)
        _label(painter, state.title or 'Chưa có nhạc', 531, 235, 160, 25, 14, PINK, DEMI, CENTER)
        status = 'Đang phát' if state.playing else ('Tạm dừng' if state.title else 'Trình phát Windows')
        _label(painter, state.artist or status, 531, 262, 160, 21, 11, MUTED,
               align=CENTER)
        for action, x in MINI_TRANSPORT.items():
            supported = bool(state.title and getattr(state, action))
            glyph = ('pause' if state.playing else 'play') if action == 'toggle' else action
            if supported and hover == action:
                pill(painter, QRectF(x - 15, MINI_Y - 14, 30, 28), 9, SURFACE2)
            icon(painter, glyph, x, MINI_Y, 17 if action == 'toggle' else 14, PINK if supported else OVERLAY)
        frame = self.cat.currentImage()
        if not frame.isNull():
            rect = QRectF(QPointF(), QSizeF(frame.size()).scaled(CAT.size(), Qt.AspectRatioMode.KeepAspectRatio))
            rect.moveCenter(CAT.center())
            painter.drawImage(rect, frame)
        self.live.draw_summary(painter, hover == 'Live Activity')
