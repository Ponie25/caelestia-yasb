"""Small Qt adapters for Microsoft's Windows typography, layout and color roles.

Guidance (the underlying Qt widgets retain their native input/accessibility):
https://learn.microsoft.com/windows/apps/design/signature-experiences/typography
https://learn.microsoft.com/windows/apps/design/basics/content-basics
https://learn.microsoft.com/windows/apps/design/layout/alignment-margin-padding
https://learn.microsoft.com/windows/apps/develop/ui/controls/navigationview
https://learn.microsoft.com/windows/apps/design/style/mica
https://learn.microsoft.com/windows/apps/design/accessibility/high-contrast-themes

Neutral colors here are solid fallback colors, not an imitation blur effect.
The owning window is responsible for requesting a native system backdrop.
"""
import sys

from PyQt6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication, QBoxLayout, QLabel, QSizePolicy, QStyle,
    QStyledItemDelegate, QVBoxLayout, QWidget,
)


NAV_ICON_ROLE = int(Qt.ItemDataRole.UserRole) + 41
NAV_GLYPHS = ('\ue771', '\ue90e', '\ue8a9', '\ue71d',
              '\ue91c', '\ue8f9', '\ue777', '\ue943')


def _color(value, fallback):
    candidate = QColor(value) if isinstance(value, (str, QColor)) else QColor()
    return candidate.name() if candidate.isValid() else fallback


def _luminance(color):
    def linear(value):
        return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
    return sum(weight * linear(value) for weight, value in
               zip((.2126, .7152, .0722), QColor(color).getRgbF()[:3]))


def _contrast(first, second):
    a, b = sorted((_luminance(first), _luminance(second)))
    return (b + .05) / (a + .05)


def _readable_accent(accent, background):
    """Keep the supplied hue while making a small selection indicator visible."""
    color = QColor(accent)
    if _contrast(color, background) >= 3:
        return color.name()
    target = QColor('#000000' if _luminance(background) > .35 else '#ffffff')
    initial = color.getRgbF()
    for step in range(1, 21):
        amount = step / 20
        color = QColor.fromRgbF(*(a + (b - a) * amount
                                 for a, b in zip(initial, target.getRgbF())))
        if _contrast(color, background) >= 3:
            break
    return color.name()


def _system_light(fallback=True):
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                return bool(winreg.QueryValueEx(key, 'AppsUseLightTheme')[0])
        except (OSError, ValueError):
            pass
    app = QApplication.instance()
    if app is not None:
        return _luminance(app.palette().color(QPalette.ColorRole.Window)) > .35
    return fallback


def _system_high_contrast():
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        class HIGHCONTRAST(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                        ('lpszDefaultScheme', wintypes.LPWSTR)]
        value = HIGHCONTRAST()
        value.cbSize = ctypes.sizeof(value)
        return bool(ctypes.windll.user32.SystemParametersInfoW(
            0x0042, value.cbSize, ctypes.byref(value), 0) and value.dwFlags & 1)
    except (OSError, AttributeError):
        return False


def _system_colors():
    # Use OS color pairs, not guessed black/white, for user-defined contrast themes.
    roles = {'window': 5, 'text': 8, 'highlight': 13, 'highlight_text': 14,
             'button': 15, 'disabled': 17, 'button_text': 18, 'link': 26}
    if sys.platform == 'win32':
        try:
            import ctypes
            values = {}
            for name, index in roles.items():
                raw = ctypes.windll.user32.GetSysColor(index)
                values[name] = '#%02x%02x%02x' % (raw & 255, raw >> 8 & 255, raw >> 16 & 255)
            return values
        except (OSError, AttributeError):
            pass
    palette = QApplication.palette() if QApplication.instance() else QPalette()
    mapping = {'window': QPalette.ColorRole.Window, 'text': QPalette.ColorRole.WindowText,
               'highlight': QPalette.ColorRole.Highlight, 'highlight_text': QPalette.ColorRole.HighlightedText,
               'button': QPalette.ColorRole.Button, 'button_text': QPalette.ColorRole.ButtonText,
               'link': QPalette.ColorRole.Link}
    result = {key: palette.color(value).name() for key, value in mapping.items()}
    result['disabled'] = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText).name()
    return result


