"""Native, on-demand settings window for the existing YASB bar."""
from copy import deepcopy
from datetime import datetime
import html
from importlib import import_module
import json
import logging
from pathlib import Path

import yaml
from PyQt6.QtCore import Qt, QEvent, QTimer, QPoint, QPointF, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette, QPainter, QPainterPath, QPen, QPixmap, QIcon, QLinearGradient,QKeySequence,QShortcut
from PyQt6.QtWidgets import (
    QApplication, QRadioButton, QAbstractItemView, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFontComboBox, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QStyledItemDelegate, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,QSlider,
)
from core.utils.theme_tokens import effective_palette,glass_alpha,is_light,on_accent
from core.utils.settings_controls import ToggleSwitch,ChevronComboBox,ChevronFontComboBox,StepperSpinBox,StepperDoubleSpinBox
from core.utils.settings_drafts import SettingsDraftMixin
from core.utils.settings_immediate import ImmediateSettingsMixin
from core.utils.settings_fluent import fluent_palette,FluentNavigationDelegate
from core.utils.settings_window import SettingsForm,FluentExpander,apply_native_caption,stylesheet
from core.utils.settings_controls import PendingCheckBox
from core.utils.settings_navigation import SettingsSearch,StatusLabel,save_feedback
from core.utils.ui_motion import PageOverlay,SectionReveal,SmoothScroll,options,duration
QComboBox=ChevronComboBox
QSpinBox=StepperSpinBox
from core.utils.bar_preferences import (
    DEFAULTS, atomic_write, compose_styles, create_snapshot, load_preferences,
    restore_snapshot, validate_config, validate_preferences,
)
from core.utils.bar_preferences import appearance_preset,material_preset,theme_preset

LABELS = {'komorebi_control':'Tên Ponie', 'komorebi_active_layout':'Kiểu chia cửa sổ',
          'komorebi_workspaces':'Không gian làm việc', 'active_window':'Ứng dụng đang mở',
          'bar_divider':'Dấu ngăn cách |', 'raycast_search':'Tìm kiếm ứng dụng',
          'clock':'Ngày và giờ', 'control_center':'Bảng điều khiển'}


class ThemeCard(QRadioButton):
    def __init__(self,label,palette,parent=None):
        super().__init__(label,parent)
        self._palette=palette
        self.setProperty('theme-card',True)
        self.setCheckable(True);self.setMinimumHeight(88)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def hitButton(self,point):
        return self.rect().contains(point)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        p=self._palette;preview=self._palette
        parent=self.parentWidget()
        while parent is not None and not hasattr(parent,'_surface_palette'):parent=parent.parentWidget()
        if parent is not None and parent._surface_palette.get('HIGH_CONTRAST'):p=parent._surface_palette
        rect=QRectF(self.rect()).adjusted(1,1,-1,-1)
        painter.setBrush(QColor(p['CARD'] if p.get('HIGH_CONTRAST') else p['SURFACE'] if self.isDown() else p['BASE']))
        painter.setPen(QPen(QColor(p['MAUVE'] if self.isChecked() else p['SURFACE2']),2 if self.isChecked() else 1))
        painter.drawRoundedRect(rect,10,10)
        font=QFont('Segoe UI');font.setPixelSize(14);font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font);painter.setPen(QColor(p['TEXT']))
        painter.drawText(self.rect().adjusted(14,10,-30,-34),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter|Qt.TextFlag.TextWordWrap,self.text())
        samples=('TEXT','MAUVE','PINK','SURFACE2','MANTLE')
        sample_width=max(12,min(28,(self.width()-44)/len(samples)))
        painter.setPen(Qt.PenStyle.NoPen)
        for index,key in enumerate(samples):
            painter.setBrush(QColor(preview[key]));painter.drawRoundedRect(QRectF(14+index*(sample_width+4),self.height()-25,sample_width,7),3,3)
        if self.isChecked():
            painter.setBrush(QColor(p['MAUVE']));painter.drawEllipse(QPointF(self.width()-20,20),8,8)
            check=QPainterPath(QPointF(self.width()-23.5,20));check.lineTo(self.width()-21,22.5);check.lineTo(self.width()-16.5,17.5)
            painter.setPen(QPen(QColor(p.get('ACCENT_TEXT',on_accent(p['MAUVE']))),1.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));painter.drawPath(check)
        if self.hasFocus():
            painter.setPen(QPen(QColor(p['TEXT']),2));painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawRoundedRect(rect.adjusted(3,3,-3,-3),8,8)
        painter.end()


class ColorButton(QPushButton):
    changed=pyqtSignal(str)
    def __init__(self, value, parent=None):
        super().__init__(parent)
        self.value=value
        self.setMaximumWidth(164)
        self.clicked.connect(self.choose)
        self.refresh()

    def refresh(self):
        self.display_color(self.value)

    def display_color(self,value):
        if getattr(self,'_displayed_color',None)==value and self.text()=='Chọn màu':return
        self._displayed_color=value
        self.setText('Chọn màu');self.setToolTip('Màu hiện tại: '+value.upper())
        ratio=self.devicePixelRatioF();pixmap=QPixmap(round(18*ratio),round(18*ratio));pixmap.setDevicePixelRatio(ratio);pixmap.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pixmap);painter.setRenderHint(QPainter.RenderHint.Antialiasing);painter.setBrush(QColor(value));painter.setPen(QPen(QColor('#777777'),.7));painter.drawRoundedRect(QRectF(1,1,16,16),4,4);painter.end()
        swatch=QIcon();swatch.addPixmap(pixmap,QIcon.Mode.Normal);swatch.addPixmap(pixmap,QIcon.Mode.Disabled)
        self.setIcon(swatch);self.setIconSize(QSize(18,18))
        self.setStyleSheet('QPushButton {text-align:left;padding:6px 10px;}')

    def choose(self):
        color=QColorDialog.getColor(QColor(self.value),self,'Chọn màu')
        if color.isValid():self.value=color.name();self.refresh();self.changed.emit(self.value)


class PercentSpinBox(StepperDoubleSpinBox):
    def textFromValue(self,value):
        return self.locale().toString(value,'f',3).rstrip('0').rstrip(self.locale().decimalPoint())


class PercentControl(QWidget):
    valueChanged=pyqtSignal(float)
    def __init__(self,value,parent=None):
        super().__init__(parent)
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0)
        self.slider=QSlider(Qt.Orientation.Horizontal);self.slider.setRange(0,100)
        self.spin=PercentSpinBox();self.spin.setRange(0,100);self.spin.setDecimals(3);self.spin.setSuffix(' %');self.spin.setSingleStep(1);self.spin.setFixedWidth(112)
        row.addWidget(self.slider,1);row.addWidget(self.spin)
        self.slider.valueChanged.connect(lambda value:self.spin.setValue(value))
        self.spin.valueChanged.connect(self._edited);self.setValue(value)
    def _edited(self,value):
        self._value=value/100
        self.slider.blockSignals(True);self.slider.setValue(round(value));self.slider.blockSignals(False)
        self.valueChanged.emit(self._value)
    def setValue(self,value):
        self._value=float(value);self.spin.blockSignals(True);self.slider.blockSignals(True)
        self.spin.setValue(value*100);self.slider.setValue(round(value*100))
        self.spin.blockSignals(False);self.slider.blockSignals(False)
    def value(self):return self._value


class BarSurfacePreview(QWidget):
    def __init__(self,dialog):
        super().__init__();self.dialog=dialog;self.setMinimumHeight(115)
        self.setAccessibleName('Xem trước nền thanh bar theo màu hình nền desktop')
    def paintEvent(self,event):
        from core.utils.bar_surface import surface_spec,rgba,wallpaper_colors
        try:
            preferences=self.dialog._collect_preferences();palette=self.dialog._preview_palette(preferences)
            a=preferences['appearance'];s=surface_spec(preferences,palette)
        except (AttributeError,KeyError,TypeError):return
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds=QRectF(self.rect()).adjusted(1,1,-1,-1)
        frame=QPainterPath();frame.addRoundedRect(bounds,9,9);p.setClipPath(frame)
        gradient=QLinearGradient(bounds.topLeft(),bounds.topRight())
        walls=wallpaper_colors() or (palette['MANTLE'],)
        for i,color in enumerate(walls):gradient.setColorAt(i/max(1,len(walls)-1),QColor(color))
        if len(walls)==1:gradient.setColorAt(1,QColor(walls[0]))
        p.fillRect(bounds,gradient)
        bar=QRectF(10,25,self.width()-20,48);shape=QPainterPath();shape.addRoundedRect(bar,min(a['radius'],24),min(a['radius'],24))
        if s['enabled']:
            fill=QColor(s['color']);fill.setAlphaF(s['alpha'])
            if s['gradient']:
                fill2=QColor(s['second']);fill2.setAlphaF(s['alpha2'])
                g=QLinearGradient(bar.topLeft(),bar.topRight() if s['direction']=='horizontal' else bar.bottomLeft());g.setColorAt(0,fill);g.setColorAt(1,fill2)
                p.fillPath(shape,g)
            else:p.fillPath(shape,fill)
        elif a['background']=='theme':
            fill=QColor(palette['MANTLE']);fill.setAlphaF(s['theme_alpha']);p.fillPath(shape,fill)
        if a['border']:
            edge=QColor(s['edge']);edge.setAlphaF(a['border_opacity']);p.setPen(QPen(edge,a['border_width']))
            if a['border_edges']=='all':p.drawPath(shape)
            else:
                y=bar.top() if a['border_edges']=='top' else bar.bottom()
                p.drawLine(QPointF(bar.left(),y),QPointF(bar.right(),y))
        font=QFont('Segoe UI');font.setPixelSize(12);font.setWeight(QFont.Weight.DemiBold);p.setFont(font);p.setPen(QColor(s['ink']))
        p.drawText(bar.adjusted(12,0,-12,0),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,'Ponie  |  BSP')
        p.drawText(bar.adjusted(12,0,-12,0),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,'23 Nov · 19:30')
        pill=QRectF(bar.center().x()-62,bar.top()+10,124,28);p.setPen(QPen(QColor(s['edge']),.8));p.setBrush(Qt.BrushStyle.NoBrush);p.drawRoundedRect(pill,14,14)
        p.setPen(QColor(s['ink']));p.drawText(pill,Qt.AlignmentFlag.AlignCenter,'Dynamic Island')
        p.end()


