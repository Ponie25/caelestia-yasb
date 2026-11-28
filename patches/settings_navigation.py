"""Find settings by task, including page links and actions."""
import re
import unicodedata

from PyQt6.QtCore import QObject, QEvent, Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QLabel, QListWidgetItem, QTabWidget
from core.utils.ui_motion import duration


class StatusLabel(QLabel):
    changed = pyqtSignal(str)

    def setText(self, text):
        super().setText(text)
        self.changed.emit(str(text))


def folded(text):
    return "".join(
        char for char in unicodedata.normalize("NFKD", str(text).casefold().replace("đ", "d"))
        if not unicodedata.combining(char)
    )


def words(text):
    return " ".join(re.findall(r"\w+", folded(text)))


ALIASES = {
    "font_family": "font phông kiểu chữ",
    "font_size": "font size chữ to nhỏ",
    "foreground": "màu chữ màu icon văn bản",
    "text_color": "màu chữ màu icon văn bản",
    "background_opacity": "opacity độ trong suốt độ mờ của nền thanh bar",
    "background_blur": "blur độ mờ ảnh nền thanh bar",
    "liquid_frost": "liquid glass blur kính độ mờ",
    "border": "viền thanh bar",
    "hotkey": "alt space phím tắt tìm ứng dụng",
    "city": "thời tiết thành phố hà nội weather",
    "material": "glass liquid nền kính",
    "popup_ms": "hiệu ứng chuyển động animation motion tốc độ",
    "speed": "hiệu ứng chuyển động animation motion tốc độ",
}


class SettingsSearch(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.entries = []
        self.field = dialog.settings_search
        self.results = dialog.search_results
        self.theme_cards = set(dialog.theme_buttons.values())
        for (group, key), (control, _) in dialog.controls.items():
            page = next((i for i in range(dialog.pages.count()) if dialog.pages.widget(i).isAncestorOf(control)), None)
            if page is not None:
                terms = ALIASES.get(key, "")
                if (group, key) == ("launcher", "enabled"):
                    terms += " launcher tìm ứng dụng"
                self.add(control.accessibleName() or key, page, control, terms)
        for page, buttons in (
            (0, dialog.theme_buttons),
            (0, {key: value[0] for key, value in dialog.text_color_presets.items()}),
        ):
            for key, button in buttons.items():
                self.add(button.accessibleName() or button.text(), page, button, key)
        for page in range(dialog.nav.count()):
            self.add(dialog.nav.item(page).text(), page, None, "")
        experience = getattr(dialog, "_settings_experience", None)
        if experience is not None:
            for item in experience.search_actions:
                self.add(*item)

        self.field.textChanged.connect(self.update)
        self.field.returnPressed.connect(self.activate)
        self.field.installEventFilter(self)
        self.results.itemActivated.connect(lambda _: self.activate())
        self.results.itemClicked.connect(lambda _: self.activate())
        self.shortcut = QShortcut(QKeySequence.StandardKey.Find, dialog)
        self.shortcut.activated.connect(self.focus)

    def add(self, label, page, control, aliases):
        self.entries.append((label, page, control, words(label), words(aliases)))

    def focus(self):
        self.field.setFocus(Qt.FocusReason.OtherFocusReason)
        self.field.selectAll()

    @staticmethod
    def rank(query, title, aliases):
        if query == title:
            return 0
        if query in title:
            return 1
        if f" {query} " in f" {aliases} ":
            return 2
        source = (title + " " + aliases).split()
        if all(any(word.startswith(term) for word in source) for term in query.split()):
            return 3
        return None

    def update(self, text):
        query = words(text)
        self.results.clear()
        self.dialog.content_stack.setCurrentIndex(1 if query else 0)
        if not query:
            return
        matches = []
        for label, page, control, title, aliases in self.entries:
            score = self.rank(query, title, aliases)
            if score is not None:
                matches.append((score, label, page, control))
        for _, label, page, control in sorted(matches, key=lambda item: item[0]):
            detail = self.dialog.nav.item(page).text()
            item = QListWidgetItem(f"{label}\n{detail}" if detail != label else label)
            item.setSizeHint(QSize(300, 53))
            item.setData(Qt.ItemDataRole.UserRole, (page, control))
            self.results.addItem(item)
        if matches:
            self.results.setCurrentRow(0)
        else:
            item = QListWidgetItem("Không tìm thấy. Thử một từ khác, ví dụ «cỡ chữ» hoặc «sao lưu».")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(item)

    def activate(self):
        item = self.results.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if data is None:
            return
        page, control = data
        self.dialog.nav.setCurrentRow(page)
        if self.dialog.pages.currentIndex() != page:
            return
        self.field.clear()
        if control is None:
            self.dialog.pages.widget(page).verticalScrollBar().setValue(0)
            self.dialog.nav.setFocus()
            return
        if control in self.theme_cards or control is getattr(self.dialog, "theme_restore", None):
            self.dialog._reveal_theme_catalog()
        parent = control
        while parent is not None:
            form = getattr(parent, "_settings_form", None)
            if form is not None and form.disclosure is not None:
                form.disclosure.setChecked(True)
            if isinstance(parent, QTabWidget):
                index = parent.indexOf(control)
                if index >= 0:
                    parent.setCurrentIndex(index)
            parent = parent.parentWidget()
        area = self.dialog.pages.widget(page)
        area.widget().layout().activate()

        def reveal():
            if self.dialog.pages.currentIndex() == page and not self.field.text() and control.isVisible():
                area.ensureWidgetVisible(getattr(control, "_settings_row", control), 12, 24)
                control.setFocus(Qt.FocusReason.OtherFocusReason)

        QTimer.singleShot(0, reveal)
        QTimer.singleShot(duration("section", self.dialog) + 30, reveal)

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress:
            return False
        if event.key() == Qt.Key.Key_Escape and self.field.text():
            self.field.clear()
            return True
        if self.field.text() and event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            direction = 1 if event.key() == Qt.Key.Key_Down else -1
            self.results.setCurrentRow(max(0, min(self.results.count() - 1, self.results.currentRow() + direction)))
            return True
        return False


def save_feedback(dialog, text):
    experience = getattr(dialog, "_settings_experience", None)
    code_error = getattr(experience, "code_error", None)
    if text.startswith("Chưa lưu:"):
        short = "Chưa lưu · xem chi tiết"
    elif text.startswith("Đang") or text.startswith("Đã lưu. Đang"):
        short = "Đang áp dụng…"
    elif text.startswith("Đã xuất"):
        short = "Đã xuất ZIP"
    elif text.startswith("Đã tạo"):
        short = "Đã sao lưu"
    elif "Mã còn lỗi" in text or (text.startswith("Đã") and code_error):
        short = "Đã lưu · mã còn lỗi"
        if code_error and code_error not in text:
            text += "\n" + code_error
    elif text.startswith("Đã"):
        short = "Đã lưu và áp dụng"
    else:
        short = "Tự động lưu"
    dialog.save_status.setText(short)
    dialog.save_status.setToolTip(text)
    dialog.save_status.setAccessibleDescription(text)
