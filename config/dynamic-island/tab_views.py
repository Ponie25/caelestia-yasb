from datetime import datetime
from functools import lru_cache
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen

from audio_mixer import MUTE, VOLUME
from icons import icon
from media import RepeatMode
from palette import BASE, LAVENDER, MANTLE, MAUVE, MUTED, OVERLAY, PINK, SURFACE, SURFACE2, TEXT
from player import artwork, pill, text
from weather import CITY, condition


DEMI = QFont.Weight.DemiBold
CENTER = Qt.AlignmentFlag.AlignHCenter
RIGHT = Qt.AlignmentFlag.AlignRight
SEEK = QRectF(243, 224, 219, 22)
MEDIA_BUTTONS = {
    'shuffle': QRectF(199, 267, 36, 44), 'previous': QRectF(240, 267, 44, 44),
    'toggle': QRectF(289, 267, 97, 44), 'next': QRectF(391, 267, 44, 44),
    'repeat': QRectF(440, 267, 36, 44),
}
DRIVE_SWITCH = QRectF(374, 237, 37, 36)
WEATHER_REFRESH = QRectF(674, 79, 28, 29)


def label(painter, value, x, y, width, height=22, size=13, color=TEXT, weight=QFont.Weight.Normal, align=None):
    text(painter, value, QRectF(x, y, width, height), size, color, weight, align or Qt.AlignmentFlag.AlignLeft)


def stroke(painter, color, width, round_caps=False):
    pen = QPen(QColor(color), width)
    if round_caps:
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)


def media_target(point, state):
    if VOLUME.contains(point):
        return 'volume'
    if MUTE.contains(point):
        return 'mute'
    if state.title:
        if state.duration and SEEK.contains(point):
            return 'seek'
        for action, rect in MEDIA_BUTTONS.items():
            if rect.contains(point):
                return action
    return None


