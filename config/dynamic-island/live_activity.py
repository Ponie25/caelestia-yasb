"""The open activity drawer and its timer, stopwatch and notification state."""

from datetime import datetime
import math
import time

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextDocument, QTextOption

from audio_mixer import _slider
from icons import icon
from palette import BASE, LAVENDER, MAUVE, MUTED, OVERLAY, PINK, SURFACE, SURFACE2, TEXT
from player import pill, text


COUNTDOWN = QRectF(22, 77, 270, 110)
STOPWATCH = QRectF(22, 197, 270, 104)
STATUS = QRectF(22, 311, 270, 128)
NOTICES = QRectF(302, 77, 404, 362)
SUMMARY = QRectF(527, 404, 168, 24)
NOTICE_ROWS = QRectF(313, 126, 382, 296)
DETAIL_BODY = QRectF(327, 167, 354, 250)
OUTPUT_VOLUME = QRectF(352, 143, 260, 26)
ROW_HEIGHT = 58
VISIBLE = 5
DEMI = QFont.Weight.DemiBold
RIGHT = Qt.AlignmentFlag.AlignRight
CENTER = Qt.AlignmentFlag.AlignHCenter


def clock_text(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f'{minutes:02}:{seconds:02}'


def open_codex(thread):
    import os
    from urllib.parse import quote
    try:
        os.startfile('codex://threads/' + quote(thread, safe=''))
    except OSError:
        pass


def open_windows_notifications():
    import ctypes
    from ctypes import wintypes
    key = ctypes.windll.user32.keybd_event
    key.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    key.restype = None
    for vk, flags in ((0x5B, 1), (0x4E, 0), (0x4E, 2), (0x5B, 3)):
        key(vk, 0, flags, 0)


class LiveActivity(QObject):
    changed = Signal()
    timer_finished = Signal()
    dismiss_requested = Signal(int)
    clear_requested = Signal()

    def __init__(self):
        super().__init__()
        self.minutes = 5
        self.deadline = None
        self.paused = None
        self.finished = False
        self.stopwatch_start = None
        self.stopwatch_total = 0.0
        self.lap = None
        self.lap_at = 0.0
        self.turns = ()
        self.ended = ()
        self.output = ''
        self.output_open = False
        self.outputs = ()
        self.output_id = None
        self.output_offset = 0
        self.volume_level = None
        self.volume_muted = False
        self.output_error = False
        self.notices = None
        self.notification_ready = False
        self.notice_offset = 0
        self.wheel_remainder = 0
        self.selected = None
        self.confirm_clear = False
        self.detail_offset = 0
        self.detail_doc = None
        self.clock = QTimer(self, interval=200)
        self.clock.timeout.connect(self._tick)
        self._last_display = None

    @property
    def countdown(self):
        if self.deadline is not None:
            return max(0, math.ceil(self.deadline - time.time()))
        if self.paused is not None:
            return math.ceil(self.paused)
        return 0 if self.finished else self.minutes * 60

    @property
    def stopwatch(self):
        extra = time.monotonic() - self.stopwatch_start if self.stopwatch_start is not None else 0.0
        return self.stopwatch_total + extra

    @property
    def has_countdown(self):
        return self.deadline is not None or self.paused is not None

    def _tick(self):
        if self.deadline is not None and self.countdown == 0:
            self.deadline = None
            self.finished = True
            self.timer_finished.emit()
        display = self.countdown, int(self.stopwatch)
        if display != self._last_display:
            self._last_display = display
            self.changed.emit()
        if self.deadline is None and self.stopwatch_start is None:
            self.clock.stop()

    def set_notifications(self, rows):
        old_rows = self.notices or ()
        first = old_rows[self.notice_offset]['id'] if self.notice_offset < len(old_rows) else None
        self.notices = rows
        self.notification_ready = True
        if rows:
            if self.notice_offset and first is not None:
                self.notice_offset = next((i for i, row in enumerate(rows) if row['id'] == first), self.notice_offset)
            self.notice_offset = min(self.notice_offset, max(0, len(rows) - VISIBLE))
        else:
            self.notice_offset = 0
            self.confirm_clear = False
        selected = next((row for row in rows or () if row['id'] == self.selected), None)
        if selected is None:
            self.selected = None
            self.detail_doc = None
        else:
            self._prepare_detail(selected, preserve=True)
        self.changed.emit()

    def set_outputs(self, devices, device_id, level, muted):
        self.outputs, self.output_id = devices, device_id
        self.volume_level, self.volume_muted = level, muted
        self.output_offset = min(self.output_offset, max(0, len(devices) - VISIBLE))

    def _prepare_detail(self, row, preserve=False):
        previous_offset = self.detail_offset if preserve else 0
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setTextWidth(DETAIL_BODY.width())
        option = doc.defaultTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(option)
        cursor = QTextCursor(doc)
        title, body = row['title'], row['body']
        for value, size, color, weight in ((title, 16, TEXT, DEMI), (body, 12, MUTED, QFont.Weight.Normal)):
            if not value:
                continue
            if not cursor.atStart():
                cursor.insertBlock()
                cursor.insertBlock()
            font = QFont('Segoe UI Variable Text')
            font.setPixelSize(size)
            font.setWeight(weight)
            style = QTextCharFormat()
            style.setFont(font)
            style.setForeground(QColor(color))
            cursor.insertText(value, style)
        self.detail_doc = doc
        self.detail_offset = min(previous_offset, self._detail_end())

    def _detail_end(self):
        return max(0.0, self.detail_doc.size().height() - DETAIL_BODY.height()) if self.detail_doc else 0.0

    def scroll(self, point, delta, pixels=False):
        if not NOTICE_ROWS.contains(point):
            return False
        if self.selected is not None and not self.output_open:
            change = delta if pixels else delta / 120 * 52
            self.detail_offset = min(self._detail_end(), max(0.0, self.detail_offset - change))
        else:
            unit = 40 if pixels else 120
            self.wheel_remainder += delta
            steps = int(self.wheel_remainder / unit)
            self.wheel_remainder -= steps * unit
            if self.output_open:
                end = max(0, len(self.outputs) - VISIBLE)
                self.output_offset = min(end, max(0, self.output_offset - steps))
            else:
                end = max(0, len(self.notices or ()) - VISIBLE)
                self.notice_offset = min(end, max(0, self.notice_offset - steps))
        self.changed.emit()
        return True

    def _controls(self):
        yield ('live', 'timer'), QRectF(204, 111, 41, 31), ('pause' if self.deadline is not None else 'play')
        yield ('live', 'timer_reset'), QRectF(251, 111, 27, 31), 'refresh'
        if not self.has_countdown:
            for index, value in enumerate((5, 15, 25)):
                yield ('live', 'preset', value), QRectF(36 + 41 * index, 151, 38, 24), f'{value}p'
            yield ('live', 'adjust', -1), QRectF(206, 151, 32, 24), 'minus'
            yield ('live', 'adjust', 1), QRectF(245, 151, 32, 24), 'plus'
        yield ('live', 'watch'), QRectF(204, 230, 41, 31), ('pause' if self.stopwatch_start is not None else 'play')
        if self.stopwatch_start is not None:
            yield ('live', 'lap'), QRectF(170, 230, 27, 31), 'flag'
        yield ('live', 'watch_reset'), QRectF(251, 230, 27, 31), 'refresh'
        if self.turns:
            yield ('live', 'codex'), QRectF(33, 322, 248, 45), ''
        yield ('live', 'output'), QRectF(33, 378, 248, 44), ''
        if self.output_open:
            yield ('live', 'output'), QRectF(313, 88, 30, 28), 'left'
            yield 'Media', QRectF(626, 88, 66, 28), 'Mixer'
            if self.volume_level is not None:
                yield ('live', 'output_mute'), QRectF(320, 143, 28, 26), 'mute' if self.volume_muted else 'volume'
                yield ('live', 'output_volume'), OUTPUT_VOLUME, ''
            for device_id, _, rect in self._output_rows():
                yield ('live', 'output_device', device_id), rect, ''
            return
        yield ('live', 'center'), QRectF(657, 88, 35, 28), 'external'
        if self.notices:
            if self.confirm_clear:
                yield ('live', 'cancel_clear'), QRectF(507, 88, 47, 28), 'Hủy'
                yield ('live', 'clear'), QRectF(558, 88, 91, 28), 'Xác nhận'
            else:
                yield ('live', 'ask_clear'), QRectF(560, 88, 89, 28), 'Xóa hết'
        if self.selected is not None:
            yield ('live', 'back'), QRectF(316, 128, 33, 28), 'left'
            yield ('live', 'dismiss', self.selected), QRectF(658, 128, 33, 28), 'x'
        else:
            for row, rect in self._rows():
                yield ('live', 'dismiss', row['id']), self._dismiss_rect(rect), 'x'
                yield ('live', 'notice', row['id']), rect, ''

    def action_at(self, point):
        return next((action for action, rect, _ in self._controls() if rect.contains(point)), None)

    @staticmethod
    def is_action(action):
        return isinstance(action, tuple) and bool(action) and action[0] == 'live'

    def tooltip(self, action):
        if action[1] == 'preset':
            return f'Chọn {action[2]} phút'
        if action[1] == 'output_device':
            return next((name for device_id, name in self.outputs if device_id == action[2]), '')
        return {
            'timer': 'Tạm dừng hẹn giờ' if self.deadline is not None else 'Bắt đầu hoặc tiếp tục hẹn giờ',
            'timer_reset': 'Đặt lại hẹn giờ',
            'watch': 'Tạm dừng bấm giờ' if self.stopwatch_start is not None else 'Bắt đầu hoặc tiếp tục bấm giờ',
            'watch_reset': 'Đặt lại bấm giờ', 'lap': 'Ghi một vòng',
            'center': 'Mở Trung tâm thông báo Windows', 'notice': 'Xem thông báo',
            'dismiss': 'Bỏ thông báo này', 'back': 'Về danh sách', 'codex': 'Mở lượt Codex',
            'adjust': 'Chỉnh thời lượng từng phút',
            'output': 'Chọn đầu ra và chỉnh âm lượng',
            'output_mute': 'Bật tiếng' if self.volume_muted else 'Tắt tiếng',
            'output_volume': 'Âm lượng đầu ra',
            'ask_clear': 'Xóa tất cả thông báo Windows', 'clear': 'Xác nhận xóa tất cả thông báo Windows',
        }.get(action[1], '')

    def activate(self, action):
        name = action[1]
        if name == 'timer':
            if self.deadline is not None:
                self.paused = max(0.05, self.deadline - time.time())
                self.deadline = None
            else:
                self.deadline = time.time() + (self.paused if self.paused is not None else self.minutes * 60)
                self.paused = None
                self.finished = False
        elif name == 'timer_reset':
            self.deadline = self.paused = None
            self.finished = False
        elif name == 'preset':
            self.minutes, self.finished = action[2], False
        elif name == 'adjust':
            self.minutes = min(99, max(1, self.minutes + action[2]))
            self.finished = False
        elif name == 'watch':
            if self.stopwatch_start is None:
                self.stopwatch_start = time.monotonic()
            else:
                self.stopwatch_total = self.stopwatch
                self.stopwatch_start = None
        elif name == 'watch_reset':
            self.stopwatch_start = None
            self.stopwatch_total = self.lap_at = 0.0
            self.lap = None
        elif name == 'lap':
            elapsed = self.stopwatch
            self.lap = elapsed - self.lap_at
            self.lap_at = elapsed
        elif name == 'codex' and self.turns:
            open_codex(self.turns[0].thread_id)
        elif name == 'center':
            open_windows_notifications()
        elif name == 'back':
            self.selected = None
            self.detail_doc = None
        elif name == 'notice':
            self.selected = action[2]
            self._prepare_detail(next(row for row in self.notices if row['id'] == self.selected))
        elif name == 'dismiss':
            self.dismiss_requested.emit(action[2])
        elif name == 'ask_clear':
            self.confirm_clear = True
        elif name == 'cancel_clear':
            self.confirm_clear = False
        elif name == 'clear':
            self.confirm_clear = False
            self.clear_requested.emit()

        if self.deadline is not None or self.stopwatch_start is not None:
            if not self.clock.isActive():
                self.clock.start()
        else:
            self.clock.stop()
        self.changed.emit()

    def draw_summary(self, painter, hovered):
        pill(painter, SUMMARY, 8, SURFACE2 if hovered else SURFACE)
        items = []
        if self.turns:
            items.append(('terminal', clock_text(time.time() - self.turns[0].started), MAUVE))
        if self.has_countdown or self.finished:
            items.append(('hourglass', '✓' if self.finished else clock_text(self.countdown), PINK))
        if self.stopwatch_start is not None or self.stopwatch_total > 0:
            items.append(('stopwatch', clock_text(self.stopwatch), LAVENDER))
        if self.notices:
            items.append(('bell', str(len(self.notices)), PINK))
        if not items:
            icon(painter, 'activity', 543, 416, 12, MAUVE)
            text(painter, 'Live Activity', QRectF(554, 404, 116, 24), 10, MUTED, DEMI)
            icon(painter, 'right', 681, 416, 11, MUTED)
            return
        width = SUMMARY.width() / len(items)
        for i, (glyph, value, accent) in enumerate(items):
            x = SUMMARY.left() + i * width
            icon(painter, glyph, x + 9, 416, 10, accent)
            text(painter, value, QRectF(x + 16, 404, width - 18, 24), 9, TEXT, DEMI)

    def draw(self, painter, hover):
        for card in (COUNTDOWN, STOPWATCH, STATUS, NOTICES):
            pill(painter, card, 20, BASE)
        for title, glyph, top, color in (('Hẹn giờ · Xong' if self.finished else 'Hẹn giờ', 'hourglass', 89, PINK),
                                         ('Bấm giờ', 'stopwatch', 209, LAVENDER)):
            icon(painter, glyph, 43, top + 10, 13, color)
            text(painter, title, QRectF(55, top, 135, 20), 12, TEXT, DEMI)
        text(painter, clock_text(self.countdown), QRectF(36, 108, 154, 38), 30, PINK, DEMI)
        if self.has_countdown:
            label = 'Tạm dừng' if self.paused is not None else 'Đang đếm ngược'
            text(painter, label, QRectF(37, 151, 155, 24), 11, MUTED)
        text(painter, clock_text(self.stopwatch), QRectF(36, 226, 128, 37), 30, LAVENDER, DEMI)
        lap = f'Vòng gần nhất · {clock_text(self.lap)}' if self.lap is not None else 'Tính thời gian đã trôi qua'
        text(painter, lap, QRectF(37, 268, 230, 21), 10, MUTED)

        if hover == ('live', 'codex'):
            pill(painter, QRectF(33, 322, 248, 45), 11, SURFACE)
        icon(painter, 'terminal', 47, 343, 16, MAUVE)
        text(painter, 'Codex', QRectF(63, 324, 123, 21), 13, TEXT, DEMI)
        running = len(self.turns)
        status = f'Đang làm · {running} lượt' if running else 'Đang rảnh'
        if not running and self.ended:
            status = {'completed': 'Vừa hoàn tất', 'interrupted': 'Vừa dừng', 'failed': 'Lượt gần nhất bị lỗi'}.get(
                self.ended[-1].status, status)
        text(painter, status, QRectF(63, 346, 157, 17), 10, MUTED)
        if running:
            text(painter, clock_text(time.time() - self.turns[0].started), QRectF(213, 325, 51, 32), 13, MAUVE, DEMI, RIGHT)
        if self.output_open or hover == ('live', 'output'):
            pill(painter, QRectF(33, 378, 248, 44), 11, SURFACE)
        icon(painter, 'headphones', 47, 399, 16, LAVENDER)
        text(painter, 'Đầu ra âm thanh', QRectF(63, 379, 185, 21), 12, TEXT, DEMI)
        text(painter, self.output or 'Chưa có thiết bị', QRectF(63, 401, 193, 17), 10, MUTED)
        icon(painter, 'left' if self.output_open else 'right', 267, 399, 12, MUTED)

        if self.output_open:
            self._draw_output(painter, hover)
        else:
            icon(painter, 'bell', 326, 103, 15, PINK)
            text(painter, 'Thông báo', QRectF(340, 87, 107, 31), 16, TEXT, DEMI)
            if self.notices:
                text(painter, str(len(self.notices)), QRectF(449, 88, 47, 30), 12, PINK, DEMI)
            self._draw_notifications(painter, hover)
        for action, rect, glyph in self._controls():
            if not glyph:
                continue
            active = action[:2] == ('live', 'preset') and action[2] == self.minutes
            main = action in (('live', 'timer'), ('live', 'watch'))
            confirm = action == ('live', 'clear')
            labeled = action in ('Media', ('live', 'ask_clear'), ('live', 'cancel_clear'), ('live', 'clear'))
            if main or active or action == hover or labeled:
                pill(painter, rect, 8, SURFACE2 if active or action == hover else SURFACE)
            if labeled or (glyph.endswith('p') and glyph[:-1].isdigit()):
                text(painter, glyph, rect, 10, PINK if active or confirm else TEXT if labeled else MUTED, DEMI, CENTER)
            else:
                icon(painter, glyph, rect.center().x(), rect.center().y(), 13 if not main else 15,
                     PINK if action == ('live', 'timer') else LAVENDER if main else MUTED)

    def _output_rows(self):
        for index, (device_id, label) in enumerate(self.outputs[self.output_offset:self.output_offset + VISIBLE]):
            yield device_id, label, QRectF(315, 189 + 44 * index, 377, 39)

    def _draw_output(self, painter, hover):
        text(painter, 'Thiết bị đầu ra', QRectF(348, 87, 257, 31), 16, TEXT, DEMI)
        pill(painter, QRectF(315, 132, 377, 47), 11, SURFACE)
        _slider(painter, OUTPUT_VOLUME, self.volume_level, self.volume_muted, hover == ('live', 'output_volume'))
        level = '—' if self.volume_level is None else f'{self.volume_level}%'
        text(painter, level, QRectF(621, 143, 50, 26), 11, MUTED if self.volume_muted else TEXT, DEMI, RIGHT)
        for device_id, name, rect in self._output_rows():
            selected = device_id == self.output_id
            if selected or hover == ('live', 'output_device', device_id):
                pill(painter, rect, 9, SURFACE)
            icon(painter, 'headphones', 332, rect.center().y(), 14, LAVENDER if selected else MUTED)
            text(painter, ' '.join(name.split()), rect.adjusted(30, 0, -36, 0), 12, TEXT, DEMI if selected else QFont.Weight.Normal)
            if selected:
                icon(painter, 'check', 676, rect.center().y(), 14, MAUVE)
        if not self.outputs:
            text(painter, 'Chưa có thiết bị đầu ra khả dụng', QRectF(327, 241, 350, 24), 12, MUTED, DEMI, CENTER)
        if self.output_error:
            text(painter, 'Windows chưa chuyển được thiết bị', QRectF(327, 410, 350, 21), 11, PINK, DEMI)
        self._scrollbar(painter, len(self.outputs), self.output_offset, 189, 215)

    def _rows(self):
        for index, row in enumerate((self.notices or ())[self.notice_offset:self.notice_offset + VISIBLE]):
            yield row, QRectF(314, 126 + index * ROW_HEIGHT, 378, ROW_HEIGHT - 5)

    @staticmethod
    def _dismiss_rect(rect):
        return QRectF(rect.right() - 29, rect.top() + 9, 24, 33)

    def _draw_notifications(self, painter, hover):
        if not self.notices:
            if self.notices == ():
                message = 'Chưa có thông báo'
            elif self.notification_ready:
                message = 'Bật quyền đọc thông báo trong Windows'
            else:
                message = 'Đang chờ thông báo từ Windows'
            icon(painter, 'bell', 504, 241, 30, OVERLAY)
            text(painter, message, QRectF(332, 266, 345, 24), 12, MUTED, DEMI, CENTER)
            return
        if self.selected is not None:
            row = next(item for item in self.notices if item['id'] == self.selected)
            text(painter, ' '.join(row['app'].split()), QRectF(354, 127, 290, 29), 12, PINK, DEMI)
            if self.detail_doc is not None:
                painter.save()
                painter.setClipRect(DETAIL_BODY, Qt.ClipOperation.IntersectClip)
                painter.translate(DETAIL_BODY.left(), DETAIL_BODY.top() - self.detail_offset)
                self.detail_doc.drawContents(painter)
                painter.restore()
                end = self._detail_end()
                if end:
                    height = DETAIL_BODY.height() ** 2 / self.detail_doc.size().height()
                    y = DETAIL_BODY.top() + (DETAIL_BODY.height() - height) * self.detail_offset / end
                    pill(painter, QRectF(691, y, 2, height), 1, SURFACE2)
            return
        for row, rect in self._rows():
            painter.save()
            painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
            if hover in (('live', 'notice', row['id']), ('live', 'dismiss', row['id'])):
                pill(painter, rect, 10, SURFACE)
            y = rect.top()
            icon(painter, 'bell', 329, y + 16, 12, PINK)
            app, title, body = (' '.join(row[key].split()) for key in ('app', 'title', 'body'))
            text(painter, app, QRectF(343, y + 2, 215, 19), 10, PINK, DEMI)
            if row['at']:
                stamp = datetime.fromtimestamp(row['at']).strftime('%H:%M')
                text(painter, stamp, QRectF(589, y + 2, 70, 19), 10, MUTED, DEMI, RIGHT)
            text(painter, title or body, QRectF(343, y + 19, 305, 17), 12, TEXT, DEMI)
            if title and body:
                text(painter, body, QRectF(343, y + 36, 305, 15), 10, MUTED)
            painter.restore()
        self._scrollbar(painter, len(self.notices), self.notice_offset, NOTICE_ROWS.top(), NOTICE_ROWS.height())

    @staticmethod
    def _scrollbar(painter, count, offset, top, length):
        if count > VISIBLE:
            height = length * VISIBLE / count
            y = top + (length - height) * offset / (count - VISIBLE)
            pill(painter, QRectF(697, y, 2, height), 1, SURFACE2)
