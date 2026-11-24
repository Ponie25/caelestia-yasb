"""Windows-native chrome and Fluent settings layout helpers for Qt."""
import ctypes
from ctypes import wintypes
from PyQt6.QtCore import Qt,QPointF,QRectF
from PyQt6.QtGui import QColor,QPainter,QPainterPath,QPen
from PyQt6.QtWidgets import QLabel,QToolButton,QVBoxLayout,QWidget,QSizePolicy
from core.utils.settings_fluent import SettingsRow
from core.utils.ui_motion import Timeline,options,curve
from core.utils.motion_spec import milliseconds


class SettingsForm(QVBoxLayout):
    """A vertical collection of SettingsCard rows with a small QFormLayout API."""
    def __init__(self):
        super().__init__();self.setContentsMargins(0,0,0,0);self.setSpacing(4);self.rows={}
    def addRow(self,label,control=None,description=''):
        if control is None:
            self.addWidget(label);return
        title=label.text() if isinstance(label,QLabel) else str(label)
        if not title:
            self.addWidget(control);return
        row=SettingsRow(title,control,description)
        self.rows[control]=row;self.addWidget(row);control._settings_row=row
    def setRowVisible(self,control,visible):
        if control in self.rows:self.rows[control].setVisible(visible)


class FluentExpander(QToolButton):
    def __init__(self,title,parent=None):
        super().__init__(parent);self.setText(title);self.setCheckable(True)
        self.setAccessibleName(title);self.setAccessibleDescription('Mở rộng hoặc thu gọn các tùy chọn phụ.')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed);self.setFixedHeight(64)
        self._arrow=0.;self._timeline=Timeline(self);self._timeline.valueChanged.connect(self._arrow_frame)
        self.toggled.connect(self._arrow_changed)
    def _arrow_changed(self,checked):
        spec=options(self);self._arrow_start=self._arrow;self._arrow_end=float(checked);self._arrow_curve=curve('spatial',spec)
        self._timeline.start(1.,milliseconds(spec,'section'),spec,0.)
    def _arrow_frame(self,value):
        self._arrow=self._arrow_start+(self._arrow_end-self._arrow_start)*self._arrow_curve.valueForProgress(value);self.update()
    def paintEvent(self,event):
        super().paintEvent(event)
        parent=self
        while parent is not None and not hasattr(parent,'_surface_palette'):parent=parent.parentWidget()
        if parent is None:return
        p=parent._surface_palette;painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color=QColor(p['TEXT'] if self.isEnabled() else p['MUTED']);painter.setPen(color)
        painter.fillRect(self.rect().adjusted(2,2,-2,-2),QColor(p['CARD']))
        painter.setFont(self.font());painter.drawText(self.rect().adjusted(16,0,-48,0),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,self.text())
        cx=self.width()-26;cy=self.height()/2
        painter.translate(cx,cy);painter.rotate(-180*self._arrow)
        path=QPainterPath(QPointF(-4,-2));path.lineTo(0,2);path.lineTo(4,-2)
        painter.setPen(QPen(color,1.4,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));painter.drawPath(path);painter.resetTransform()
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor(p['FOCUS']),2));painter.drawRoundedRect(QRectF(self.rect()).adjusted(2,2,-2,-2),3,3)
        painter.end()


def apply_native_caption(widget,palette):
    """Let Windows own caption buttons, snap UI, system menu and resize borders."""
    if not widget.isVisible():return
    try:
        api=ctypes.windll.dwmapi;hwnd=wintypes.HWND(int(widget.winId()))
        dark=ctypes.c_int(1 if QColor(palette['WINDOW']).lightness()<128 else 0)
        api.DwmSetWindowAttribute(hwnd,20,ctypes.byref(dark),ctypes.sizeof(dark))
        # DWORD COLORREF uses 0x00BBGGRR. Contrast mode delegates caption colors
        # to the OS rather than forcing application colors.
        for attribute,role in ((35,'WINDOW'),(36,'TEXT')):
            color=QColor(palette[role])
            value=ctypes.c_uint32(0xffffffff if palette.get('HIGH_CONTRAST') else color.red()|(color.green()<<8)|(color.blue()<<16))
            api.DwmSetWindowAttribute(hwnd,attribute,ctypes.byref(value),ctypes.sizeof(value))
    except (OSError,AttributeError,ValueError):pass


