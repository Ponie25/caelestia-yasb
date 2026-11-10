from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath

from icons import icon
from media import RepeatMode
from palette import MUTED, SURFACE, TEXT


INK = TEXT
REPEAT_NEXT = {RepeatMode.NONE: RepeatMode.LIST, RepeatMode.LIST: RepeatMode.TRACK, RepeatMode.TRACK: RepeatMode.NONE}

@lru_cache(maxsize=24)
def _font(size, weight):
    font = QFont('Segoe UI Variable Text')
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


def text(painter, value, rect, size, color, weight=QFont.Weight.Normal, align=Qt.AlignmentFlag.AlignLeft):
    painter.setFont(_font(size, weight))
    painter.setPen(QColor(color))
    value = painter.fontMetrics().elidedText(value, Qt.TextElideMode.ElideRight, int(rect.width()))
    painter.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, value)


def pill(painter, rect, radius, color):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(rect, radius, radius)


def artwork(painter, art, rect, radius):
    if art.isNull():
        pill(painter, rect, radius, SURFACE)
        icon(painter, 'music', rect.center().x(), rect.center().y(), rect.width() * 0.39, MUTED)
    else:
        side = min(art.width(), art.height())
        source = QRectF((art.width() - side) / 2, (art.height() - side) / 2, side, side)
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        painter.drawImage(rect, art, source)
        painter.restore()


def enabled(action, state, volume):
    if action in ('volume', 'mute'):
        return volume.level is not None
    if action in ('shuffle', 'repeat'):
        return getattr(state, action) is not None
    if action == 'seek':
        return state.seek and state.duration > 0
    return action == 'close' or bool(action and getattr(state, action, False))


def tooltip(action, state, volume):
    labels = {'close': 'Thu gọn', 'volume': 'Âm lượng hệ thống', 'mute': 'Bật tiếng' if volume.muted else 'Tắt tiếng',
              'seek': 'Kéo để tua', 'previous': 'Bài trước', 'next': 'Bài tiếp theo',
              'toggle': 'Tạm dừng' if state.playing else 'Phát tiếp',
              'shuffle': 'Tắt phát ngẫu nhiên' if state.shuffle else 'Phát ngẫu nhiên',
              'repeat': {RepeatMode.NONE: 'Bật lặp danh sách', RepeatMode.LIST: 'Lặp một bài',
                         RepeatMode.TRACK: 'Tắt lặp'}.get(state.repeat, 'Lặp lại')}
    if action is None:
        return ''
    if not enabled(action, state, volume):
        return 'Ứng dụng phát không hỗ trợ thao tác này' if action not in ('volume', 'mute') else 'Chưa có thiết bị âm thanh'
    return labels[action]