def fluent_palette(bar_palette=None, mode='system', *, high_contrast=None):
    """Return neutral Windows role colors plus the existing bar palette aliases.

    ``mode`` is system/light/dark/high-contrast. System honors AppsUseLightTheme.
    Native contrast mode always wins unless tests explicitly pass
    ``high_contrast=False``. Color values are hex strings; HIGH_CONTRAST is a bool
    and MODE is light/dark/high-contrast. The bar's accent hue is retained.
    """
    source = dict(bar_palette or {})
    fallback_light = _luminance(_color(source.get('BASE'), '#f3f3f3')) > .35
    light = _system_light(fallback_light) if mode == 'system' else mode == 'light'
    contrast = _system_high_contrast() if high_contrast is None else bool(high_contrast)
    contrast = contrast or mode in ('high-contrast', 'highcontrast')
    if contrast:
        system = _system_colors()
        roles = dict(WINDOW=system['window'], LAYER=system['window'],
                     CARD=system['window'], CARD_HOVER=system['window'],
                     CONTROL=system['button'], CONTROL_TEXT=system['button_text'], CONTROL_BORDER=system['text'],
                     TEXT_PRIMARY=system['text'], TEXT_SECONDARY=system['text'],
                     DISABLED=system['disabled'], NAV_SELECTED=system['highlight'],
                     NAV_SELECTED_TEXT=system['highlight_text'], NAV_HOVER=system['highlight'],
                     NAV_HOVER_TEXT=system['highlight_text'], ACCENT=system['highlight'],
                     ACCENT_TEXT=system['highlight_text'], FOCUS=system['text'], LINK=system['link'],
                     STROKE=system['text'], HIGH_CONTRAST=True, MODE='high-contrast')
    else:
        roles = dict(
            WINDOW='#f3f3f3' if light else '#202020',
            LAYER='#f9f9f9' if light else '#272727',
            CARD='#fbfbfb' if light else '#2b2b2b',
            CARD_HOVER='#f6f6f6' if light else '#303030',
            CONTROL='#ffffff' if light else '#333333',
            CONTROL_BORDER='#c7c7c7' if light else '#666666',
            TEXT_PRIMARY='#1a1a1a' if light else '#ffffff',
            TEXT_SECONDARY='#5b5b5b' if light else '#c5c5c5',
            DISABLED='#717171' if light else '#9b9b9b',
            NAV_SELECTED='#e5e5e5' if light else '#383838',
            NAV_SELECTED_TEXT='#1a1a1a' if light else '#ffffff',
            NAV_HOVER='#eaeaea' if light else '#2e2e2e',
            NAV_HOVER_TEXT='#1a1a1a' if light else '#ffffff',
            STROKE='#e0e0e0' if light else '#3d3d3d',
            FOCUS='#1a1a1a' if light else '#ffffff',
            HIGH_CONTRAST=False, MODE='light' if light else 'dark',
        )
        roles['ACCENT'] = _readable_accent(_color(source.get('MAUVE'), '#0067c0' if light else '#60cdff'),
                                           roles['WINDOW'])
        roles['ACCENT_TEXT'] = '#000000' if _luminance(roles['ACCENT']) > .179 else '#ffffff'
        roles['LINK'] = _readable_accent(roles['ACCENT'], roles['CARD'])
        roles['CONTROL_TEXT'] = roles['TEXT_PRIMARY']
    # Existing custom controls read these aliases from ancestor._surface_palette.
    roles.update(CRUST=roles['WINDOW'], MANTLE=roles['WINDOW'], BASE=roles['CONTROL'],
                 SURFACE=roles['CARD'], SURFACE2=roles['CONTROL_BORDER'],
                 OVERLAY=roles['CONTROL_BORDER'], MUTED=roles['DISABLED'] if contrast else roles['TEXT_SECONDARY'],
                 TEXT=roles['TEXT_PRIMARY'], MAUVE=roles['ACCENT'])
    for key in ('LAVENDER', 'PINK', 'ROSEWATER'):
        roles[key] = roles['ACCENT'] if contrast else _color(source.get(key), roles['ACCENT'])
    return roles


