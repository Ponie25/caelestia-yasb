"""Compact, accessible Qt controls shared by the native bar Settings window.

Only painting is customized. Check state, popup handling, keyboard navigation,
signals and accessibility continue to be supplied by the native Qt widgets.
Colors are resolved at paint time from the nearest ancestor's
``_surface_palette`` so changing theme does not require rebuilding controls.
"""
from core.utils.ui_motion import options,curve
from core.utils.motion_spec import milliseconds
from PyQt6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QAbstractSpinBox, QCheckBox, QComboBox, QDoubleSpinBox, QFontComboBox, QSizePolicy, QSpinBox, QStyle, QStyleOptionComboBox, QStyleOptionSpinBox, QWidget


_FALLBACK = {
    'BASE': '#1e1e2e', 'SURFACE': '#313244', 'SURFACE2': '#45475a',
    'OVERLAY': '#6c7086', 'MUTED': '#a6adc8', 'TEXT': '#cdd6f4',
    'MAUVE': '#cba6f7',
}


def _colors(widget):
    parent = widget
    while parent is not None:
        palette = getattr(parent, '_surface_palette', None)
        if isinstance(palette, dict):
            colors={key: _valid_color(palette.get(key), default) for key, default in _FALLBACK.items()}
            colors['ON_ACCENT']=_valid_color(palette.get('ACCENT_TEXT'),_ink(colors['MAUVE']))
            colors['CONTROL_TEXT']=_valid_color(palette.get('CONTROL_TEXT'),colors['TEXT'])
            return colors
        parent = parent.parentWidget()
    colors={key: QColor(value) for key, value in _FALLBACK.items()};colors['ON_ACCENT']=_ink(colors['MAUVE']);colors['CONTROL_TEXT']=colors['TEXT'];return colors


def _valid_color(value, default):
    color = QColor(value) if isinstance(value, (str, QColor)) else QColor()
    return color if color.isValid() else QColor(default)


def _mix(first, second, amount):
    a, b = first.getRgbF(), second.getRgbF()
    return QColor.fromRgbF(*(x + (y - x) * amount for x, y in zip(a, b)))


def _ink(background):
    def linear(channel):
        return channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4
    luminance = sum(weight * linear(channel) for weight, channel in
                    zip((.2126, .7152, .0722), background.getRgbF()[:3]))
    return QColor('#14131a' if luminance > .179 else '#ffffff')