def _time(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


def _bar(painter, rect, fraction, color, knob=False, wave=False, animate=False):
    fraction = max(0.0, min(1.0, fraction))
    y = rect.center().y()
    pill(painter, QRectF(rect.x(), y - 2, rect.width(), 4), 2, SURFACE2)
    width = rect.width() * fraction
    if wave and width > 3:
        path = QPainterPath(QPointF(rect.x(), y))
        phase = time.monotonic() * 2.4 if animate else 0.0
        for i in range(1, 42):
            step = i / 41
            dy = 2.3 * math.sin(width * step / 6 + phase) * min(1, step * 5, (1 - step) * 5)
            path.lineTo(rect.x() + width * step, y + dy)
        pen = QPen(QColor(color), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.strokePath(path, pen)
    elif width:
        pill(painter, QRectF(rect.x(), y - 2, width, 4), 2, color)
    if knob:
        pill(painter, QRectF(rect.x() + width - 1.5, y - 7, 3, 14), 1.5, color)


@lru_cache(maxsize=1)
def _album_shape():
    path = QPainterPath()
    for i in range(161):
        angle = math.tau * i / 160
        radius = 63 + 3.2 * math.cos(8 * angle)
        point = QPointF(111 + radius * math.cos(angle), 251 + radius * math.sin(angle))
        path.moveTo(point) if i == 0 else path.lineTo(point)
    path.closeSubpath()
    return path


RING_SPOKES = tuple((math.cos(math.tau * i / 48), math.sin(math.tau * i / 48), i * 0.79) for i in range(48))


def _media_cover(painter, state, art):
    shape = _album_shape()
    painter.save()
    painter.setClipPath(shape, Qt.ClipOperation.IntersectClip)
    if art.isNull():
        painter.fillPath(shape, QColor(SURFACE))
        icon(painter, 'music', 111, 251, 45, LAVENDER)
    else:
        artwork(painter, art, QRectF(43, 183, 136, 136), 0)
    painter.restore()
    now = time.monotonic()
    stroke(painter, MAUVE if state.playing else SURFACE2, 2.7, True)
    for dx, dy, phase in RING_SPOKES:
        radius = 74 + (2 + 5 * (0.5 + 0.5 * math.sin(now * 4.0 + phase)) if state.playing else 2)
        painter.drawLine(QPointF(111 + dx * 71, 251 + dy * 71), QPointF(111 + dx * radius, 251 + dy * radius))


def media_view(painter, state, art, hover, seek_preview):
    _media_cover(painter, state, art)
    if state.title:
        label(painter, state.title, 199, 135, 278, 33, 23, TEXT, DEMI)
        label(painter, state.artist or '—', 200, 173, 276, 24, 14, MUTED)
        label(painter, state.album, 200, 197, 276, 22, 13, LAVENDER)
        elapsed = min(state.duration, seek_preview) if seek_preview is not None else state.elapsed()
        if state.duration:
            _bar(painter, SEEK, elapsed / state.duration, MAUVE, state.seek, True, state.playing)
            label(painter, _time(elapsed), 199, 224, 38, 22, 11, MUTED, align=CENTER)
            label(painter, _time(state.duration), 466, 224, 38, 22, 11, MUTED, align=CENTER)
        for action, rect in MEDIA_BUTTONS.items():
            supported = getattr(state, action) is not None if action in ('repeat', 'shuffle') else getattr(state, action)
            active = (action == 'toggle' or action == 'shuffle' and state.shuffle or
                      action == 'repeat' and state.repeat not in (None, RepeatMode.NONE))
            bg = (PINK if hover == action else MAUVE) if active and supported else (SURFACE2 if hover == action and supported else SURFACE)
            glyph = action
            if action == 'toggle':
                glyph = 'pause' if state.playing else 'play'
            elif action == 'repeat' and state.repeat == RepeatMode.TRACK:
                glyph = 'repeat_one'
            pill(painter, rect, 15 if action == 'toggle' else rect.width() / 2, bg)
            icon(painter, glyph, rect.center().x(), rect.center().y(), 22 if action == 'toggle' else 16,
                 MANTLE if active and supported else TEXT if supported else OVERLAY)
    else:
        pill(painter, QRectF(298, 166, 74, 63), 23, SURFACE)
        icon(painter, 'music', 335, 197, 30, LAVENDER)
        label(painter, 'Chưa có nhạc đang phát', 196, 242, 280, 32, 17, TEXT, DEMI, CENTER)
        label(painter, 'Mở nhạc hoặc video để bắt đầu', 196, 275, 280, 24, 12, MUTED, align=CENTER)

    if state.source:
        pill(painter, QRectF(257, 344, 160, 33), 15, SURFACE)
        label(painter, state.source, 266, 347, 142, 27, 11, LAVENDER, DEMI, CENTER)


def _gauge(painter, x, y, diameter, value, color, width):
    rect = QRectF(x, y, diameter, diameter)
    stroke(painter, SURFACE, width, True)
    painter.drawArc(rect, 225 * 16, -270 * 16)
    if value is not None and value > 0:
        stroke(painter, color, width, True)
        painter.drawArc(rect, 225 * 16, -round(270 * 16 * value / 100))


def _speed(value):
    if value >= 2**20:
        return f'{value / 2**20:.1f} MiB/s'
    return f'{value / 2**10:.1f} KiB/s'


def performance_view(painter, metrics, hover):
    d = metrics.data
    cpu_details = f'{metrics.cores} luồng'
    gpu_details = f'{d.gpu_temp}°C' if d.gpu_temp is not None else '—'
    for x, glyph, name, model, value, detail, accent in (
        (22, 'cpu', 'CPU', metrics.cpu_name, d.cpu, cpu_details, MAUVE),
        (369, 'desktop', 'GPU', metrics.gpu.name if metrics.gpu else 'GPU', d.gpu, gpu_details, PINK),
    ):
        pill(painter, QRectF(x, 77, 337, 139), 22, BASE)
        _gauge(painter, x + 17, 97, 34, value, accent, 3)
        icon(painter, glyph, x + 34, 114, 15, accent)
        label(painter, name, x + 63, 94, 172, 27, 17, accent, DEMI)
        label(painter, model, x + 63, 122, 197, 21, 11, MUTED)
        label(painter, detail, x + 20, 165, 150, 24, 13, TEXT)
        if name == 'GPU' and d.gpu_temp is not None:
            _bar(painter, QRectF(x + 20, 190, 142, 14), d.gpu_temp / 100, PINK)
        label(painter, 'Sử dụng', x + 235, 152, 84, 22, 11, MUTED, align=RIGHT)
        label(painter, f'{value:.0f}%' if value is not None else '—', x + 224, 173, 95, 30, 24, accent, DEMI, RIGHT)

    for x, name, glyph, value, detail, accent in (
        (22, 'RAM', 'ram', d.ram, d.ram_text, LAVENDER),
        (226, f'Ổ đĩa {metrics.drive[:2]}', 'disk', d.disk, d.disk_text, PINK),
    ):
        pill(painter, QRectF(x, 226, 194, 213), 22, BASE)
        icon(painter, glyph, x + 24, 254, 16, accent)
        label(painter, name, x + 43, 240, 113, 28, 15, TEXT, DEMI)
        _gauge(painter, x + 51, 283, 92, value, accent, 8)
        label(painter, f'{value:.0f}%' if value is not None else '—', x + 48, 307, 98, 38, 27, accent, DEMI, CENTER)
        label(painter, detail, x + 8, 396, 178, 24, 12, MUTED, align=CENTER)
    if len(metrics.drives) > 1:
        if hover == 'drive':
            pill(painter, DRIVE_SWITCH, 8, SURFACE)
        icon(painter, 'right', DRIVE_SWITCH.center().x(), DRIVE_SWITCH.center().y(), 14, MUTED)

    pill(painter, QRectF(430, 226, 276, 213), 22, BASE)
    icon(painter, 'network', 454, 254, 16, LAVENDER)
    label(painter, 'Mạng', 470, 240, 180, 28, 15, TEXT, DEMI)
    network = metrics.network_history
    if len(network) >= 2:
        largest = max(1, *(max(pair) for pair in network))
        for index, color in ((0, MAUVE), (1, LAVENDER)):
            path = QPainterPath()
            for i, pair in enumerate(network):
                x = 687 - (len(network) - 1 - i) * 238 / (network.maxlen - 1)
                y = 342 - 59 * pair[index] / largest
                path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
            painter.strokePath(path, QPen(QColor(color), 1.6))
    for i, (name, value, color) in enumerate((('Tải xuống', _speed(d.rx), MAUVE), ('Tải lên', _speed(d.tx), LAVENDER),
                                             ('Tổng', f'{d.total / 2**20:.0f} MiB', MUTED))):
        y = 354 + i * 23
        label(painter, name, 451, y, 106, 22, 11, MUTED)
        label(painter, value, 559, y, 126, 22, 12, color, DEMI, RIGHT)


def weather_view(painter, weather, hover, weekdays):
    f = weather.forecast
    now = datetime.now()
    label(painter, CITY, 23, 76, 240, 35, 27, TEXT, DEMI)
    label(painter, f'{weekdays[now.weekday()]}, {now.day} tháng {now.month}', 23, 110, 240, 20, 11, MUTED)
    for x, glyph, name, value in ((456, 'sunrise', 'Bình minh', f.sunrise if f else '—'),
                                  (563, 'moon', 'Hoàng hôn', f.sunset if f else '—')):
        icon(painter, glyph, x, 102, 21, PINK)
        label(painter, name, x + 18, 83, 78, 20, 11, MUTED)
        label(painter, value, x + 18, 103, 78, 20, 12, TEXT, DEMI)
    if hover == 'refresh':
        pill(painter, WEATHER_REFRESH, 8, SURFACE)
    icon(painter, 'refresh', WEATHER_REFRESH.center().x(), WEATHER_REFRESH.center().y(), 15, MUTED)
    pill(painter, QRectF(22, 137, 684, 113), 22, BASE)
    glyph, description = condition(f.code) if f else ('cloud', 'Đang tải dự báo…' if weather.loading else 'Chưa có dữ liệu')
    icon(painter, glyph, 280, 194, 63, LAVENDER)
    label(painter, f'{f.temperature:.0f}°C' if f else '—°C', 332, 148, 197, 60, 49, MAUVE, DEMI)
    label(painter, description, 335, 210, 207, 22, 13, TEXT)
    for i, (glyph, name, value, accent) in enumerate((
        ('drop', 'Độ ẩm', f'{f.humidity}%' if f else '—', LAVENDER),
        ('temperature', 'Cảm giác', f'{f.feels_like:.0f}°C' if f else '—', MAUVE),
        ('wind', 'Gió', f'{f.wind:.1f} km/h' if f else '—', PINK),
    )):
        x = 22 + 231 * i
        pill(painter, QRectF(x, 260, 222, 50), 13, BASE)
        icon(painter, glyph, x + 75, 285, 17, accent)
        label(painter, name, x + 92, 263, 108, 18, 10, MUTED)
        label(painter, value, x + 92, 281, 108, 21, 13, TEXT, DEMI)
    label(painter, 'Dự báo 7 ngày', 23, 316, 220, 22, 13, TEXT, DEMI)
    label(painter, 'Open-Meteo' if not weather.failed else 'Open-Meteo · Làm mới để thử lại',
          435, 316, 271, 22, 10, MUTED, align=RIGHT)
    if f:
        for i, day in enumerate(f.days[:7]):
            x = 22 + 98 * i
            pill(painter, QRectF(x, 344, 96, 95), 15, SURFACE if i == 0 else BASE)
            label(painter, 'Hôm nay' if i == 0 else weekdays[day.date.weekday()], x, 349, 96, 19, 12, LAVENDER, DEMI, CENTER)
            label(painter, day.date.strftime('%d/%m'), x, 369, 96, 16, 10, MUTED, align=CENTER)
            icon(painter, condition(day.code)[0], x + 48, 398, 20, LAVENDER)
            label(painter, f'{day.high:.0f}° / {day.low:.0f}°', x, 411, 96, 21, 12, PINK, DEMI, CENTER)
