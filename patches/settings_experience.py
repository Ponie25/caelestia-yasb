"""Settings guidance and automatic saving for the installed YASB dialog."""
from contextlib import suppress
from copy import deepcopy
from pathlib import Path
import json
import time

import yaml
from PyQt6.QtCore import QEvent, QObject, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontInfo, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QWidget

from core.utils.bar_preferences import appearance_preset, atomic_write, material_preset, validate_config, validate_preferences
from core.utils.bar_surface import surface_spec
from core.utils.settings_window import FluentExpander
from core.utils.ui_motion import SectionReveal


def description(text):
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setWordWrap(True)
    return label


def caption(control, title, detail=None):
    row = control._settings_row
    control.setAccessibleName(title)
    row.title.setText(title)
    if detail is not None:
        row._description_text = detail
        row.setControlEnabled(control.isEnabled(), row._reason)


class BarReadabilityPreview(QWidget):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.setMinimumHeight(94)
        self.setAccessibleName("Xem trước chữ trên nền sáng và tối")

    def paintEvent(self, _event):
        dialog = self.dialog
        preferences = dialog._collect_preferences()
        appearance = preferences["appearance"]
        palette = dialog._preview_palette(preferences)
        light, dark = QColor("#d6dae1"), QColor("#303740")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(appearance["font_family"])
        font.setPixelSize(appearance["font_size"])
        font.setWeight(min(QFont.Weight, key=lambda weight: abs(weight - appearance["font_weight"])))
        painter.setFont(font)
        dark_left = self.width() // 2
        panels = (
            (QRectF(0, 0, dark_left - 4, self.height()), light, "Nền sáng"),
            (QRectF(dark_left + 4, 0, self.width() - dark_left - 4, self.height()), dark, "Nền tối"),
        )
        for bounds, backdrop, label in panels:
            panel = QPainterPath()
            panel.addRoundedRect(bounds, 8, 8)
            painter.fillPath(panel, backdrop)
            spec = surface_spec(preferences, palette, (backdrop.name(),))
            bar = bounds.adjusted(0, 18, 0, -33)
            painter.save()
            painter.setClipPath(panel)
            surface = QPainterPath()
            radius = min(appearance["radius"], bar.height() / 2)
            surface.addRoundedRect(bar, radius, radius)
            if spec["enabled"]:
                color = QColor(spec["color"])
                color.setAlphaF(spec["alpha"])
                if spec["gradient"]:
                    gradient = QLinearGradient(
                        bar.topLeft(), bar.topRight() if spec["direction"] == "horizontal" else bar.bottomLeft()
                    )
                    second = QColor(spec["second"])
                    second.setAlphaF(spec["alpha2"])
                    gradient.setColorAt(0, color)
                    gradient.setColorAt(1, second)
                    painter.fillPath(surface, gradient)
                else:
                    painter.fillPath(surface, color)
            elif appearance["background"] == "theme":
                color = QColor(palette["MANTLE"])
                color.setAlphaF(spec["theme_alpha"])
                painter.fillPath(surface, color)
            if appearance["border"]:
                edge = QColor(spec["edge"])
                edge.setAlphaF(appearance["border_opacity"])
                painter.setPen(QPen(edge, appearance["border_width"]))
                if appearance["border_edges"] == "all":
                    painter.drawPath(surface)
                else:
                    line = bar.topLeft() if appearance["border_edges"] == "top" else bar.bottomLeft()
                    painter.drawLine(line, line + bar.topRight() - bar.topLeft())
            painter.setPen(QColor(spec["ink"]))
            painter.drawText(bar.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignCenter, "Ponie  |  19:30")
            label_font = QFont("Segoe UI")
            label_font.setPixelSize(12)
            painter.setFont(label_font)
            painter.setPen(QColor("#191b21" if backdrop.lightness() > 130 else "#ffffff"))
            painter.drawText(bounds.adjusted(0, 61, 0, 0), Qt.AlignmentFlag.AlignCenter, label)
            painter.restore()