class ToggleSwitch(QCheckBox):
    """44 px switch retaining the complete QCheckBox API and accessible role.

    Optional text is supported. The animation runs only during a visible state
    change. ``setAnimationEnabled(False)`` supports the Settings motion option.
    """
    def __init__(self, text='', parent=None):
        if isinstance(text, QWidget) and parent is None:
            parent, text = text, ''
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(28)
        self._progress = 1.0 if self.isChecked() else 0.0
        self._animate_changes = True
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(125)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._frame)
        self.stateChanged.connect(self._state_changed)

    def sizeHint(self):
        text_width = self.fontMetrics().horizontalAdvance(self.text()) + 10 if self.text() else 0
        return QSize(44 + text_width, 28)

    def minimumSizeHint(self):
        return self.sizeHint()

    def setAnimationEnabled(self, enabled):
        self._animate_changes = bool(enabled)
        if not enabled:
            self._animation.stop()
            self._progress = self._target()
            self.update()

    def _target(self):
        state = self.checkState()
        return .5 if state == Qt.CheckState.PartiallyChecked else 1.0 if state == Qt.CheckState.Checked else 0.0

    def _state_changed(self, _state):
        self._animation.stop()
        target = self._target()
        if not self._animate_changes or not self.isVisible():
            self._progress = target
            self.update()
            return
        spec=options(self);self._animation.setDuration(milliseconds(spec,'control'));self._animation.setEasingCurve(curve('fast',spec))
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(target)
        self._animation.start()

    def _frame(self, value):
        self._progress = float(value)
        self.update()

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        colors = _colors(self)
        enabled = self.isEnabled()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        left = self.width() - 42.0 if rtl else 2.0
        track = QRectF(left, (self.height() - 22.0) / 2, 40, 22)
        progress = min(1.0, max(0.0, self._progress))
        accent = colors['MAUVE'] if enabled else _mix(colors['SURFACE2'], colors['MUTED'], .22)
        off = colors['SURFACE2'] if enabled else _mix(colors['BASE'], colors['SURFACE2'], .65)
        fill = _mix(off, accent, progress)
        edge = _mix(colors['OVERLAY'], accent, progress)
        if not enabled:
            edge = colors['SURFACE2']
        if self.underMouse() and enabled:
            edge = colors['TEXT'] if progress < .5 else accent.lighter(115)
        painter.setBrush(fill)
        painter.setPen(QPen(edge, 1))
        painter.drawRoundedRect(track, 11, 11)

        thumb = _mix(colors['TEXT'], colors['ON_ACCENT'], progress)
        if not enabled:
            thumb = colors['MUTED']
        position = 1.0 - progress if rtl else progress
        center = QPointF(track.left() + 11 + 18 * position, track.center().y())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(thumb)
        painter.drawEllipse(center, 8, 8)

        if self.checkState() == Qt.CheckState.PartiallyChecked:
            painter.setPen(QPen(_ink(thumb), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(center + QPointF(-3, 0), center + QPointF(3, 0))
        if self.hasFocus() and enabled:
            focus = QColor(colors['MAUVE'])
            focus.setAlpha(185)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(focus, 1.4))
            painter.drawRoundedRect(track.adjusted(-2.2, -2.2, 2.2, 2.2), 13, 13)
        if self.text():
            text_rect = QRectF(0, 0, self.width() - 54, self.height()) if rtl else QRectF(54, 0, self.width() - 54, self.height())
            painter.setPen(colors['TEXT'] if enabled else colors['MUTED'])
            alignment = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
            painter.drawText(text_rect, int(alignment | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextShowMnemonic), self.text())
        painter.end()


class _ChevronMixin:
    """Paint only the arrow/focus; leave native combo interactions untouched."""
    def _init_chevron(self):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        editor = self.lineEdit() if self.isEditable() else None
        if editor is not None:
            editor.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.EnabledChange):
            self.update()
        return super().eventFilter(watched, event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def wheelEvent(self,event):
        if self.hasFocus() or self.isEditable() and self.lineEdit().hasFocus():super().wheelEvent(event)
        else:event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        colors = _colors(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        arrow = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                            QStyle.SubControl.SC_ComboBoxArrow, self)
        if arrow.width() < 8:
            arrow = self.rect().adjusted(self.width() - 25, 1, -1, -1)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Cover any platform-specific arrow without painting over the field edge.
        cover = QRectF(arrow).intersected(QRectF(self.rect()).adjusted(3, 3, -3, -3))
        painter.fillRect(cover, colors['BASE'])
        center = QRectF(arrow).center()
        path = QPainterPath(QPointF(center.x() - 3.5, center.y() - 1.7))
        path.lineTo(center.x(), center.y() + 1.8)
        path.lineTo(center.x() + 3.5, center.y() - 1.7)
        painter.setPen(QPen(colors['CONTROL_TEXT'] if self.isEnabled() else colors['MUTED'], 1.5,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        editor = self.lineEdit() if self.isEditable() else None
        if self.isEnabled() and (self.hasFocus() or editor is not None and editor.hasFocus()):
            focus = QColor(colors['MAUVE'])
            focus.setAlpha(185)
            painter.setPen(QPen(focus, 1.2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(.8, .8, -.8, -.8), 6, 6)
        painter.end()


class ChevronComboBox(_ChevronMixin, QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_chevron()


class ChevronFontComboBox(_ChevronMixin, QFontComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_chevron()


class _StepperMixin:
    """Replace only platform arrow painting; Qt still owns editing and stepping.

    Give ``QAbstractSpinBox::up-button`` and ``::down-button`` a width of 24 px
    in the dialog stylesheet for a comfortable target. No custom hit handling is
    used: the drawn buttons exactly follow Qt's actual subcontrol rectangles.
    """
    def _init_stepper(self):
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.lineEdit().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.EnabledChange):
            self.update()
        return super().eventFilter(watched, event)

    def wheelEvent(self,event):
        if self.hasFocus() or self.lineEdit().hasFocus():super().wheelEvent(event)
        else:event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        colors = _colors(self)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for subcontrol, flag, direction in (
            (QStyle.SubControl.SC_SpinBoxUp, QAbstractSpinBox.StepEnabledFlag.StepUpEnabled, -1),
            (QStyle.SubControl.SC_SpinBoxDown, QAbstractSpinBox.StepEnabledFlag.StepDownEnabled, 1),
        ):
            rect = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, subcontrol, self)
            if rect.isEmpty():
                continue
            cover = QRectF(rect).intersected(QRectF(self.rect()).adjusted(2, 2, -2, -2))
            painter.fillRect(cover, colors['BASE'])
            enabled = self.isEnabled() and not self.isReadOnly() and bool(self.stepEnabled() & flag)
            color = QColor(colors['CONTROL_TEXT'] if enabled else colors['MUTED'])
            if not enabled:
                color.setAlpha(120)
            center = QRectF(rect).center()
            path = QPainterPath(QPointF(center.x() - 3, center.y() - 1.5 * direction))
            path.lineTo(center.x(), center.y() + 1.5 * direction)
            path.lineTo(center.x() + 3, center.y() - 1.5 * direction)
            painter.setPen(QPen(color, 1.35, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        if self.isEnabled() and (self.hasFocus() or self.lineEdit().hasFocus()):
            focus = QColor(colors['MAUVE'])
            focus.setAlpha(185)
            painter.setPen(QPen(focus, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(.8, .8, -.8, -.8), 6, 6)
        painter.end()


class StepperSpinBox(_StepperMixin, QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_stepper()


class StepperDoubleSpinBox(_StepperMixin, QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_stepper()


class PendingCheckBox(QCheckBox):
    """A checkbox for changes that require an explicit Apply command."""
    def __init__(self,parent=None):
        super().__init__(parent);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(28,28);self.setCursor(Qt.CursorShape.PointingHandCursor)
    def hitButton(self,point):return self.rect().contains(point)
    def paintEvent(self,event):
        colors=_colors(self);painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box=QRectF(4,4,20,20);enabled=self.isEnabled()
        color=colors['MAUVE'] if self.isChecked() else colors['CONTROL_TEXT']
        painter.setPen(QPen(color if enabled else colors['MUTED'],1.2))
        painter.setBrush(colors['MAUVE'] if self.isChecked() and enabled else colors['BASE']);painter.drawRoundedRect(box,4,4)
        if self.isChecked():
            check=QPainterPath(QPointF(8,14));check.lineTo(12,18);check.lineTo(20,10)
            painter.setPen(QPen(colors['ON_ACCENT'] if enabled else colors['MUTED'],1.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));painter.drawPath(check)
        if self.hasFocus():
            painter.setPen(QPen(colors['TEXT'],1.3));painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawRoundedRect(box.adjusted(-3,-3,3,3),5,5)
        painter.end()

__all__ = ['PendingCheckBox','ToggleSwitch', 'ChevronComboBox', 'ChevronFontComboBox',
           'StepperSpinBox', 'StepperDoubleSpinBox']