class WidgetList(QListWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMinimumHeight(165)

    def add_widget(self,name):
        item=QListWidgetItem(LABELS.get(name,name.replace('_',' ').title()))
        item.setData(Qt.ItemDataRole.UserRole,name)
        self.addItem(item)

    def names(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]


class ValueDelegate(QStyledItemDelegate):
    def createEditor(self,parent,option,index):
        return super().createEditor(parent,option,index) if index.column()==1 else None


class BarSettingsDialog(ImmediateSettingsMixin,SettingsDraftMixin,QDialog):
    def __init__(self,controller):
        super().__init__(None,Qt.WindowType.Dialog|Qt.WindowType.WindowTitleHint|Qt.WindowType.WindowSystemMenuHint|Qt.WindowType.WindowMinMaxButtonsHint|Qt.WindowType.WindowCloseButtonHint)
        self.controller=controller;self.root=controller.root
        self.draft=yaml.safe_load((self.root/'config.yaml').read_bytes());self.preferences=load_preferences(self.root)
        self._disk_baseline=self._disk_state();self.selected_theme=controller.current
        self.bar_name=next(iter(self.draft['bars']));self.widget_name=None;self.widget_loading=False;self._committing=False
        self.setObjectName('BarSettings');self.setWindowTitle('Cài đặt thanh bar · YASB')
        icon=QApplication.instance().windowIcon()
        if icon.isNull():
            import sys
            icon_path=Path(sys.executable).parent/'assets/images/app_icon.png'
            if icon_path.is_file():icon=QIcon(str(icon_path))
        if not icon.isNull():self.setWindowIcon(icon)
        available=self.screen().availableGeometry()
        self.setMinimumSize(min(640,available.width()-32),min(500,available.height()-32))
        self.resize(min(1120,available.width()-48),min(820,available.height()-48));self.controls={}
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        body=QHBoxLayout();body.setContentsMargins(12,16,24,0);body.setSpacing(24)
        self.nav_pane=QWidget();navigation=QVBoxLayout(self.nav_pane);navigation.setContentsMargins(0,0,0,0);navigation.setSpacing(16)
        self.nav_title=QLabel('Thanh bar');self.nav_title.setProperty('role','nav-title');self.nav_title.setContentsMargins(12,8,0,8);navigation.addWidget(self.nav_title)
        self.nav=QListWidget();self.nav.setObjectName('Navigation');self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.nav.setItemDelegate(FluentNavigationDelegate(self.nav))
        self.nav.addItems(['Giao diện','Nền và viền','Bố cục','Từng mục trên bar','Island và Launcher','Viền cửa sổ','Sao lưu','Chỉnh bằng mã'])
        for index in range(self.nav.count()):self.nav.item(index).setToolTip(self.nav.item(index).text())
        navigation.addWidget(self.nav,1)
        self.advanced_button=QPushButton('Thiết lập nâng cao');self.advanced_button.setCheckable(True);self.advanced_button.setAccessibleName('Thiết lập nâng cao');self.advanced_button.setToolTip('Mở các tùy chọn chi tiết; bạn không cần dùng phần này để đổi giao diện.')
        self.advanced_button.toggled.connect(self._advanced_navigation);navigation.addWidget(self.advanced_button)
        self._advanced_navigation(False);body.addWidget(self.nav_pane)
        self.main_pane=QWidget();main=QVBoxLayout(self.main_pane);main.setContentsMargins(0,0,0,0);main.setSpacing(14)
        header=QHBoxLayout();self.settings_search=QLineEdit();self.settings_search.setPlaceholderText('Tìm cài đặt…  Ctrl+F');self.settings_search.setAccessibleName('Tìm cài đặt');self.settings_search.setClearButtonEnabled(True)
        self.save_status=QLabel('Tự động lưu');self.save_status.setProperty('role','muted');self.save_status.setMinimumWidth(110);self.save_status.setMaximumWidth(190);self.save_status.setWordWrap(True)
        header.addWidget(self.settings_search,1);header.addWidget(self.save_status);main.addLayout(header)
        self.content_stack=QStackedWidget();self.pages=QStackedWidget();self.content_stack.addWidget(self.pages)
        self.search_results=QListWidget();self.search_results.setObjectName('SearchResults');self.search_results.setAccessibleName('Kết quả tìm cài đặt');self.content_stack.addWidget(self.search_results)
        main.addWidget(self.content_stack,1);body.addWidget(self.main_pane,1);outer.addLayout(body,1)
        self._appearance();self._bar_surface();self._layout();self._widgets();self._island();self._komorebi();self._backups();self._advanced()
        self.page_motion=PageOverlay(self.pages)
        self._wire_preview();self.nav.currentRowChanged.connect(self._page_changed);self.nav.setCurrentRow(0)
        command=QFrame();command.setObjectName('CommandBar');footer=QHBoxLayout(command);footer.setContentsMargins(24,12,24,12);footer.setSpacing(8)
        self.status=StatusLabel('Các cài đặt thông thường được áp dụng ngay.');self.status.changed.connect(lambda text:save_feedback(self,text));self.status.setWordWrap(True);self.status.setProperty('role','muted');footer.addWidget(self.status,1)
        self.manual_actions=QWidget();manual=QHBoxLayout(self.manual_actions);manual.setContentsMargins(0,0,0,0);manual.setSpacing(8)
        self.revert_button=QPushButton('Hoàn tác');self.revert_button.clicked.connect(self.revert_changes);manual.addWidget(self.revert_button)
        self.apply_button=QPushButton('Áp dụng');self.apply_button.setObjectName('Primary');self.apply_button.clicked.connect(self.apply_changes);manual.addWidget(self.apply_button)
        footer.addWidget(self.manual_actions)
        self.cancel_button=QPushButton('Đóng');self.cancel_button.clicked.connect(self._request_close);footer.addWidget(self.cancel_button);self.cancel_button.hide()
        outer.addWidget(command);self.command_bar=command
        self.refresh_style();self._active_page=0
        self.save_shortcut=QShortcut(QKeySequence.StandardKey.Save,self);self.save_shortcut.activated.connect(self.apply_changes)
        self._install_draft_tracking();self._install_immediate_settings()
        hints=QApplication.instance().styleHints()
        if hasattr(hints,'colorSchemeChanged'):hints.colorSchemeChanged.connect(lambda *_:self.refresh_style())
        for button in self.findChildren(QPushButton):button.setAutoDefault(False)
        self.search_controller=SettingsSearch(self)
        self.nav.setFocus();self._adapt_navigation();self.move(available.center()-self.rect().center())


    def refresh_style(self):
        mode=self.preferences.get('settings_window',{}).get('mode','system')
        if ('settings_window','mode') in self.controls:mode=self.controls[('settings_window','mode')][0].currentData()
        p=fluent_palette(effective_palette(self.root,self.controller.current),mode)
        p['ON_ACCENT']=p['ACCENT_TEXT']
        if getattr(self,'_surface_palette',None)==p:return
        self._surface_palette=p
        self.setStyleSheet(stylesheet(p));self.update();self.nav.viewport().update()
        for button in getattr(self,'surface_preset_buttons',{}).values():
            button.setStyleSheet('QPushButton:checked {background:'+p['ACCENT']+';color:'+p['ACCENT_TEXT']+';border-color:'+p['ACCENT']+';}')
        for control,kind in self.controls.values():
            row=getattr(control,'_settings_row',None)
            if row is not None:row.refreshPalette()
        apply_native_caption(self,p)
        if hasattr(self,'accent') and not self.custom_accent.isChecked():
            self.accent.value=effective_palette(self.root,self.controller.current)['MAUVE'];self.accent.refresh()


    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor(self._surface_palette['WINDOW']));painter.end()


    def showEvent(self,event):
        super().showEvent(event);apply_native_caption(self,self._surface_palette)


    def show(self):
        if self.isMinimized():self.showNormal()
        else:super().show()

    def mousePressEvent(self,event):
        super().mousePressEvent(event)


    def mouseDoubleClickEvent(self,event):
        super().mouseDoubleClickEvent(event)


    def closeEvent(self,event):
        event.ignore();self._request_close()

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:
            if self.settings_search.text():self.settings_search.clear()
            else:self._request_close()
            event.accept();return
        super().keyPressEvent(event)

    def _page(self,title,description):
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
        scroll._smooth_scroll=SmoothScroll(scroll)
        content=QWidget();content.setMaximumWidth(1100);layout=QVBoxLayout(content);layout.setContentsMargins(0,8,12,24);layout.setSpacing(16)
        label=QLabel(title);label.setProperty('role','page-title');layout.addWidget(label)
        hint=QLabel(description);hint.setProperty('role','muted');hint.setWordWrap(True);layout.addWidget(hint)
        scroll.setWidget(content);self.pages.addWidget(scroll);return layout


    def _section(self,layout,text,collapsed=False):
        card=QFrame();card.setObjectName('SettingsSection');box=QVBoxLayout(card);box.setContentsMargins(0,0,0,0);box.setSpacing(4)
        body=QWidget();body_layout=QVBoxLayout(body);body_layout.setContentsMargins(0,0,0,0)
        if collapsed:
            title=FluentExpander(text);title.setObjectName('SectionDisclosure');box.addWidget(title);body.hide()
        else:
            title=QLabel(text);title.setProperty('role','section');title.setContentsMargins(0,8,0,4);box.addWidget(title)
        form=SettingsForm();body_layout.addLayout(form);box.addWidget(body);layout.addWidget(card)
        form.section_card=card;form.section_body=body;form.disclosure=title if collapsed else None
        if collapsed:form.reveal=SectionReveal(title,body)
        return form


    def _bind(self,form,label,group,key,kind='number',low=0,high=100,choices=None):
        label=str(label)
        value=self.preferences[group][key]
        if kind=='bool':
            control=ToggleSwitch('Bật' if value else 'Tắt');control.setChecked(value);control.toggled.connect(lambda checked,control=control:control.setText('Bật' if checked else 'Tắt'))
        elif kind=='text':control=QLineEdit(str(value))
        elif kind=='color':control=ColorButton(value)
        elif kind=='font':
            control=ChevronFontComboBox();control.setCurrentFont(QFont(value))
            control.setEditText(value);control.setProperty('requested_family',value)
            control.activated.connect(lambda index,control=control:control.setProperty('requested_family',control.currentText()))
            control.lineEdit().textEdited.connect(lambda text,control=control:control.setProperty('requested_family',text))
        elif kind=='choice':
            control=ChevronComboBox()
            for text,data in choices:control.addItem(text,data)
            if control.findData(value)<0:control.addItem(str(value),value)
            control.setCurrentIndex(control.findData(value))
        elif kind=='decimal':
            control=StepperDoubleSpinBox();control.setDecimals(5 if group=='weather' else 3);control.setRange(low,high);control.setSingleStep(.05);control.setValue(value)
        elif kind=='percent':
            control=PercentControl(value)
            if high<=1:
                control.spin.setRange(low*100,high*100);control.slider.setRange(round(low*100),round(high*100))
        else:
            control=StepperSpinBox();control.setRange(low,high);control.setValue(value)
        if kind in ('number','decimal'):control.setMaximumWidth(168);control.setKeyboardTracking(False)
        elif kind in ('choice','font','text','percent'):control.setMaximumWidth(420)
        control.setAccessibleName(label)
        form.addRow(label,control)
        row=form.rows[control];control._settings_caption=row.title;control._settings_form=form
        hints={('settings_window','mode'):'Chỉ đổi cửa sổ này; không đổi màu của thanh bar.',
               ('appearance','font_family'):'Phông chữ hiển thị trên thanh bar.',
               ('appearance','background'):'Nền trải dài toàn bộ thanh bar.',
               ('animations','enabled'):'Dùng chung cho launcher, Island, các menu và cửa sổ cài đặt.',
               ('launcher','dangerous_actions'):'Ẩn mặc định. Khi bật, các lệnh này vẫn cần xác nhận.',
               ('launcher','wallpaper_directory'):'Để trống để dùng config/wallpapers. Thư viện Wallpaper Engine đang chạy cũng được nhận diện.',
               ('animations','popup_ms'):'Số nhỏ hơn sẽ nhanh hơn. Các hiệu ứng cùng thay đổi theo nhịp này.',
               ('island','speed'):'1 là mặc định. Dưới 1 nhanh hơn, trên 1 chậm hơn; áp dụng cho toàn bộ giao diện.',
               ('island','fps'):'Chọn gần tần số quét màn hình. 60 FPS tiết kiệm hơn, 120 FPS mượt hơn.',
               ('island','enabled'):'Bấm vào Dynamic Island để mở menu.',
               ('island','material'):'Dùng chung cho pill, menu và App launcher.',
               ('island','remember_tab'):'Mở lại tab đã dùng gần nhất.',
               ('island','liquid_contrast'):'Giữ chữ rõ trên hình nền sáng.',
               ('island','liquid_fps'):'Nền đứng yên không cần vẽ lại liên tục.',
               ('komorebi','mode'):'Chỉ thay đổi màu viền; giữ nguyên workspace.'}
        row._description_text=hints.get((group,key),'');row.description.setText(row._description_text);row.description.setVisible(bool(row.description.text()))
        if kind=='percent':
            control.setFocusProxy(control.spin)
            for child in (control.slider,control.spin):child.setAccessibleName(label+' (%)');child.setAccessibleDescription('Giá trị phần trăm; ô số cho phép nhập chính xác.')
        self.controls[(group,key)]=(control,kind)
        return control

    def _appearance(self):
        layout=self._page('Giao diện','Chọn một preset để lấy lại màu, nền và kính mặc định. Chọn lại preset đang dùng cũng khôi phục các giá trị gốc.')
        self.appearance_preview=BarSurfacePreview(self);layout.addWidget(self.appearance_preview)
        grid=QGridLayout();grid.setSpacing(12);self.theme_group=QButtonGroup(self);self.theme_buttons={}
        for index,(name,label) in enumerate(self.controller.theme_labels.items()):
            palette=json.loads((self.root/'theme-profiles'/name/'palette.json').read_text())
            button=ThemeCard(label,palette);button.setChecked(name==self.selected_theme)
            button.setToolTip({'catppuccin':'Catppuccin · tím hồng','everforest':'Everforest · xanh lá','wallpaper':'Tự tạo bảng màu từ hình nền hiện tại; giữ tông sáng/tối bạn chọn.'}.get(name,label))
            button.clicked.connect(lambda checked=False,name=name:self._choose_theme(name))
            self.theme_group.addButton(button);self.theme_buttons[name]=button;grid.addWidget(button,index//3,index%3)
        layout.addLayout(grid)
        form=self._section(layout,'Màu chữ và icon')
        self._bind(form,'Cách chọn màu','appearance','foreground','choice',choices=[
            ('Tự động theo nền thanh bar','auto'),('Theo bộ màu','theme'),
            ('Màu riêng · tự điều chỉnh độ rõ','tint'),('Màu riêng · giữ nguyên','custom')])
        self._bind(form,'Màu chữ bạn chọn','appearance','text_color','color')
        choices=QWidget();grid=QGridLayout(choices);grid.setContentsMargins(0,0,0,0);grid.setSpacing(8)
        self.text_color_presets={}
        for index,(name,label,color) in enumerate([
            ('black','Đen','#000000'),('white','Trắng','#ffffff'),('accent','Màu nhấn',None),
            ('purple','Tím','#cba6f7'),('pink','Hồng','#f5a8d6'),('red','Đỏ','#ef667a'),
            ('green','Xanh lá','#a7c080'),('blue','Xanh dương','#89b4fa'),('orange','Cam','#fab387')]):
            button=QPushButton(label);button.setAccessibleName('Màu chữ '+label)
            button.setToolTip('Giữ nguyên màu đã chọn.' if name in ('black','white') else 'Giữ sắc màu và tự điều chỉnh độ sáng/tối cho dễ đọc.')
            button.clicked.connect(lambda checked=False,name=name,color=color:self._text_color_preset(name,color))
            self.text_color_presets[name]=(button,color);grid.addWidget(button,index//3,index%3)
        form.addRow(choices)
        hint=QLabel('Màu riêng tự điều chỉnh độ rõ sẽ giữ sắc tím, hồng, đỏ… và đổi độ đậm theo nền. Chọn Giữ nguyên nếu muốn dùng đúng màu đã chọn.');hint.setWordWrap(True);hint.setProperty('role','muted');form.addRow(hint)
        form=self._section(layout,'Chọn màu riêng',collapsed=True)
        self.custom_accent=ToggleSwitch('Bật' if 'MAUVE' in self.preferences['palette'] else 'Tắt');self.custom_accent.setChecked('MAUVE' in self.preferences['palette'])
        self.custom_accent.toggled.connect(lambda checked:self.custom_accent.setText('Bật' if checked else 'Tắt'))
        current=json.loads((self.root/'theme-profiles'/self.controller.current/'palette.json').read_text())
        self.accent=ColorButton(self.preferences['palette'].get('MAUVE',current['MAUVE']))
        form.addRow('Dùng màu nhấn riêng',self.custom_accent,'Đổi màu nổi bật mà vẫn giữ bộ màu đã chọn.')
        form.addRow('Màu bạn chọn',self.accent)
        form.rows[self.accent].setControlEnabled(self.custom_accent.isChecked(),'Bật Dùng màu nhấn riêng để chọn màu.')
        self.custom_accent.toggled.connect(lambda checked,row=form.rows[self.accent]:row.setControlEnabled(checked,'Bật Dùng màu nhấn riêng để chọn màu.'))
        form=self._section(layout,'Chữ và khoảng cách',collapsed=True)
        self._bind(form,'Kiểu chữ','appearance','font_family','font')
        self._bind(form,'Cỡ chữ','appearance','font_size',low=8,high=24)
        self._bind(form,'Độ đậm của chữ','appearance','font_weight','choice',choices=[('Bình thường',400),('Vừa',500),('Đậm vừa',600),('Đậm',700)])
        self._bind(form,'Khoảng cách giữa các mục','appearance','spacing',low=0,high=32)
        self._bind(form,'Khoảng cách hai đầu thanh bar','appearance','padding',low=0,high=60)
        form=self._section(layout,'Hiệu ứng chuyển động',collapsed=True)
        self._bind(form,'Chuyển động của giao diện','animations','enabled','bool')
        motion_choices=QWidget();row=QHBoxLayout(motion_choices);row.setContentsMargins(0,0,0,0);self.motion_presets={}
        for label,value in [('Nhanh',165),('Cân bằng',220),('Thư thái',300)]:
            button=QPushButton(label);button.setCheckable(True);button.setProperty('motion-preset',True);button.clicked.connect(lambda checked=False,value=value:self._motion_preset(value));row.addWidget(button);self.motion_presets[value]=button
        form.addRow(motion_choices)
        self.motion_preview_button=QPushButton('Xem thử chuyển động');self.motion_preview_button.clicked.connect(self._preview_motion);form.addRow(self.motion_preview_button)
        self._bind(form,'Nhịp chuyển động','animations','popup_ms',low=0,high=600)
        self.controls[('animations','popup_ms')][0].setSuffix(' ms')
        self._bind(form,'Điều chỉnh thêm thời gian','island','speed','decimal',.25,3)
        self._bind(form,'Độ mượt tối đa','island','fps','choice',choices=[(str(x)+' FPS',x) for x in (30,60,90,120,144,165,240)])
        form=self._section(layout,'Giao diện của cửa sổ cài đặt',collapsed=True)
        self._bind(form,'Kiểu sáng/tối','settings_window','mode','choice',choices=[('Theo Windows','system'),('Sáng','light'),('Tối','dark')])
        layout.addStretch()


    def _choose_theme(self,name):
        self.selected_theme=name
        palette=json.loads((self.root/'theme-profiles'/name/'palette.json').read_text())
        self._immediate_begin_loading()
        try:
            self.preferences['palette']={};self.custom_accent.setChecked(False)
            self._set_field('launcher','wallpaper_auto_theme',name=='wallpaper')
            self.accent.value=palette['MAUVE'];self.accent.refresh();self.theme_buttons[name].setChecked(True)
            for group,values in (('appearance',appearance_preset(palette)),('island',material_preset('liquid-soft'))):
                for key,value in values.items():self._set_field(group,key,value)
        finally:self._immediate_end_loading()
        self._refresh_preview();self._queue_immediate_preferences()

    def _motion_preset(self,value):
        self._immediate_begin_loading()
        try:
            self._set_field('animations','popup_ms',value)
            self._set_field('island','speed',1.)
            self._set_field('animations','enabled',True)
        finally:self._immediate_end_loading()
        self._refresh_preview();self._queue_immediate_preferences()

    def _preview_motion(self):
        from core.utils.utilities import PopupWidget
        popup=PopupWidget(self.motion_preview_button,persistent=False)
        popup.setProperty('class','motion-preview');popup.setStyleSheet('QFrame {background:'+self._surface_palette['CARD']+';border-radius:12px;color:'+self._surface_palette['TEXT']+';} QLabel {padding:10px;}')
        box=QVBoxLayout(popup);box.setContentsMargins(18,18,18,18)
        label=QLabel('Cùng chuyển động với launcher');box.addWidget(label)
        hint=QLabel('Menu, bảng điều khiển và các mục cài đặt dùng chung nhịp chuyển động.');hint.setWordWrap(True);box.addWidget(hint)
        close=QPushButton('Đóng');close.clicked.connect(popup.hide_animated);box.addWidget(close)
        popup.resize(360,190);popup.setPosition('right','up',0,8);self._motion_preview=popup;popup.show()

    def _bar_surface(self):
        layout=self._page('Nền và viền','Chọn kiểu nền để chữ dễ đọc hơn trên hình nền. Thay đổi được lưu tự động.')
        self.surface_preview=BarSurfacePreview(self);layout.addWidget(self.surface_preview)
        self.contrast_hint=QLabel();self.contrast_hint.setWordWrap(True);self.contrast_hint.setProperty('role','muted');layout.addWidget(self.contrast_hint)
        title=QLabel('Chọn nhanh một kiểu nền');title.setProperty('role','section');layout.addWidget(title)
        presets=QHBoxLayout();self.surface_preset_buttons={}
        for text,name in [('Trong suốt','clear'),('Mờ nhẹ','soft'),('Mờ rõ','balanced'),('Nền đặc','solid')]:
            button=QPushButton(text);button.setCheckable(True);button.clicked.connect(lambda checked=False,name=name:self._surface_preset(name));presets.addWidget(button);self.surface_preset_buttons[name]=button
        layout.addLayout(presets)
        self.surface_preset_label=QLabel();self.surface_preset_label.setProperty('role','muted');layout.addWidget(self.surface_preset_label)
        form=self._section(layout,'Điều chỉnh nền đang dùng')
        self._bind(form,'Độ rõ của nền','appearance','background_opacity','percent')
        self._bind(form,'Làm mờ hình nền phía sau','appearance','background_blur','bool')
        self._bind(form,'Màu nền','appearance','background_source','choice',choices=[('Theo bộ màu đã chọn','theme'),('Tự chọn màu','custom')])
        self._bind(form,'Màu bạn chọn','appearance','background_color','color')
        form=self._section(layout,'Chỉnh chi tiết',collapsed=True)
        self._bind(form,'Cách hiển thị nền','appearance','background','choice',choices=[('Theo bộ màu đã chọn','theme'),('Không có nền','transparent'),('Nền mờ','glass'),('Nền màu riêng','custom')])
        self._bind(form,'Dùng hai màu nền','appearance','background_gradient','bool')
        self._bind(form,'Màu nền thứ hai','appearance','background_color2','color')
        self._bind(form,'Độ rõ của màu thứ hai','appearance','background_opacity2','percent')
        self._bind(form,'Hướng chuyển màu','appearance','gradient_direction','choice',choices=[('Từ trên xuống','vertical'),('Từ trái sang phải','horizontal')])
        self._bind(form,'Độ bo tròn góc','appearance','radius',low=0,high=40)
        self._bind(form,'Hiện đường viền','appearance','border','bool')
        self._bind(form,'Màu của đường viền','appearance','border_color_source','choice',choices=[('Theo bộ màu','theme'),('Tự chọn màu','custom')])
        self._bind(form,'Màu viền bạn chọn','appearance','border_color','color')
        self._bind(form,'Độ rõ của đường viền','appearance','border_opacity','percent')
        self._bind(form,'Độ dày của đường viền','appearance','border_width','decimal',.5,8)
        self._bind(form,'Đường viền nằm ở','appearance','border_edges','choice',choices=[('Cả khung','all'),('Chỉ cạnh dưới','bottom'),('Chỉ cạnh trên','top')])
        copy=QPushButton('Dùng màu hiện tại làm màu riêng');copy.clicked.connect(self._copy_surface_colors);form.addRow(copy)
        reset=QPushButton('Dùng lại nền mặc định của bộ màu');reset.clicked.connect(lambda:self._surface_preset('theme'));layout.addWidget(reset)
        layout.addStretch()


    def _set_field(self,group,key,value):
        control,kind=self.controls[(group,key)]
        if kind=='choice':
            index=control.findData(value)
            if index<0:control.addItem(str(value),value);index=control.count()-1
            control.setCurrentIndex(index)
        elif kind=='bool':control.setChecked(value)
        elif kind=='color':control.value=value;control.refresh()
        elif kind=='font':
            control.blockSignals(True);control.setCurrentFont(QFont(value));control.setEditText(value);control.blockSignals(False);control.setProperty('requested_family',value)
        elif kind=='text':control.setText(value)
        else:control.setValue(value)

    def _surface_preset(self,name):
        palette=self._preview_palette(self._collect_preferences())
        self._immediate_begin_loading()
        try:
            for key,value in appearance_preset(palette,name).items():self._set_field('appearance',key,value)
        finally:self._immediate_end_loading()
        self._refresh_preview();self._queue_immediate_preferences()

    def _text_color_preset(self,name,color):
        if color is None:color=self._preview_palette(self._collect_preferences())['MAUVE']
        self._immediate_begin_loading()
        try:
            self._set_field('appearance','text_color',color)
            self._set_field('appearance','foreground','custom' if name in ('black','white') else 'tint')
        finally:self._immediate_end_loading()
        self._refresh_preview();self._queue_immediate_preferences()

    def _material_preset(self,*_):
        name=self.controls[('island','material')][0].currentData()
        self._immediate_begin_loading()
        try:
            for key,value in material_preset(name).items():self._set_field('island',key,value)
        finally:self._immediate_end_loading()
        self._refresh_preview();self._queue_immediate_preferences()

    def _copy_surface_colors(self):
        palette=self._preview_palette(self._collect_preferences())
        self._set_field('appearance','background_color',palette['MANTLE']);self._set_field('appearance','background_color2',palette['BASE'])
        self._set_field('appearance','background_source','custom');self._refresh_preview()

    def _copy_border_colors(self):
        from core.utils.komorebi_theme import colors_for
        settings=self._collect_preferences();settings['komorebi']['mode']='theme'
        colors=colors_for(settings,self._preview_palette(settings))
        for kind,color in colors.items():self._set_field('komorebi',kind.replace('-','_')+'_color',color)
        self._set_field('komorebi','mode','custom');self._refresh_preview()

    def _preview_palette(self,preferences):
        from core.utils.theme_tokens import normalize_palette
        palette=json.loads((self.root/'theme-profiles'/self.selected_theme/'palette.json').read_text(encoding='utf-8'))
        palette.update(preferences['palette']);return normalize_palette(palette)

    def _wire_preview(self):
        for (group,key),(control,kind) in self.controls.items():
            signal=control.toggled if kind=='bool' else control.currentIndexChanged if kind=='choice' else control.changed if kind=='color' else control.valueChanged if kind in ('number','decimal','percent') else None
            if signal is not None:signal.connect(self._refresh_preview)
            if (group,key) in (('appearance','background_source'),('appearance','foreground'),('appearance','border_color_source'),('appearance','background'),('komorebi','mode')):
                control.activated.connect(lambda index,group=group,key=key:self._preset_source(group,key))
        self.custom_accent.toggled.connect(self._refresh_preview);self.accent.changed.connect(self._refresh_preview)
        self.custom_accent.toggled.connect(self._accent_source)
        self._refresh_preview()

    def _accent_source(self,enabled):
        if not enabled:
            self.accent.value=json.loads((self.root/'theme-profiles'/self.selected_theme/'palette.json').read_text())['MAUVE'];self.accent.refresh()

    def _preset_source(self,group,key):
        settings=self._collect_preferences();palette=self._preview_palette(settings);value=settings[group][key];values={}
        if group=='appearance':
            if key=='background_source' and value=='theme':values={'background_color':palette['MANTLE'],'background_color2':palette['BASE']}
            elif key=='border_color_source' and value=='theme':values={'border_color':palette['MAUVE']}
            elif key=='foreground' and value in ('theme','auto'):
                from core.utils.bar_surface import surface_spec
                values={'text_color':surface_spec(settings,palette)['ink']}
            elif key=='background' and value=='theme':values=appearance_preset(palette)
        elif group=='komorebi' and value=='theme':
            from core.utils.komorebi_theme import colors_for
            values={kind.replace('-','_')+'_color':color for kind,color in colors_for(settings,palette).items()}
        if values:
            self._immediate_begin_loading()
            try:
                for field,value in values.items():self._set_field(group,field,value)
            finally:self._immediate_end_loading()
            self._refresh_preview();self._queue_immediate_preferences()

    def _refresh_preview(self,*_):
        if not hasattr(self,'komorebi_status'):return
        from core.utils.bar_surface import surface_spec
        settings=self._collect_preferences();a=settings['appearance'];palette=self._preview_palette(settings)
        filled=a['background'] in ('glass','custom');gradient=filled and a['background_gradient']
        enabled={'background_source':a['background']=='glass','background_color':filled and (a['background']=='custom' or a['background_source']=='custom'),
                 'background_opacity':filled,'background_blur':a['background']=='glass','background_gradient':filled,
                 'background_color2':gradient and (a['background']=='custom' or a['background_source']=='custom'),
                 'background_opacity2':gradient,'gradient_direction':gradient,'text_color':a['foreground'] in ('custom','tint'),
                 'border_color_source':a['border'],'border_color':a['border'] and a['border_color_source']=='custom',
                 'border_width':a['border'],'border_opacity':a['border'],'border_edges':a['border']}
        for key,value in enabled.items():self.controls[('appearance',key)][0].setEnabled(value)
        for key,value in enabled.items():
            control=self.controls[('appearance',key)][0]
            control._settings_caption.setEnabled(value)
            reason='Chọn Mờ nhẹ, Mờ rõ hoặc Nền đặc ở phía trên để điều chỉnh.'
            if key in ('background_color','background_color2') and filled:
                reason='Chọn Tự chọn màu ở mục Màu nền.'
                if key=='background_color2' and not gradient:reason='Bật Dùng hai màu nền trong Chỉnh chi tiết.'
            elif key in ('background_opacity2','gradient_direction') and filled:reason='Bật Dùng hai màu nền trong Chỉnh chi tiết.'
            elif key=='text_color':reason='Chọn Màu riêng ở mục Cách chọn màu để tùy chỉnh.'
            elif key.startswith('border_'):
                reason='Bật Hiện đường viền trong Chỉnh chi tiết.'
                if key=='border_color' and a['border']:reason='Chọn Tự chọn màu ở mục Màu của đường viền.'
            elif key=='background_blur' and a['background']=='custom':reason='Chọn Mờ nhẹ hoặc Mờ rõ để bật hiệu ứng mờ.'
            control._settings_row.setControlEnabled(value,reason)
        spec=surface_spec(settings,palette)
        for name,(button,color) in getattr(self,'text_color_presets',{}).items():
            swatch=color or palette['MAUVE'];image=QPixmap(14,14);image.fill(Qt.GlobalColor.transparent)
            painter=QPainter(image);painter.setRenderHint(QPainter.RenderHint.Antialiasing);painter.setBrush(QColor(swatch));painter.setPen(QPen(QColor('#85858c'),.5));painter.drawEllipse(QRectF(1,1,12,12));painter.end();button.setIcon(QIcon(image))
        hint=('Chữ tối trên nền sáng, chữ sáng trên nền tối. Nền trong suốt có viền chữ nhẹ để dễ đọc.'
              if a['foreground']!='custom' else 'Đang dùng màu chữ bạn chọn.')
        if a['foreground']=='tint':hint='Đang dùng màu riêng, tự điều chỉnh độ đậm để dễ đọc trên nền thanh bar.'
        if a['foreground']=='custom' and spec['contrast']<4.5:hint='Màu chữ này có thể khó đọc. Chọn tự điều chỉnh độ rõ hoặc Tự động theo nền thanh bar ở mục Màu chữ và icon.'
        self.contrast_hint.setToolTip(f"Độ tương phản ước tính: {spec['contrast']:.1f}:1")
        self.contrast_hint.setText(hint);self.surface_preview.update();self.appearance_preview.update()
        if ('island','material') in self.controls:
            island=settings['island'];optical=island['material'].startswith('liquid-') and island['glass'] and island['enabled']
            for (group,key),(control,_) in self.controls.items():
                if group!='island' or key=='enabled':continue
                active=island['enabled']
                if key in ('speed','fps'):active=settings['animations']['enabled']
                elif key.startswith('liquid_'):active=optical
                elif key=='material':active=active and island['glass']
                elif key=='default_tab':active=active and not island['remember_tab']
                elif key=='notification_seconds':active=active and island['notifications']
                reason='Bật Chuyển động của giao diện để điều chỉnh.' if key in ('speed','fps') else 'Dynamic Island đang tắt.' if not island['enabled'] else 'Bật Dùng nền kính và chọn một kiểu kính để sử dụng.' if key.startswith('liquid_') else 'Tắt Nhớ trang vừa mở để chọn trang sẽ mở khi bấm.' if key=='default_tab' else 'Bật Thông báo mới để chỉnh thời gian.' if key=='notification_seconds' else 'Bật Dùng nền kính để chọn chất liệu.'
                control._settings_row.setControlEnabled(active,reason)
            self.glass_details.section_card.setEnabled(optical)
            self._refresh_material_status()
        for key in ('hotkey','max_results','dangerous_actions'):
            if ('launcher',key) in self.controls:self.controls[('launcher',key)][0]._settings_row.setControlEnabled(settings['launcher']['enabled'],'Bật App launcher để sử dụng.')
        duration=self.controls[('animations','popup_ms')][0];duration._settings_row.setControlEnabled(settings['animations']['enabled'],'Bật Chuyển động để chỉnh thời gian.')
        for value,button in self.motion_presets.items():button.setChecked(settings['animations']['enabled'] and settings['animations']['popup_ms']==value and settings['island']['speed']==1.)
        for (group,key),(control,kind) in self.controls.items():
            if kind=='bool' and hasattr(control,'setAnimationEnabled'):control.setAnimationEnabled(settings['animations']['enabled'])
        from core.utils.komorebi_theme import KINDS,colors_for
        mode=settings['komorebi']['mode'];colors=colors_for(settings,palette)
        if mode=='original':
            try:colors=json.loads((self.root/'komorebi-original-colors.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):colors=None
        for kind in KINDS:
            button=self.controls[('komorebi',kind.replace('-','_')+'_color')][0]
            button.setEnabled(mode=='custom')
            if colors and kind in colors:button.display_color(colors[kind])
            else:button.refresh();button.setText('Màu ban đầu' if mode=='original' else 'Giữ hiện tại')
            button.setToolTip('Màu riêng đã lưu: '+button.value.upper())
        self._refresh_preset_selection()
        if hasattr(self,'_queue_dirty'):self._queue_dirty()

    def _komorebi(self):
        layout=self._page('Viền cửa sổ','Đổi màu theo theme hoặc tự đặt từng màu. Màu mới được áp dụng ngay; không cần khởi động lại Komorebi.')
        form=self._section(layout,'Đồng bộ màu viền')
        self._bind(form,'Chế độ màu','komorebi','mode','choice',choices=[('Theo theme của bar','theme'),('Màu riêng cho từng trạng thái','custom'),('Khôi phục màu ban đầu','original'),('Không đồng bộ','off')])
        for kind,title in [('single','Cửa sổ đang chọn'),('stack','Nhóm cửa sổ'),('monocle','Chế độ monocle'),('floating','Cửa sổ nổi'),('unfocused','Cửa sổ chưa chọn'),('unfocused-locked','Cửa sổ khóa, chưa chọn')]:
            self._bind(form,title,'komorebi',kind.replace('-','_')+'_color','color')
        self.komorebi_status=QLabel(self.controller.border_bridge.status);self.komorebi_status.setWordWrap(True);self.komorebi_status.setProperty('role','muted');layout.addWidget(self.komorebi_status)
        self.controller.border_bridge.status_changed.connect(self.komorebi_status.setText)
        copy=QPushButton('Lấy màu viền theme làm màu riêng');copy.clicked.connect(self._copy_border_colors);layout.addWidget(copy)
        layout.addStretch()

    def _layout(self):
        layout=self._page('Sắp xếp thanh bar','Kéo các mục để đổi vị trí. Bấm Áp dụng để lưu cách sắp xếp.')
        self.bar_selector=QComboBox();self.bar_selector.addItems(list(self.draft['bars']))
        layout.addWidget(self.bar_selector);self.bar_selector.setVisible(len(self.draft['bars'])>1)
        geometry_card=QWidget();geometry_layout=QVBoxLayout(geometry_card);geometry_layout.setContentsMargins(0,0,0,0)
        fields=self._section(geometry_layout,'Kích thước, vị trí & khoảng cách',collapsed=True);self.position=QComboBox();self.position.addItem('Phía trên','top');self.position.addItem('Phía dưới','bottom')
        fields.addRow('Vị trí thanh bar',self.position)
        self.bar_height=QSpinBox();self.bar_height.setRange(24,80);fields.addRow('Chiều cao (px)',self.bar_height)
        self.bar_width=QLineEdit();fields.addRow('Chiều rộng (%, px hoặc auto)',self.bar_width)
        self.always_top=PendingCheckBox();fields.addRow('Luôn ở trên cửa sổ khác',self.always_top)
        self.reserve=PendingCheckBox();fields.addRow('Chừa khoảng trống cho bar',self.reserve)
        self.autohide=PendingCheckBox();fields.addRow('Tự ẩn thanh bar',self.autohide)
        self.fullscreen=PendingCheckBox();fields.addRow('Ẩn khi chạy fullscreen',self.fullscreen)
        self.outer_padding={}
        for key,title in [('top','Khoảng cách phía trên'),('bottom','Khoảng cách phía dưới'),('left','Khoảng cách bên trái'),('right','Khoảng cách bên phải')]:
            control=QSpinBox();control.setRange(0,160);control.setSuffix(' px');fields.addRow(title,control);self.outer_padding[key]=control
        self.bar_height.setMaximumWidth(168);self.bar_width.setMaximumWidth(200)
        for control in self.outer_padding.values():control.setMaximumWidth(168)
        row=QHBoxLayout();self.region_lists={}
        for key,title in [('left','Trái'),('center','Giữa'),('right','Phải')]:
            column=QVBoxLayout();column.addWidget(QLabel(title));items=WidgetList();self.region_lists[key]=items
            column.addWidget(items);remove=QPushButton('Ẩn mục đã chọn');remove.clicked.connect(lambda checked=False,items=items:[items.takeItem(items.row(x)) for x in list(items.selectedItems())]);column.addWidget(remove)
            row.addLayout(column,1)
        layout.addLayout(row)
        add=QHBoxLayout();self.add_widget=QComboBox()
        for name in self.draft['widgets']:self.add_widget.addItem(LABELS.get(name,name),name)
        self.add_region=QComboBox()
        for text,key in [('Trái','left'),('Giữa','center'),('Phải','right')]:self.add_region.addItem(text,key)
        add_button=QPushButton('Thêm vào thanh bar');add_button.clicked.connect(lambda:self.region_lists[self.add_region.currentData()].add_widget(self.add_widget.currentData()))
        add.addWidget(self.add_widget,1);add.addWidget(self.add_region);add.addWidget(add_button);layout.addLayout(add)
        layout.addWidget(geometry_card)
        self._load_bar_fields()
        self.bar_selector.currentTextChanged.connect(self._change_bar)
        layout.addStretch()

    def _load_bar_fields(self):
        bar=self.draft['bars'][self.bar_name]
        self.position.setCurrentIndex(max(0,self.position.findData(bar.get('alignment',{}).get('position','top'))))
        self.bar_height.setValue(bar.get('dimensions',{}).get('height',34))
        self.bar_width.setText(str(bar.get('dimensions',{}).get('width','100%')))
        flags=bar.get('window_flags',{})
        for key,control in self.outer_padding.items():control.setValue(bar.get('padding',{}).get(key,0))
        for widget,key in [(self.always_top,'always_on_top'),(self.reserve,'windows_app_bar'),(self.autohide,'auto_hide'),(self.fullscreen,'hide_on_fullscreen')]:widget.setChecked(flags.get(key,False))
        for region,items in self.region_lists.items():
            items.clear()
            for name in bar.get('widgets',{}).get(region,[]):items.add_widget(name)

    def _save_bar_fields(self):
        bar=self.draft['bars'][self.bar_name]
        previous_position=bar.get('alignment',{}).get('position','top')
        bar.setdefault('alignment',{})['position']=self.position.currentData()
        width=self.bar_width.text().strip()
        bar.setdefault('dimensions',{}).update(height=self.bar_height.value(),width=int(width) if width.isdigit() else width)
        flags=bar.setdefault('window_flags',{})
        for widget,key in [(self.always_top,'always_on_top'),(self.reserve,'windows_app_bar'),(self.autohide,'auto_hide'),(self.fullscreen,'hide_on_fullscreen')]:flags[key]=widget.isChecked()
        bar['widgets']={region:items.names() for region,items in self.region_lists.items()}
        for key,control in self.outer_padding.items():bar.setdefault('padding',{})[key]=control.value()
        direction='up' if self.position.currentData()=='bottom' else 'down'
        def popup_direction(value):
            if isinstance(value,dict):
                if 'direction' in value and value['direction'] in ('up','down'):value['direction']=direction
                for child in value.values():popup_direction(child)
            elif isinstance(value,list):
                for child in value:popup_direction(child)
        if previous_position!=self.position.currentData():
            for name in set(sum(bar['widgets'].values(),[])):popup_direction(self.draft['widgets'][name].get('options',{}))

    def _change_bar(self,name):
        self._save_bar_fields();self.bar_name=name;self._load_bar_fields()

    def _widgets(self):
        layout=self._page('Tùy chỉnh từng mục','Chọn widget và nhấp đúp vào giá trị để sửa. Đây là các tuỳ chọn nâng cao; thay đổi chỉ áp dụng khi lưu.')
        self.widget_selector=QComboBox()
        active=list(dict.fromkeys(sum(self.draft['bars'][self.bar_name].get('widgets',{}).values(),[])))
        for name in active+[name for name in self.draft['widgets'] if name not in active]:
            self.widget_selector.addItem(LABELS.get(name,name)+(' · đang ẩn' if name not in active else ''),name)
        layout.addWidget(self.widget_selector)
        type_form=self._section(layout,'Loại widget · nâng cao',collapsed=True)
        self.widget_type=QLineEdit();self.widget_type.setAccessibleName('Loại widget YASB');type_form.addRow('Loại widget YASB',self.widget_type)
        self.widget_search=QLineEdit();self.widget_search.setPlaceholderText('Tìm tuỳ chọn…');layout.addWidget(self.widget_search)
        self.options_tree=QTreeWidget();self.options_tree.setHeaderLabels(['Tuỳ chọn','Giá trị']);self.options_tree.setMinimumHeight(350)
        self.options_tree.setItemDelegate(ValueDelegate(self.options_tree))
        self.options_tree.header().resizeSection(0,290);layout.addWidget(self.options_tree)
        all_options=QPushButton('Hiện đầy đủ tuỳ chọn mặc định');all_options.clicked.connect(self._expand_defaults);layout.addWidget(all_options)
        self.widget_selector.currentIndexChanged.connect(self._change_widget)
        self.widget_search.textChanged.connect(self._filter_options)
        self._change_widget(0)

    def _fill_options(self,options):
        self.options_tree.clear()
        def build(parent,data,path=()):
            for key,value in data.items():
                item=QTreeWidgetItem(parent,[str(key),''])
                if isinstance(value,dict):build(item,value,path+(key,));item.setExpanded(len(path)<1)
                else:
                    kind='bool' if type(value) is bool else 'string' if isinstance(value,str) else 'json'
                    item.setData(0,Qt.ItemDataRole.UserRole,(path+(key,),kind))
                    if kind=='bool':
                        item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(1,Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)
                    else:
                        item.setText(1,value if kind=='string' else json.dumps(value,ensure_ascii=True))
                        item.setFlags(item.flags()|Qt.ItemFlag.ItemIsEditable)
        build(self.options_tree,options)

    def _commit_widget(self):
        if not self.widget_name:return
        options=deepcopy(self.draft['widgets'][self.widget_name].get('options',{}))
        def walk(item):
            marker=item.data(0,Qt.ItemDataRole.UserRole)
            if marker:
                path,kind=marker;target=options
                for key in path[:-1]:target=target.setdefault(key,{})
                target[path[-1]]=item.checkState(1)==Qt.CheckState.Checked if kind=='bool' else item.text(1) if kind=='string' else json.loads(item.text(1))
            for i in range(item.childCount()):walk(item.child(i))
        walk(self.options_tree.invisibleRootItem())
        self.draft['widgets'][self.widget_name].update(type=self.widget_type.text().strip(),options=options)

    def _change_widget(self,index):
        if self.widget_loading:return
        try:self._commit_widget()
        except (ValueError,TypeError) as error:
            self.widget_selector.blockSignals(True)
            self.widget_selector.setCurrentIndex(self.widget_selector.findData(self.widget_name))
            self.widget_selector.blockSignals(False)
            self._error(f'Giá trị widget chưa hợp lệ: {error}');return
        self.widget_name=self.widget_selector.itemData(index)
        if not self.widget_name:return
        definition=self.draft['widgets'][self.widget_name]
        self.widget_type.setText(definition['type']);self._fill_options(definition.get('options',{}))

    def _expand_defaults(self):
        try:
            self._commit_widget();definition=self.draft['widgets'][self.widget_name]
            module,cls=definition['type'].rsplit('.',1)
            schema=getattr(import_module('core.widgets.'+module),cls).validation_schema
            options=schema.model_validate(definition.get('options',{})).model_dump(mode='json')
            self._fill_options(options)
        except Exception as error:self._error(str(error))

    def _filter_options(self,text):
        text=text.casefold()
        def walk(item):
            visible=text in item.text(0).casefold() or text in item.text(1).casefold()
            for i in range(item.childCount()):visible=walk(item.child(i)) or visible
            item.setHidden(not visible);return visible
        for i in range(self.options_tree.topLevelItemCount()):walk(self.options_tree.topLevelItem(i))

    def _choose_wallpaper_directory(self):
        control=self.controls[('launcher','wallpaper_directory')][0]
        directory=QFileDialog.getExistingDirectory(self,'Chọn thư mục hình nền',control.text() or str(self.root/'wallpapers'))
        if directory:control.setText(directory);self._queue_immediate_preferences()

    def _island(self):
        layout=self._page('Island và Launcher','Một preset dùng chung cho pill, menu và launcher. Bấm pill để mở menu; Alt+Space để tìm kiếm.')
        form=self._section(layout,'Preset chung · Island và Launcher')
        self._bind(form,'Hiện Dynamic Island','island','enabled','bool')
        self._bind(form,'Dùng nền kính','island','glass','bool')
        self._bind(form,'Kiểu nền kính','island','material','choice',choices=[('Kính mềm · đề xuất','liquid-soft'),('Kính trong','liquid-clear'),('Kính mờ','frosted'),('Chỉ đường viền','outline')])
        self.controls[('island','material')][0].activated.connect(self._material_preset)
        self._bind(form,'Hiện đường viền','island','outline','bool')
        self.material_status=QLabel();self.material_status.setWordWrap(True);self.material_status.setProperty('role','muted');form.addRow(self.material_status)
        self.material_preset_hint=QLabel();self.material_preset_hint.setWordWrap(True);self.material_preset_hint.setProperty('role','muted');form.addRow(self.material_preset_hint)
        self.material_reset=QPushButton('Dùng lại preset kính');self.material_reset.clicked.connect(self._material_preset);form.addRow(self.material_reset)
        self.material_poll=QTimer(self);self.material_poll.setInterval(1200);self.material_poll.timeout.connect(self._refresh_material_status)
        form=self._section(layout,'App launcher · tìm kiếm trên thanh bar')
        self._bind(form,'Bật App launcher','launcher','enabled','bool')
        self._bind(form,'Mở bằng Alt+Space','launcher','hotkey','bool')
        self._bind(form,'Số kết quả hiển thị','launcher','max_results',low=3,high=7)
        self._bind(form,'Lệnh tắt máy, khởi động lại và đăng xuất','launcher','dangerous_actions','bool')
        form=self._section(layout,'Hình nền và màu giao diện')
        self._bind(form,'Chỉ hiện yêu thích từ Wallpaper Engine','launcher','wallpaper_favorites_only','bool')
        self._bind(form,'Tự đổi màu giao diện theo hình nền','launcher','wallpaper_auto_theme','bool')
        self._bind(form,'Tông màu theo hình nền','launcher','wallpaper_theme_mode','choice',choices=[('Giữ sáng/tối đang dùng','current'),('Luôn sáng','light'),('Luôn tối','dark')])
        self._bind(form,'Thư mục hình nền','launcher','wallpaper_directory','text')
        choose=QPushButton('Chọn thư mục hình nền…');choose.clicked.connect(self._choose_wallpaper_directory);form.addRow(choose)
        hint=QLabel('Gõ tên app, phép tính hoặc > để xem lệnh. Mũi tên để chọn, Enter để mở, Esc để đóng. Hiệu ứng dùng cùng cài đặt chuyển động của Island.');hint.setWordWrap(True);hint.setProperty('role','muted');form.addRow(hint)
        hint=QLabel('Yêu thích lấy từ tài khoản Steam đang dùng với Wallpaper Engine; chỉ hiện các ảnh đã tải về máy. Bấm Làm mới trong gallery sau khi thêm hoặc bỏ sao. Chọn một theme cố định sẽ tắt tự đổi màu.');hint.setWordWrap(True);hint.setProperty('role','muted');form.addRow(hint)
        form=self._section(layout,'Khi bấm vào Island')
        choices=[('Tổng quan (Dashboard)','Dashboard'),('Nhạc và âm thanh (Media)','Media'),('Hiệu năng máy (Performance)','Performance'),('Thời tiết (Weather)','Weather'),('Hoạt động đang chạy (Live Activity)','Live Activity')]
        self._bind(form,'Trang mở khi bấm','island','default_tab','choice',choices=choices)
        self._bind(form,'Nhớ trang vừa mở','island','remember_tab','bool')
        form=self._section(layout,'Nội dung hiển thị',collapsed=True)
        for label,key in [('Nhạc đang phát','media'),('Codex đang làm việc','codex'),('Thông báo mới','notifications'),('Hẹn giờ','timer'),('Bấm giờ','stopwatch'),('Thay đổi loa hoặc tai nghe','output')]:self._bind(form,label,'island',key,'bool')
        self._bind(form,'Hiện thông báo trong','island','notification_seconds',low=1,high=30);self.controls[('island','notification_seconds')][0].setSuffix(' giây')
        form=self._section(layout,'Chỉnh preset kính chung',collapsed=True);self.glass_details=form
        self._bind(form,'Độ uốn của kính','island','liquid_refraction','decimal',0,2)
        self._bind(form,'Độ mờ của kính','island','liquid_frost','percent',0,1)
        self._bind(form,'Độ phủ màu của kính','island','liquid_tint','percent',0,.85)
        self._bind(form,'Độ sáng của viền kính','island','liquid_reflection','decimal',0,2)
        self._bind(form,'Giữ chữ dễ đọc','island','liquid_contrast','bool')
        self._bind(form,'Độ mượt tối đa của kính','island','liquid_fps','choice',choices=[(str(x)+' FPS',x) for x in (30,60,90,120,144,165,240)])
        form=self._section(layout,'Hiệu ứng và kích thước',collapsed=True)
        self._bind(form,'Hiệu ứng khi đưa chuột lên','island','hover','bool')
        self._bind(form,'Độ rộng khi không có hoạt động','island','idle_width',low=80,high=240)
        form=self._section(layout,'Địa điểm thời tiết · nâng cao',collapsed=True)
        self._bind(form,'Tên địa điểm','weather','city','text')
        self._bind(form,'Vĩ độ','weather','latitude','decimal',-90,90)
        self._bind(form,'Kinh độ','weather','longitude','decimal',-180,180)
        self._bind(form,'Múi giờ','weather','timezone','text')
        layout.addStretch()


    def _backups(self):
        layout=self._page('Sao lưu','Giữ một bản giao diện bạn thích để có thể quay lại sau này.')
        create=QPushButton('Tạo bản sao lưu ngay');create.clicked.connect(self._snapshot);layout.addWidget(create)
        self.backup_list=QListWidget();self.backup_list.setMinimumHeight(280);self.backup_list.setAccessibleName('Các bản đã sao lưu');layout.addWidget(self.backup_list)
        self.restore_button=QPushButton('Quay về bản đã chọn');self.restore_button.setEnabled(False);self.restore_button.clicked.connect(self._restore);layout.addWidget(self.restore_button)
        self.backup_list.currentItemChanged.connect(lambda item,*_:self.restore_button.setEnabled(item is not None))
        hint=QLabel('Chọn một bản trong danh sách để quay lại. Giao diện hiện tại cũng được sao lưu trước khi khôi phục.');hint.setWordWrap(True);hint.setProperty('role','muted');layout.addWidget(hint)
        form=self._section(layout,'Lưu ra file hoặc mở thư mục',collapsed=True)
        export=QPushButton('Lưu một bản thành file ZIP…');export.clicked.connect(self._export);form.addRow(export)
        directory=QPushButton('Mở thư mục sao lưu');directory.clicked.connect(self._open_backups);form.addRow(directory)
        initial=QPushButton('Mở bản sao trước lần tùy chỉnh đầu tiên');initial.clicked.connect(self._open_initial);form.addRow(initial)
        self._refresh_backups();layout.addStretch()


    def _refresh_backups(self):
        self.backup_list.clear()
        for directory in sorted((self.root/'settings-backups').glob('*'),reverse=True):
            try:
                metadata=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
                stamp=datetime.fromisoformat(str(metadata.get('created',''))).strftime('%d/%m/%Y · %H:%M')
                item=QListWidgetItem(f"{stamp}   ·   {metadata.get('label','Bản sao lưu')}")
                item.setData(Qt.ItemDataRole.UserRole,str(directory));self.backup_list.addItem(item)
            except (OSError,ValueError,TypeError,AttributeError):continue

    def _snapshot(self):
        create_snapshot(self.root,'Bản sao lưu thủ công');self._refresh_backups();self.status.setText('Đã tạo bản sao lưu.')

    def _restore(self):
        item=self.backup_list.currentItem()
        if not item:self.status.setText('Chọn một bản sao lưu trước.');return
        try:
            before=yaml.safe_load((self.root/'config.yaml').read_bytes())
            restore_snapshot(self.root,item.data(Qt.ItemDataRole.UserRole))
            self.controller.reload_preferences()
            self.controller.select(json.loads((self.root/'theme.json').read_text())['name'])
            after=yaml.safe_load((self.root/'config.yaml').read_bytes())
            runtime=getattr(self.controller.manager,'config',None)
            changed=before!=after
            if runtime is not None:
                changed=validate_config(after).model_dump(exclude={'watch_config','watch_stylesheet'})!=runtime.model_dump(exclude={'watch_config','watch_stylesheet'})
            if changed:self._schedule_reload()
            else:
                self.hide();self.controller.settings_dialog=None;self.controller.show_settings(6);self.deleteLater()
        except Exception as error:self._error(str(error))

    def _open_backups(self):
        from core.utils.shell_utils import shell_open
        directory=self.root/'settings-backups';directory.mkdir(exist_ok=True);shell_open(str(directory))

    def _open_initial(self):
        from core.utils.shell_utils import shell_open
        try:
            directory=json.loads((self.root/'initial-settings-backup.json').read_text())['path']
            shell_open(directory)
        except (OSError,ValueError,KeyError):self.status.setText('Không tìm thấy bản sao lưu ban đầu.')

    def _export(self):
        import zipfile
        path,_=QFileDialog.getSaveFileName(self,'Xuất cấu hình',str(Path.home()/'Desktop/ponie-yasb.zip'),'ZIP (*.zip)')
        if not path:return
        try:
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
                for file in self.root.rglob('*'):
                    relative=file.relative_to(self.root)
                    if not file.is_file() or any(p in ('runtime','__pycache__','backup','settings-backups') for p in relative.parts):continue
                    if file.resolve()==Path(path).resolve():continue
                    if file.suffix in ('.log','.lock') or file.name.startswith('yasb.log') or file.name=='komorebi-original-colors.json':continue
                    archive.write(file,str(relative))
            self.status.setText('Đã xuất cấu hình ZIP.')
        except OSError as error:self._error(str(error))

    def _advanced(self):
        layout=self._page('Nâng cao','YAML chứa toàn bộ tuỳ chọn YASB. CSS được giữ riêng và áp dụng trên mọi theme. Nội dung sai sẽ không được ghi vào cấu hình.')
        tabs=QTabWidget();layout.addWidget(tabs)
        self.raw_yaml=QPlainTextEdit((self.root/'config.yaml').read_text(encoding='utf-8'))
        self.custom_css=QPlainTextEdit((self.root/'custom.css').read_text(encoding='utf-8') if (self.root/'custom.css').exists() else '')
        self.raw_preferences=QPlainTextEdit(json.dumps(self.preferences,ensure_ascii=False,indent=2))
        for editor,title in [(self.raw_yaml,'YASB · YAML'),(self.custom_css,'CSS tuỳ chỉnh'),(self.raw_preferences,'Settings · JSON')]:
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap);editor.setMinimumHeight(405)
            editor.setFont(QFont('JetBrainsMono NFP',10));tabs.addTab(editor,title)
        self.raw_yaml.document().setModified(False);self.raw_preferences.document().setModified(False)

    def _page_changed(self,index):
        if index in (3,5,7) and not self.advanced_button.isChecked():self.advanced_button.setChecked(True)
        previous=getattr(self,'_active_page',0)
        if previous==7 and index!=7:
            try:self._consume_advanced_drafts()
            except Exception as error:
                self.nav.blockSignals(True);self.nav.setCurrentRow(7);self.nav.blockSignals(False);self._error(str(error));return
        if index==7:
            try:
                self._save_bar_fields();self._commit_widget()
                if not self.raw_yaml.document().isModified():
                    self.raw_yaml.setPlainText(yaml.safe_dump(self.draft,sort_keys=False,allow_unicode=False));self.raw_yaml.document().setModified(False)
                if not self.raw_preferences.document().isModified():
                    self.raw_preferences.setPlainText(json.dumps(self._collect_preferences(),ensure_ascii=False,indent=2));self.raw_preferences.document().setModified(False)
            except Exception as error:self._error(str(error))
        outgoing=self.pages.grab() if self.isVisible() and previous!=index else None
        self.pages.setCurrentIndex(index)
        if outgoing is not None:self.page_motion.begin(outgoing,1 if index>previous else -1)
        self._active_page=index
        if hasattr(self,'material_poll'):
            if index==4:self._refresh_material_status();self.material_poll.start()
            else:self.material_poll.stop()

    def _refresh_material_status(self):
        saved=load_preferences(self.root)['island'];current=self._collect_preferences()['island']
        names={'liquid-soft':'Kính mềm','liquid-clear':'Kính trong','frosted':'Kính mờ','outline':'Chỉ đường viền'}
        text='Dynamic Island đang tắt.' if not saved['enabled'] else 'Đang dùng nền trong suốt.' if not saved['glass'] else 'Đang dùng: '+names.get(saved['material'],'Kính mềm')+'.'
        try:
            status=json.loads((self.root/'dynamic-island/material-status.json').read_text(encoding='utf-8'))
            self.material_status.setToolTip(status.get('message',''))
            if saved['enabled'] and saved['glass'] and status.get('state')=='fallback':text='Đang dùng kính mờ thay thế để giữ giao diện hoạt động.'
        except (OSError,ValueError):pass
        if any(current.get(key)!=saved.get(key) for key in ('enabled','glass','outline','material',*[key for key in current if key.startswith('liquid_')])):text='Đang áp dụng nền mới…'
        self.material_status.setText(text)
        if hasattr(self,'material_preset_hint'):
            defaults=material_preset(current['material'])
            customized=any(current[key]!=value for key,value in defaults.items())
            self.material_preset_hint.setText(('Đã tùy chỉnh từ ' if customized else 'Đang dùng preset ')+names[current['material']]+'.')
            self.material_reset.setVisible(customized)


    def _consume_advanced_drafts_core(self):
        """Round-trip advanced edits before returning to forms; no silent draft priority."""
        preferences=None;config=None
        if self.raw_preferences.document().isModified():preferences=validate_preferences(json.loads(self.raw_preferences.toPlainText()))
        if self.raw_yaml.document().isModified():
            config=yaml.safe_load(self.raw_yaml.toPlainText());validate_config(config)
        if preferences is not None:
            self.preferences=preferences
            for group,key in self.controls:self._set_field(group,key,preferences[group][key])
            self.custom_accent.setChecked('MAUVE' in preferences['palette'])
            if 'MAUVE' in preferences['palette']:self.accent.value=preferences['palette']['MAUVE'];self.accent.refresh()
            self.raw_preferences.document().setModified(False)
        if config is not None:
            self.draft=config;self.bar_name=self.bar_name if self.bar_name in config['bars'] else next(iter(config['bars']))
            self.bar_selector.blockSignals(True);self.bar_selector.clear();self.bar_selector.addItems(config['bars']);self.bar_selector.setCurrentText(self.bar_name);self.bar_selector.blockSignals(False)
            self._load_bar_fields()
            self.widget_name=None
            self.widget_selector.blockSignals(True);self.widget_selector.clear()
            for name in config['widgets']:self.widget_selector.addItem(LABELS.get(name,name),name)
            self.widget_selector.blockSignals(False);self._change_widget(0)
            self.raw_yaml.document().setModified(False)
        self._refresh_preview()


    def _consume_advanced_drafts(self):
        had_json=self.raw_preferences.document().isModified();success=False
        self._immediate_begin_loading()
        try:
            self._consume_advanced_drafts_core();success=True
        finally:self._immediate_end_loading(imported_preferences=had_json and success)

    def _adapt_navigation(self):
        compact=self.width()<1008
        changed=self.nav.property('compact')!=compact
        self.nav.setProperty('compact',compact);self.nav_pane.setFixedWidth(48 if compact else 240)
        self.nav_title.setVisible(not compact);self.advanced_button.setText('⋯' if compact else 'Thiết lập nâng cao');self.nav.viewport().update()
        if changed:
            self.nav.doItemsLayout();self.nav.horizontalScrollBar().setValue(0)
            QTimer.singleShot(0,self.nav.doItemsLayout)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if all(hasattr(self,name) for name in ('nav_pane','nav','nav_title')):self._adapt_navigation()

    def changeEvent(self,event):
        super().changeEvent(event)
        kinds=(getattr(QEvent.Type,'ThemeChange',None),QEvent.Type.ApplicationPaletteChange)
        if (event.type() in kinds or event.type()==QEvent.Type.ActivationChange and self.isActiveWindow()) and hasattr(self,'_surface_palette'):
            QTimer.singleShot(0,self.refresh_style)


    def _advanced_navigation(self,opened):
        if not opened and self.nav.currentRow() in (3,5,7):self.nav.setCurrentRow(0)
        for index in (3,5,7):self.nav.setRowHidden(index,not opened)

    def _refresh_preset_selection(self):
        if not hasattr(self,'surface_preset_buttons'):return
        a=self._collect_preferences()['appearance'];name=None
        if a['background']=='transparent':name='clear'
        elif a['background']=='glass' and not a['background_gradient'] and a['background_source']=='theme' and a['foreground']=='auto' and not a['border']:
            for candidate,alpha,blur in (('soft',.36,True),('balanced',.56,True),('solid',1.,False)):
                if abs(a['background_opacity']-alpha)<.0001 and a['background_blur']==blur:name=candidate
        for key,button in self.surface_preset_buttons.items():button.setChecked(key==name)
        self.surface_preset_label.setText('Đang dùng: '+('Theo bộ màu đã chọn' if a['background']=='theme' else self.surface_preset_buttons[name].text() if name else 'Tùy chỉnh riêng'))

    def _disk_state(self):
        return {name:(self.root/name).read_bytes() if (self.root/name).exists() else None for name in ('config.yaml','bar-settings.json','custom.css')}

    def _collect_preferences(self):
        settings=deepcopy(self.preferences)
        for (group,key),(control,kind) in self.controls.items():
            if kind=='bool':value=control.isChecked()
            elif kind=='text':value=control.text()
            elif kind=='font':value=control.property('requested_family')
            elif kind=='choice':value=control.currentData()
            elif kind=='color':value=control.value
            else:value=control.value()
            settings[group][key]=value
        if self.custom_accent.isChecked():settings['palette']['MAUVE']=self.accent.value
        else:settings['palette'].pop('MAUVE',None)
        return settings

    def _error(self,text):
        logging.warning('Bar settings validation: %s',text)
        if hasattr(self,'status'):
            self.status.setToolTip(str(text))
            self.status.setText('Chưa lưu: '+str(text)[:320])

    def apply_changes(self):
        if self._committing:return
        try:
            if self._disk_state()!=self._disk_baseline:raise ValueError('Cấu hình đã được thay đổi bên ngoài cửa sổ này. Mở lại Settings để tải bản mới; bản trên đĩa chưa bị ghi đè.')
            self._save_bar_fields();self._commit_widget()
            config=yaml.safe_load(self.raw_yaml.toPlainText()) if self.raw_yaml.document().isModified() else deepcopy(self.draft)
            validated=validate_config(config)
            preferences=json.loads(self.raw_preferences.toPlainText()) if self.raw_preferences.document().isModified() else self._collect_preferences()
            preferences=validate_preferences(preferences)
            custom=self.custom_css.toPlainText()
            self._validate_css(custom)
            old_config=yaml.safe_load((self.root/'config.yaml').read_bytes())
            changed=config!=old_config
            snapshot=create_snapshot(self.root)
            try:
                atomic_write(self.root/'bar-settings.json',json.dumps(preferences,ensure_ascii=False,indent=2)+'\n')
                atomic_write(self.root/'custom.css',custom)
                if changed:atomic_write(self.root/'config.yaml',yaml.safe_dump(config,sort_keys=False,allow_unicode=False))
                if not self.controller.select(self.selected_theme):raise RuntimeError('Không áp dụng được theme.')
                self.controller.reload_preferences()
            except Exception:
                restore_snapshot(self.root,snapshot)
                restored=json.loads((self.root/'theme.json').read_text(encoding='utf-8'))['name']
                self.controller.select(restored);self.controller.reload_preferences()
                self._disk_baseline=self._disk_state()
                raise
            self.preferences=preferences;self.draft=config;self._disk_baseline=self._disk_state()
            self.custom_accent.setChecked('MAUVE' in preferences['palette'])
            if 'MAUVE' in preferences['palette']:
                self.accent.value=preferences['palette']['MAUVE'];self.accent.refresh()
            for group,key in self.controls:self._set_field(group,key,preferences[group][key])
            self.raw_yaml.document().setModified(False);self.raw_preferences.document().setModified(False)
            self.refresh_style();self._refresh_preview();self._refresh_backups();self.status.setText('Đã áp dụng thay đổi.');self._mark_saved();self._immediate_saved(snapshot)
            runtime=getattr(self.controller.manager,'config',None)
            if runtime is not None:
                changed=validated.model_dump(exclude={'watch_config','watch_stylesheet'})!=runtime.model_dump(exclude={'watch_config','watch_stylesheet'})
            if changed:self._schedule_reload()
        except Exception as error:self._error(str(error))

    @staticmethod
    def _validate_css(css):
        from core.utils.bar_preferences import validate_custom_css
        validate_custom_css(css)

    def _schedule_reload(self):
        self._committing=True
        atomic_write(self.root/'reopen-bar-settings.json',json.dumps({'page':self.nav.currentRow()}))
        self.status.setText('Đã lưu. Đang cập nhật thanh bar…')
        self.apply_button.setEnabled(False)
        QTimer.singleShot(120,self.controller.manager.on_config_modified)