class SettingsExperience(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.search_actions = []
        self.draft_timer = QTimer(self, singleShot=True)
        self.draft_timer.timeout.connect(self.apply_draft)
        self.reflow_timer = QTimer(self, singleShot=True)
        self.reflow_timer.timeout.connect(self.reflow_catalog)
        self.appearance_viewport = dialog.pages.widget(0).viewport()
        self.failed_signature = None
        self.code_error = None
        self.saving_draft = False
        self.json_base = None

        self.appearance()
        self.surface()
        self.layout()
        self.island()
        self.backups()

        self.refresh_draft_state = dialog._refresh_draft_state
        dialog._refresh_draft_state = self.refresh_save_state
        dialog._draft_timer.timeout.disconnect()
        dialog._draft_timer.timeout.connect(self.refresh_save_state)
        dialog.raw_preferences.document().modificationChanged.connect(self.track_json_base)
        dialog._consume_advanced_drafts = self.flush_draft
        dialog._immediate_timer.setInterval(140)
        dialog._adapt_navigation = self.adapt_navigation
        self.restore_window_state()

    def field(self, key, group="appearance"):
        return self.dialog.controls[group, key][0]

    def page_layout(self, index):
        return self.dialog.pages.widget(index).widget().layout()

    def replace_preview(self, index, name):
        layout = self.page_layout(index)
        old = getattr(self.dialog, name)
        position = layout.indexOf(old)
        preview = BarReadabilityPreview(self.dialog)
        layout.removeWidget(old)
        old.hide()
        old.deleteLater()
        layout.insertWidget(position, preview)
        setattr(self.dialog, name, preview)

    def appearance(self):
        dialog = self.dialog
        layout = self.page_layout(0)
        layout.itemAt(1).widget().setText("Chỉnh chữ trên thanh bar hoặc mở bộ màu để đổi preset.")
        self.replace_preview(0, "appearance_preview")
        color_form = self.field("foreground")._settings_form
        font_form = self.field("font_size")._settings_form
        catalog = dialog._section(layout, "Bộ màu giao diện", collapsed=True)
        layout.removeWidget(catalog.section_card)
        while layout.indexOf(color_form.section_card) > 3:
            item = layout.takeAt(3)
            if item.widget() is not None:
                catalog.addWidget(item.widget())
            elif item.layout() is not None:
                catalog.addLayout(item.layout())

        self.catalog = catalog
        dialog._reveal_theme_catalog = self.reveal_catalog
        catalog.disclosure.toggled.connect(lambda opened: self.queue_reflow() if opened else None)
        layout.insertWidget(3, catalog.section_card)
        font_form.disclosure.setText("Phông chữ, độ đậm và khoảng cách")
        font_form.disclosure.setAccessibleName("Phông chữ, độ đậm và khoảng cách")

        size = self.field("font_size")
        size.setSuffix(" px")
        caption(size, "Cỡ chữ")
        font = self.field("font_family")
        caption(font, "Phông chữ")
        for index, text in enumerate(("Vừa", "Hơi đậm", "Đậm vừa", "Đậm")):
            if index < self.field("font_weight").count():
                self.field("font_weight").setItemText(index, text)
        size_row = size._settings_row
        font_form.removeWidget(size_row)
        size._settings_form = None
        layout.insertWidget(4, size_row)
        choices = self.choice_buttons(
            (("Nhỏ", 10), ("Vừa", 12), ("Lớn", 15)),
            lambda value: self.change_field("appearance", "font_size", value),
        )
        layout.insertWidget(5, choices)
        self.size_buttons = choices

        foreground = self.field("foreground")
        caption(foreground, "Cách tô màu chữ và biểu tượng")
        labels = {"auto": "Tự động · dễ đọc theo nền", "theme": "Theo bộ màu đang dùng",
                  "tint": "Màu riêng · tự giữ độ rõ", "custom": "Màu riêng · giữ đúng màu"}
        for index in range(foreground.count()):
            value = foreground.itemData(index)
            if value in labels:
                foreground.setItemText(index, labels[value])
        caption(self.field("text_color"), "Màu chữ riêng", "Chọn một màu có sẵn bên dưới hoặc tự chọn.")
        for name, (button, _color) in dialog.text_color_presets.items():
            button.setCheckable(True)
            button.setProperty("motion-preset", True)
            button.setToolTip("Giữ đúng màu" if name in ("black", "white") else "Tự tăng độ rõ theo nền")
            button.clicked.connect(dialog._flush_immediate_preferences)
        modes = self.choice_buttons(
            (("Tự động", "auto"), ("Theo bộ màu", "theme")),
            lambda mode: self.change_field("appearance", "foreground", mode),
        )
        color_form.insertWidget(0, modes)
        self.ink_hint = description("")
        color_form.insertWidget(1, self.ink_hint)
        self.mode_buttons = modes
        custom = dialog._section(color_form, "Tùy chọn màu chữ", collapsed=True)
        for control in (foreground, self.field("text_color")):
            color_form.removeWidget(control._settings_row)
            custom.addWidget(control._settings_row)
            control._settings_form = custom
        picker = QPushButton("Chọn màu khác…")
        picker.clicked.connect(self.field("text_color").choose)
        modes.layout().insertWidget(2, picker)
        self.field("text_color").changed.connect(self.save_custom_ink)
        caption(font, "Phông chữ", "Phông dùng cho chữ trên thanh bar.")
        font.activated.connect(self.sync_appearance)
        font.lineEdit().editingFinished.connect(self.sync_appearance)
        size.valueChanged.connect(self.sync_appearance)
        foreground.currentIndexChanged.connect(self.sync_appearance)
        self.field("text_color").changed.connect(self.sync_appearance)
        dialog.status.changed.connect(self.sync_appearance)
        dialog.picker_search.textChanged.connect(self.queue_reflow)
        dialog.tone_group.buttonClicked.connect(self.queue_reflow)
        self.appearance_viewport.installEventFilter(self)
        dialog.theme_restore.setToolTip("Khôi phục thiết lập gốc của preset đang dùng.")
        sync_picker = dialog._sync_picker

        def update_picker():
            sync_picker()
            self.sync_appearance()

        dialog._sync_picker = update_picker
        modes.setFocusProxy(modes.findChildren(QPushButton)[0])
        self.search_actions.append(("Màu chữ", 0, modes, "màu chữ biểu tượng"))
        self.search_actions.append(("Bộ màu giao diện", 0, catalog.disclosure, "theme preset đổi màu"))
        self.search_actions.append(("Khôi phục mặc định của preset", 0, dialog.theme_restore, "đặt lại reset"))
        self.search_actions.append(("Màu nhấn của bộ màu", 0, dialog.custom_accent, "màu nhấn accent"))
        self.sync_appearance()

    @staticmethod
    def choice_buttons(options, callback):
        group = QWidget()
        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        for title, value in options:
            button = QPushButton(title)
            button.setCheckable(True)
            button.setProperty("motion-preset", True)
            button.setProperty("choice", value)
            button.clicked.connect(lambda _checked=False, value=value: callback(value))
            layout.addWidget(button)
        layout.addStretch()
        return group

    def sync_appearance(self, *_):
        dialog = self.dialog
        label = dialog.controller.theme_labels.get(dialog.controller.current, dialog.controller.current)
        title = f"Bộ màu · {label}"
        self.catalog.disclosure.setText(title)
        self.catalog.disclosure.setAccessibleName(title)
        size = self.field("font_size").value()
        mode = self.field("foreground").currentData()
        chosen = self.field("text_color").value.lower()
        for group, value in ((self.size_buttons, size), (self.mode_buttons, mode)):
            for button in group.findChildren(QPushButton):
                button.setChecked(button.property("choice") == value)
        palette = dialog.controller.catalog.palette(dialog.controller.current)
        appearance = dialog._collect_preferences()
        for name, (button, color) in dialog.text_color_presets.items():
            current = color or appearance["palette"].get("MAUVE", palette["MAUVE"])
            required = "custom" if name in ("black", "white") else "tint"
            button.setChecked(mode == required and chosen == current.lower())
        self.field("text_color").setText(chosen.upper())
        modes = {"auto": "Tự động theo nền", "theme": "Theo bộ màu", "tint": "Màu riêng tự giữ độ rõ",
                 "custom": "Giữ đúng màu riêng"}
        self.ink_hint.setText(modes[mode] + (f" · {chosen.upper()}" if mode in ("tint", "custom") else ""))
        font = self.field("font_family")
        family = str(font.property("requested_family"))
        caption(font, "Phông chữ", "Phông dùng cho chữ trên thanh bar." if QFontInfo(QFont(family)).family().casefold() == family.casefold()
                else "Nếu phông này chưa được cài, Windows sẽ dùng phông thay thế.")
        dialog.appearance_preview.update()
        dialog.surface_preview.update()

    def save_custom_ink(self, _color):
        if self.field("foreground").currentData() not in ("custom", "tint"):
            self.change_field("appearance", "foreground", "tint")
        else:
            self.dialog._flush_immediate_preferences()

    def reveal_catalog(self):
        self.catalog.disclosure.setChecked(True)
        self.dialog.picker_search.clear()
        self.dialog.tone_filter["all"].click()
        self.reflow_catalog()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and watched is self.appearance_viewport:
            self.queue_reflow()
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.KeyPress) and watched in self.dialog.region_lists.values():
            if event.type() == QEvent.Type.FocusIn:
                self.active_region = next(key for key, items in self.dialog.region_lists.items() if items is watched)
            if event.type() == QEvent.Type.KeyPress and event.modifiers() == Qt.KeyboardModifier.AltModifier:
                shifts = {Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1),
                          Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0)}
                if event.key() in shifts:
                    self.move_selected(*shifts[event.key()])
                    return True
        return False

    def queue_reflow(self, *_):
        self.reflow_timer.start(0)

    def reflow_catalog(self):
        columns = max(1, min(3, (self.appearance_viewport.width() - 18) // 210))
        for _title, _heading, grid in self.dialog.picker_groups.values():
            if all(grid.getItemPosition(index)[:2] == (index // columns, index % columns)
                   for index in range(grid.count())):
                continue
            cards = []
            while grid.count():
                item = grid.takeAt(0)
                if item.widget() is not None:
                    cards.append(item.widget())
            for index, card in enumerate(cards):
                grid.addWidget(card, index // columns, index % columns)

    def change_field(self, group, key, value):
        dialog = self.dialog
        dialog._set_field(group, key, value)
        dialog._refresh_preview()
        dialog._flush_immediate_preferences()

    def surface(self):
        dialog = self.dialog
        self.replace_preview(1, "surface_preview")
        caption(self.field("background_opacity"), "Độ đậm của nền", "0% là trong suốt. 100% che kín hình nền.")
        caption(self.field("background_blur"), "Làm mờ hình nền phía sau", "Hiệu ứng này chỉnh độ nét của hình nền.")
        caption(self.field("background_source"), "Nguồn màu nền")
        caption(self.field("background_color"), "Màu nền riêng")
        dialog.surface_preset_buttons["soft"].setText("Kính nhẹ")
        dialog.surface_preset_buttons["balanced"].setText("Kính đậm")
        dialog._surface_preset = self.set_background
        dialog._refresh_preset_selection = self.refresh_background_selection
        original_source = dialog._preset_source

        def preset_source(group, key):
            if (group, key) == ("appearance", "background") and self.field("background").currentData() == "theme":
                self.set_background("theme")
            else:
                original_source(group, key)

        dialog._preset_source = preset_source
        first = self.field("background_opacity")._settings_form.section_card
        self.surface_options = first
        self.field("background").currentIndexChanged.connect(self.refresh_background)
        self.refresh_background()
        for name, button in dialog.surface_preset_buttons.items():
            self.search_actions.append((button.text(), 1, button, "nền thanh bar"))
        for button in self.page_layout(1).parentWidget().findChildren(QPushButton):
            if button.text() == "Dùng màu hiện tại làm màu riêng":
                button.setText("Lấy màu nền của bộ màu để chỉnh riêng")

    def set_background(self, name):
        dialog = self.dialog
        settings = dialog._collect_preferences()
        palette = dialog._preview_palette(settings)
        dialog._immediate_begin_loading()
        try:
            for key, value in appearance_preset(palette, name).items():
                if key.startswith("background") or key == "gradient_direction":
                    dialog._set_field("appearance", key, value)
        finally:
            dialog._immediate_end_loading()
        dialog._refresh_preview()
        dialog._flush_immediate_preferences()

    def refresh_background(self, *_):
        mode = self.field("background").currentData()
        self.surface_options.setVisible(mode in ("glass", "custom"))
        self.refresh_background_selection()

    def refresh_background_selection(self):
        dialog = self.dialog
        appearance = dialog._collect_preferences()["appearance"]
        selected = "clear" if appearance["background"] == "transparent" else None
        if appearance["background"] == "glass" and appearance["background_source"] == "theme" and not appearance["background_gradient"]:
            for name, alpha, blur in (("soft", .36, True), ("balanced", .56, True), ("solid", 1., False)):
                if abs(appearance["background_opacity"] - alpha) < .0001 and appearance["background_blur"] == blur:
                    selected = name
                    break
        for key, button in dialog.surface_preset_buttons.items():
            button.setChecked(key == selected)
        label = dialog.surface_preset_buttons[selected].text() if selected else (
            "Theo bộ màu" if appearance["background"] == "theme" else "Màu nền riêng"
        )
        dialog.surface_preset_label.setText("Đang dùng: " + label)

    def layout(self):
        dialog = self.dialog
        layout = self.page_layout(2)
        layout.itemAt(1).widget().setText("Kéo hoặc dùng các nút để đổi vị trí. Thanh bar cập nhật sau mỗi thay đổi.")
        center = dialog.region_lists["center"]
        center.setToolTip("Dynamic Island ở giữa và có cài đặt riêng trong Island và Launcher.")
        center.setAccessibleDescription(center.toolTip())
        hint = description("Dynamic Island có vị trí riêng ở giữa. Cột Giữa bên dưới dành cho mục YASB.")
        layout.insertWidget(2, hint)
        for name, control, terms in (
            ("Vị trí thanh bar", dialog.position, "bố cục trên dưới"),
            ("Chiều cao thanh bar", dialog.bar_height, "bố cục kích thước"),
        ):
            self.search_actions.append((name, 2, control, terms))
        dialog.bar_height.setSuffix(" px")
        dialog.bar_height.setKeyboardTracking(False)
        self.active_region = "left"
        for items in dialog.region_lists.values():
            items.setAccessibleDescription("Kéo để sắp xếp hoặc dùng Alt và các phím mũi tên.")
            items.installEventFilter(self)
        moves = QWidget()
        buttons = QHBoxLayout(moves)
        buttons.setContentsMargins(0, 0, 0, 0)
        for title, (x, y) in (("Sang trái", (-1, 0)), ("Lên", (0, -1)), ("Xuống", (0, 1)), ("Sang phải", (1, 0))):
            button = QPushButton(title)
            button.clicked.connect(lambda _checked=False, x=x, y=y: self.move_selected(x, y))
            buttons.addWidget(button)
        layout.insertWidget(4, moves)
        # Use the existing validated width field as the persistence model.
        original = dialog.bar_width
        row = original._settings_row
        input_box = QWidget()
        widths = QHBoxLayout(input_box)
        widths.setContentsMargins(0, 0, 0, 0)
        unit = QComboBox()
        for label, value in (("Tự động", "auto"), ("% màn hình", "%"), ("pixel", "px")):
            unit.addItem(label, value)
        unit.setAccessibleName("Cách đặt chiều rộng")
        amount = QSpinBox()
        amount.setAccessibleName("Chiều rộng")
        amount.setKeyboardTracking(False)
        widths.addWidget(amount)
        widths.addWidget(unit)
        row._box.removeWidget(original)
        original.hide()
        row._box.addWidget(input_box)
        row.control = input_box
        row.title.setText("Chiều rộng thanh bar")
        row.title.setBuddy(unit)
        input_box._settings_row = row
        for section in layout.parentWidget().findChildren(FluentExpander):
            if section.text().startswith("Kích thước"):
                self.search_actions.append(("Kích thước và vị trí thanh bar", 2, section, "bố cục chiều rộng chiều cao"))
                break

        def sync_width():
            width = original.text().strip()
            mode = "auto" if width == "auto" else "%" if width.endswith("%") else "px"
            unit.blockSignals(True)
            amount.blockSignals(True)
            unit.setCurrentIndex(unit.findData(mode))
            amount.setRange(1, 100 if mode == "%" else 32768)
            amount.setValue(int(width.strip("%")) if width.strip("%").isdigit() else 100)
            amount.setEnabled(mode != "auto")
            amount.blockSignals(False)
            unit.blockSignals(False)

        def set_width():
            mode = unit.currentData()
            amount.setRange(1, 100 if mode == "%" else 32768)
            amount.setEnabled(mode != "auto")
            original.setText("auto" if mode == "auto" else str(amount.value()) + ("%" if mode == "%" else ""))

        original.textChanged.connect(sync_width)
        unit.currentIndexChanged.connect(set_width)
        amount.valueChanged.connect(set_width)
        self.search_actions.append(("Chiều rộng thanh bar", 2, input_box, "bố cục kích thước"))
        sync_width()

    def move_selected(self, side, step):
        lists = self.dialog.region_lists
        regions = list(lists)
        source = lists[self.active_region]
        row = source.currentRow()
        region = regions.index(self.active_region) + side
        if row < 0 or not 0 <= region < len(regions):
            return
        destination = lists[regions[region]]
        if step and not 0 <= row + step < source.count():
            return
        position = row + step if step else destination.count()
        destination.insertItem(position, source.takeItem(row))
        destination.setCurrentRow(position)
        self.active_region = regions[region]
        destination.setFocus()

    def adapt_navigation(self):
        dialog = self.dialog
        compact = dialog.width() < 760
        changed = dialog.nav.property("compact") != compact
        dialog.nav.setProperty("compact", compact)
        dialog.nav_pane.setFixedWidth(48 if compact else 190)
        dialog.nav_title.setVisible(not compact)
        dialog.advanced_button.setText("⋯" if compact else "Thiết lập nâng cao")
        if changed:
            dialog.nav.doItemsLayout()
            dialog.nav.viewport().update()

    def island(self):
        caption(self.field("glass", "island"), "Dùng nền kính cho Island")
        caption(self.field("material", "island"), "Kiểu kính", "Dùng chung cho Island, menu và ô tìm kiếm.")
        caption(self.field("hotkey", "launcher"), "Mở tìm kiếm bằng Alt+Space")
        caption(self.field("wallpaper_auto_theme", "launcher"), "Tự đổi bộ màu khi đổi hình nền")
        caption(self.field("city", "weather"), "Tên hiển thị của địa điểm",
                "Tên và tọa độ cần chỉ cùng một nơi. Dự báo lấy theo vĩ độ và kinh độ bên dưới.")
        caption(self.field("notification_seconds", "island"), "Thời gian hiện thông báo")
        caption(self.field("monocle_color", "komorebi"), "Cửa sổ ở chế độ một cửa sổ (Monocle)")
        layout = self.page_layout(4)
        layout.itemAt(1).widget().setText("Chỉnh Dynamic Island, phím tắt tìm kiếm và tùy chọn hình nền.")
        self.collapse_group(self.field("wallpaper_favorites_only", "launcher")._settings_form,
                            "Hình nền và tự đổi bộ màu")
        self.collapse_group(self.field("default_tab", "island")._settings_form, "Trang mở khi bấm Island")
        material = self.field("material", "island")
        material.activated.disconnect(self.dialog._material_preset)
        material.activated.connect(self.choose_material)
        self.dialog.material_reset.setText("Khôi phục thiết lập của kiểu kính")

    def choose_material(self, *_):
        dialog = self.dialog
        mode = self.field("material", "island").currentData()
        dialog._immediate_begin_loading()
        try:
            for key, value in material_preset(mode).items():
                if key not in ("glass", "outline"):
                    dialog._set_field("island", key, value)
        finally:
            dialog._immediate_end_loading()
        dialog._refresh_preview()
        dialog._flush_immediate_preferences()

    @staticmethod
    def collapse_group(form, title):
        box = form.section_card.layout()
        heading = box.takeAt(0).widget()
        heading.hide()
        heading.deleteLater()
        disclosure = FluentExpander(title)
        disclosure.setObjectName("SectionDisclosure")
        box.insertWidget(0, disclosure)
        form.disclosure = disclosure
        form.section_body.hide()
        form.reveal = SectionReveal(disclosure, form.section_body)

    def backups(self):
        dialog = self.dialog
        layout = self.page_layout(6)
        layout.itemAt(1).widget().setText("Lưu cấu hình hiện tại để quay lại khi cần.")
        self.page_layout(7).itemAt(1).widget().setText(
            "Nội dung hợp lệ tự lưu sau khi bạn dừng nhập. Nếu có lỗi, thanh bar tiếp tục dùng bản đã lưu."
        )
        for button in layout.parentWidget().findChildren(QPushButton):
            if button.text() == "Tạo bản sao lưu ngay":
                self.search_actions.append(("Tạo bản sao lưu", 6, button, "backup lưu"))
        self.search_actions.append(("Khôi phục bản sao lưu", 6, dialog.backup_list, "quay về phục hồi backup"))
        for title, editor in (("YAML của YASB", dialog.raw_yaml), ("CSS tùy chỉnh", dialog.custom_css),
                              ("JSON của Settings", dialog.raw_preferences)):
            self.search_actions.append((title, 7, editor, "chỉnh bằng mã cấu hình"))
        refresh = dialog._refresh_backups
        details = {}

        def describe_backups():
            refresh()
            for index in range(dialog.backup_list.count()):
                item = dialog.backup_list.item(index)
                directory = Path(item.data(Qt.ItemDataRole.UserRole))
                if directory not in details:
                    try:
                        theme = json.loads((directory / "theme.json").read_bytes())["name"]
                        label = dialog.controller.theme_labels.get(theme, theme)
                    except (OSError, UnicodeError, ValueError, KeyError):
                        label = ""
                    created = directory.name.split("-")
                    seconds = ":" + created[1][-2:] if len(created) > 1 and len(created[1]) == 6 else ""
                    head, separator, tail = item.text().partition("   ·   ")
                    details[directory] = head + seconds + separator + tail + (" · " + label if label else "")
                item.setText(details[directory])

        dialog._refresh_backups = describe_backups
        describe_backups()
        restore = dialog._restore
        dialog.restore_button.clicked.disconnect(restore)

        def confirm_restore():
            item = dialog.backup_list.currentItem()
            if item is None:
                return
            box = QMessageBox(dialog)
            box.setWindowTitle("Khôi phục cấu hình")
            box.setText(item.text())
            box.setInformativeText(
                "Khôi phục sẽ dùng cấu hình trong bản sao đã chọn. "
                "Cấu hình đang dùng sẽ được sao lưu trước."
                + (" Nội dung đang chỉnh và chưa lưu sẽ bị bỏ." if dialog._draft_dirty else "")
            )
            confirm = box.addButton("Khôi phục", QMessageBox.ButtonRole.AcceptRole)
            cancel = box.addButton("Quay lại", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(cancel)
            box.exec()
            if box.clickedButton() is confirm:
                self.draft_timer.stop()
                dialog._immediate_timer.stop()
                restore()

        dialog.restore_button.clicked.connect(confirm_restore)

    def track_json_base(self, modified):
        self.json_base = deepcopy(self.dialog._immediate_saved_preferences) if modified else None

    def refresh_save_state(self, *args, **kwargs):
        self.refresh_draft_state(*args, **kwargs)
        dialog = self.dialog
        if self.saving_draft or dialog._committing or dialog._immediate_loading or dialog._immediate_busy:
            return
        signature = self.manual_signature()
        if signature is None:
            self.draft_timer.stop()
            self.code_error = None
            return
        dialog.apply_button.setVisible(False)
        if signature == self.failed_signature:
            return
        dialog.status.setText("Đang lưu thay đổi…")
        self.draft_timer.start(900 if dialog.nav.currentRow() == 7 else 420)

    def manual_signature(self):
        dialog = self.dialog
        current = json.loads(dialog._draft_signature())
        saved = json.loads(dialog._draft_saved_signature)
        raw = dialog.raw_preferences
        has_json = raw.document().isModified() and current[1] != saved[1]
        if current[2:] != saved[2:] or has_json:
            return dialog._draft_json((current[2:], raw.toPlainText() if has_json else None))
        return None

    def flush_draft(self):
        self.apply_draft()

    def apply_draft(self):
        dialog = self.dialog
        self.draft_timer.stop()
        if self.saving_draft or dialog._committing:
            return
        signature = self.manual_signature()
        if signature is None or signature == self.failed_signature:
            return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            self.draft_timer.start(180)
            return
        self.saving_draft = True
        raw = dialog.raw_preferences
        modified = raw.document().isModified()
        try:
            if dialog.raw_yaml.document().isModified():
                validate_config(yaml.safe_load(dialog.raw_yaml.toPlainText()))
            dialog._validate_css(dialog.custom_css.toPlainText())
            if modified:
                imported = validate_preferences(json.loads(raw.toPlainText()))
                if self.json_base is not None:
                    latest = dialog._collect_preferences()
                    for group, values in imported.items():
                        if group == "palette":
                            if values != self.json_base[group]:
                                latest[group] = values
                            continue
                        for key, value in values.items():
                            if value != self.json_base[group][key]:
                                latest[group][key] = value
                    if latest != imported:
                        cursor = raw.textCursor().position()
                        raw.setPlainText(json.dumps(latest, ensure_ascii=False, indent=2))
                        raw.document().setModified(True)
                        caret = raw.textCursor()
                        caret.setPosition(min(cursor, len(raw.toPlainText())))
                        raw.setTextCursor(caret)
            self.code_error = None
            dialog.apply_changes()
            if dialog.status.text().startswith("Chưa lưu:"):
                self.failed_signature = self.manual_signature()
            else:
                self.failed_signature = None
        except (ValueError, TypeError, yaml.YAMLError) as error:
            self.failed_signature = signature
            self.code_error = f"Nội dung chưa hợp lệ. {error}"
            dialog._error(self.code_error)
        finally:
            self.saving_draft = False
        if self.failed_signature is not None:
            dialog.apply_button.setVisible(False)

    def restore_window_state(self):
        dialog = self.dialog
        path = dialog.root / "settings-window-reopen.json"
        original = dialog._schedule_reload

        def reload_preserving_view():
            rect = dialog.geometry()
            state = {"time": time.time(), "rect": [rect.x(), rect.y(), rect.width(), rect.height()],
                     "scroll": dialog.pages.currentWidget().verticalScrollBar().value(),
                     "advanced": dialog.advanced_button.isChecked()}
            with suppress(OSError):
                atomic_write(path, json.dumps(state))
            original()
            dialog.content_stack.setEnabled(False)

        dialog._schedule_reload = reload_preserving_view
        try:
            state = json.loads(path.read_bytes())
            path.unlink()
            if time.time() - state["time"] > 30:
                return
            rect = QRect(*state["rect"])
            if dialog.screen().availableGeometry().intersects(rect):
                geometry_timer = QTimer(self, singleShot=True)
                geometry_timer.timeout.connect(lambda: dialog.setGeometry(rect))
                geometry_timer.start(0)
            dialog.advanced_button.setChecked(state["advanced"])
            scroll_timer = QTimer(self, singleShot=True)
            scroll_timer.timeout.connect(
                lambda: dialog.pages.currentWidget().verticalScrollBar().setValue(state["scroll"])
            )
            scroll_timer.start(260)
        except (OSError, ValueError, TypeError, KeyError):
            pass


def install_settings_experience(dialog):
    dialog._settings_experience = SettingsExperience(dialog)