def stylesheet(p):
    return f'''
QDialog#BarSettings {{background:{p['WINDOW']};color:{p['TEXT']};}}
#BarSettings QWidget {{font-family:"Segoe UI Variable","Segoe UI";font-size:14px;font-weight:400;color:{p['TEXT']};}}
#BarSettings QLabel[role="page-title"] {{font-size:28px;font-weight:600;margin-bottom:4px;}}
#BarSettings QLabel[role="nav-title"] {{font-size:20px;font-weight:600;}}
#BarSettings QLabel[role="section"],#BarSettings QLabel[role="card-title"] {{font-size:14px;font-weight:600;}}
#BarSettings QLabel[role="muted"] {{color:{p['TEXT_SECONDARY']};font-size:12px;}}
#BarSettings QScrollArea,#BarSettings QStackedWidget,#BarSettings QScrollArea>QWidget>QWidget {{background:transparent;border:none;}}
#BarSettings QListWidget#Navigation {{background:transparent;border:none;padding:0;outline:0;}}
#BarSettings QFrame#CommandBar {{background:{p['WINDOW']};border-top:1px solid {p['SURFACE2']};}}
#BarSettings QFrame#SettingsSection {{background:transparent;border:none;}}
#BarSettings QWidget#SettingsRow {{background:{p['CARD']};border:1px solid {p['SURFACE2']};border-radius:4px;}}
#BarSettings QWidget#SettingsRow QLabel {{background:transparent;border:none;}}
#BarSettings QToolButton#SectionDisclosure {{background:{p['CARD']};border:1px solid {p['SURFACE2']};border-radius:4px;text-align:left;padding:16px;}}
#BarSettings QListWidget,#BarSettings QTreeWidget,#BarSettings QPlainTextEdit {{background:{p['CARD']};border:1px solid {p['SURFACE2']};border-radius:4px;padding:8px;selection-background-color:{p['NAV_SELECTED']};}}
#BarSettings QTreeWidget::item {{padding:6px 4px;}}
#BarSettings QListWidget#SearchResults {{padding:8px;}}
#BarSettings QListWidget#SearchResults::item {{padding:8px 12px;border-radius:6px;}}
#BarSettings QListWidget#SearchResults::item:selected {{background:{p['NAV_SELECTED']};color:{p['TEXT']};}}
#BarSettings QHeaderView::section {{background:{p['CARD']};color:{p['TEXT']};padding:8px;border:none;border-bottom:1px solid {p['SURFACE2']};}}
#BarSettings QPushButton {{background:{p['CONTROL']};color:{p['CONTROL_TEXT']};border:1px solid {p['SURFACE2']};border-radius:4px;padding:5px 12px;min-height:20px;}}
#BarSettings QPushButton:hover {{background:{p['SURFACE']};}}
#BarSettings QPushButton:pressed {{background:{p['NAV_SELECTED']};}}
#BarSettings QPushButton[motion-preset="true"]:checked {{background:{p['ACCENT']};color:{p['ACCENT_TEXT']};border-color:{p['ACCENT']};}}
#BarSettings QPushButton:disabled {{color:{p['DISABLED']};background:{p['CARD']};}}
#BarSettings QPushButton[theme-card="true"] {{min-height:78px;max-height:78px;padding:0;}}
#BarSettings QRadioButton[theme-card="true"] {{min-height:78px;max-height:78px;padding:0;}}
#BarSettings QPlainTextEdit {{font-family:"Cascadia Code","Consolas";font-size:13px;}}
#BarSettings QPushButton#Primary {{background:{p['MAUVE']};color:{p['ON_ACCENT']};border-color:{p['MAUVE']};font-weight:600;}}
#BarSettings QPushButton#Primary:disabled {{background:{p['CARD']};color:{p['DISABLED']};border-color:{p['SURFACE2']};}}
#BarSettings QLineEdit,#BarSettings QComboBox,#BarSettings QSpinBox,#BarSettings QDoubleSpinBox {{background:{p['CONTROL']};color:{p['CONTROL_TEXT']};border:1px solid {p['SURFACE2']};border-bottom-color:{p['OVERLAY']};border-radius:4px;padding:5px 8px;min-height:20px;selection-background-color:{p['NAV_SELECTED']};}}
#BarSettings QComboBox {{padding-right:28px;}}
#BarSettings QComboBox::drop-down {{border:none;width:28px;}}
#BarSettings QComboBox QAbstractItemView {{background:{p['CARD']};color:{p['TEXT']};border:1px solid {p['SURFACE2']};selection-background-color:{p['NAV_SELECTED']};}}
#BarSettings QLineEdit:focus,#BarSettings QComboBox:focus,#BarSettings QSpinBox:focus,#BarSettings QDoubleSpinBox:focus {{border-bottom:2px solid {p['MAUVE']};}}
#BarSettings QPushButton:focus {{border:2px solid {p['FOCUS']};}}
#BarSettings QLineEdit:disabled,#BarSettings QComboBox:disabled,#BarSettings QSpinBox:disabled,#BarSettings QDoubleSpinBox:disabled {{color:{p['DISABLED']};background:{p['CARD']};border-color:{p['SURFACE2']};}}
#BarSettings QSpinBox::up-button,#BarSettings QDoubleSpinBox::up-button {{subcontrol-origin:border;subcontrol-position:top right;width:24px;background:transparent;border:none;}}
#BarSettings QSpinBox::down-button,#BarSettings QDoubleSpinBox::down-button {{subcontrol-origin:border;subcontrol-position:bottom right;width:24px;background:transparent;border:none;}}
#BarSettings QSpinBox::up-arrow,#BarSettings QSpinBox::down-arrow,#BarSettings QDoubleSpinBox::up-arrow,#BarSettings QDoubleSpinBox::down-arrow {{image:none;width:0;height:0;}}
#BarSettings QTabWidget::pane {{border:1px solid {p['SURFACE2']};border-radius:4px;}}
#BarSettings QTabBar::tab {{background:{p['WINDOW']};padding:10px 16px;border-bottom:2px solid transparent;}}
#BarSettings QTabBar::tab:selected {{background:{p['CARD']};border-bottom-color:{p['MAUVE']};}}
#BarSettings QSlider::groove:horizontal {{height:4px;background:{p['SURFACE2']};border-radius:2px;}}
#BarSettings QSlider::sub-page:horizontal {{background:{p['MAUVE']};border-radius:2px;}}
#BarSettings QSlider::handle:horizontal {{background:{p['MAUVE']};border:3px solid {p['CONTROL']};width:12px;margin:-6px 0;border-radius:8px;}}
#BarSettings QSlider::sub-page:horizontal:disabled,#BarSettings QSlider::handle:horizontal:disabled {{background:{p['DISABLED']};}}
#BarSettings QScrollBar:vertical {{background:transparent;width:12px;}}
#BarSettings QScrollBar::handle:vertical {{background:{p['OVERLAY']};min-height:32px;border-radius:3px;margin:2px 3px;}}
#BarSettings QScrollBar::add-line:vertical,#BarSettings QScrollBar::sub-line:vertical {{height:0;}}
'''