def _ancestor_palette(widget):
    current = widget
    while current is not None:
        palette = getattr(current, '_surface_palette', None)
        if isinstance(palette, dict):
            return palette if 'CARD' in palette and 'NAV_SELECTED' in palette else fluent_palette(palette)
        current = current.parentWidget()
    return fluent_palette()


class FluentNavigationDelegate(QStyledItemDelegate):
    """Native list selection/input, Windows iconography and a left accent marker.

    Set ``nav.setProperty('compact', True)`` for icon-only rendering. A custom
    glyph may be supplied per item at NAV_ICON_ROLE, otherwise NAV_GLYPHS maps the
    existing eight Settings pages. Native list keyboard/accessibility is retained.
    """
    def paint(self, painter, option, index):
        view = option.widget if option.widget is not None else self.parent()
        palette = _ancestor_palette(view)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        compact = bool(view.property('compact')) if view is not None else False
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(4, 2, -4, -2)
        text_color = palette['TEXT_PRIMARY'] if enabled else palette['DISABLED']
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(palette['NAV_SELECTED' if selected else 'NAV_HOVER']))
            painter.drawRoundedRect(rect, 4, 4)
            if enabled:
                text_color = palette['NAV_SELECTED_TEXT' if selected else 'NAV_HOVER_TEXT']
        if selected:
            painter.setBrush(QColor(palette['NAV_SELECTED_TEXT'] if palette['HIGH_CONTRAST'] else palette['ACCENT']))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(rect.left(), rect.center().y() - 8, 3, 16), 1.5, 1.5)
        glyph = index.data(NAV_ICON_ROLE)
        if glyph is None:
            glyph = NAV_GLYPHS[index.row()] if index.row() < len(NAV_GLYPHS) else '\ue713'
        if isinstance(glyph, int):
            glyph = chr(glyph)
        icon_font = QFont()
        icon_font.setFamilies(['Segoe Fluent Icons', 'Segoe MDL2 Assets'])
        icon_font.setPixelSize(16)
        painter.setFont(icon_font)
        painter.setPen(QColor(text_color))
        icon_rect = QRectF(rect.left() + 12, rect.top(), 20, rect.height())
        if compact:
            icon_rect.moveCenter(rect.center())
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, str(glyph))
        if not compact:
            font = QFont()
            font.setFamilies(['Segoe UI Variable', 'Segoe UI'])
            font.setPixelSize(14)
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            text_rect = rect.adjusted(44, 0, -12, 0)
            label = QFontMetrics(font).elidedText(str(index.data(Qt.ItemDataRole.DisplayRole) or ''),
                                                Qt.TextElideMode.ElideRight, max(0, round(text_rect.width())))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        if focused and enabled:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            focus = palette['NAV_SELECTED_TEXT'] if selected and palette['HIGH_CONTRAST'] else palette['FOCUS']
            painter.setPen(QPen(QColor(focus), 1.5))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 3, 3)
        painter.restore()

    def sizeHint(self, option, index):
        view=option.widget if option.widget is not None else self.parent()
        return QSize(44 if view is not None and view.property('compact') else 200, 40)


class SettingsRow(QWidget):
    """One setting card: explanatory text at left, its native action at right.

    Below 480 logical pixels, the control moves below its label/description.
    Disabling the control never removes the explanation; an optional reason can
    be shown there. Visibility applies to the complete row, not an orphan label.
    """
    def __init__(self, title, control, description='', parent=None):
        super().__init__(parent)
        self.setObjectName('SettingsRow')
        self.setProperty('setting-row', True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._description_text = str(description)
        self._reason = ''
        self._colors_signature = None
        self._stacked = None
        self.control = control
        self.text_container = QWidget(self)
        self.text_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.text_container.setMinimumWidth(0)
        texts = QVBoxLayout(self.text_container)
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(4)
        self.title = QLabel(str(title), self.text_container)
        self.title.setObjectName('SettingTitle')
        self.title.setProperty('role', 'setting-title')
        self.title.setWordWrap(True)
        self.title.setMinimumWidth(0)
        self.title.setBuddy(control)
        self.description = QLabel(str(description), self.text_container)
        self.description.setObjectName('SettingDescription')
        self.description.setProperty('role', 'setting-description')
        self.description.setWordWrap(True)
        self.description.setMinimumWidth(0)
        self.description.setVisible(bool(description))
        texts.addWidget(self.title)
        texts.addWidget(self.description)
        self._box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._box.setContentsMargins(16, 16, 16, 16)
        self._box.setSpacing(16)
        self._box.addWidget(self.text_container, 1)
        self._box.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if not control.accessibleName():
            control.setAccessibleName(str(title))
        if description and not control.accessibleDescription():
            control.setAccessibleDescription(str(description))
        control.installEventFilter(self)
        self._set_stacked(self.width() < 480)
        self.refreshPalette()

    def setControlEnabled(self, enabled, reason=''):
        self.control.setEnabled(bool(enabled))
        self.title.setEnabled(bool(enabled))
        self.description.setEnabled(bool(enabled))
        self._reason = str(reason) if not enabled else ''
        detail = ' '.join(part for part in (self._description_text, self._reason) if part)
        self.description.setText(detail)
        self.description.setVisible(bool(detail))
        self.control.setAccessibleDescription(detail)
        self.updateGeometry()
        self.update()

    def setControlVisible(self, visible):
        self.setVisible(bool(visible))

    def refreshPalette(self):
        if not hasattr(self, 'title'):
            return
        palette = _ancestor_palette(self)
        signature = tuple(palette[key] for key in ('TEXT_PRIMARY', 'TEXT_SECONDARY', 'DISABLED'))
        if signature == self._colors_signature:
            return
        self._colors_signature = signature
        for label, size, color in ((self.title, 14, palette['TEXT_PRIMARY']),
                                   (self.description, 12, palette['TEXT_SECONDARY'])):
            label.setStyleSheet('QLabel {background:transparent;border:none;'
                                'font-family:"Segoe UI Variable","Segoe UI";font-size:%dpx;'
                                'font-weight:400;color:%s;} QLabel:disabled {color:%s;}' %
                                (size, color, palette['DISABLED']))

    def _set_stacked(self, stacked):
        if stacked == self._stacked:
            return
        self._stacked = stacked
        self._box.setDirection(QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight)
        self._box.setSpacing(12 if stacked else 16)
        self._box.setStretch(0, 0 if stacked else 1)
        self._box.setAlignment(self.control, Qt.AlignmentFlag.AlignLeft if stacked else
                               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.updateGeometry()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        available = max(40, width - 32)
        hint = self.control.sizeHint()
        control_width = min(available, self.control.maximumWidth(),
                            max(self.control.minimumWidth(), hint.width()))
        text_width = available if width < 480 else max(40, available - control_width - 16)
        title_height = max(self.title.fontMetrics().height(), self.title.heightForWidth(text_width))
        detail_height = 0
        if not self.description.isHidden():
            detail_height = 4 + max(self.description.fontMetrics().height(), self.description.heightForWidth(text_width))
        control_height = max(self.control.minimumHeight(), hint.height())
        content = title_height + detail_height + 12 + control_height if width < 480 else max(title_height + detail_height, control_height)
        return max(64, 32 + content)

    def sizeHint(self):
        return QSize(600, self.heightForWidth(max(40, self.width())))

    def minimumSizeHint(self):
        return QSize(0, self.heightForWidth(max(40, self.width())))

    def resizeEvent(self, event):
        self._set_stacked(event.size().width() < 480)
        super().resizeEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.control and event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.FontChange):
            self.updateGeometry()
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange, QEvent.Type.ParentChange):
            self.refreshPalette()

    def paintEvent(self, event):
        self.refreshPalette()
        palette = _ancestor_palette(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(palette['CARD']))
        painter.setPen(QPen(QColor(palette['STROKE']), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 4, 4)
        painter.end()


__all__ = ['fluent_palette', 'FluentNavigationDelegate', 'SettingsRow',
           'NAV_ICON_ROLE', 'NAV_GLYPHS']
