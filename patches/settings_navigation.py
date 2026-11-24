"""Settings search and persistent save feedback without editing any values."""
import unicodedata
from PyQt6.QtCore import QObject,QEvent,Qt,QSize,QTimer,pyqtSignal
from PyQt6.QtGui import QKeySequence,QShortcut
from PyQt6.QtWidgets import QLabel,QLineEdit,QListWidget,QListWidgetItem,QWidget,QStackedWidget
from core.utils.ui_motion import duration

class StatusLabel(QLabel):
    changed=pyqtSignal(str)
    def setText(self,text):super().setText(text);self.changed.emit(str(text))

def folded(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(text).casefold().replace('đ','d')) if not unicodedata.combining(c))

class SettingsSearch(QObject):
    def __init__(self,dialog):
        super().__init__(dialog);self.dialog=dialog;self.entries=[]
        self.field=dialog.settings_search;self.results=dialog.search_results
        aliases={'font_family':'font phông', 'foreground':'màu chữ văn bản icon', 'text_color':'màu chữ văn bản icon',
                 'liquid_frost':'glass blur kính độ mờ','enabled':'bật tắt', 'hotkey':'alt space phím tắt',
                 'city':'thời tiết thành phố hà nội weather','material':'glass liquid nền kính',
                 'popup_ms':'hiệu ứng chuyển động animation motion tốc độ', 'speed':'hiệu ứng chuyển động animation motion tốc độ'}
        for (group,key),(control,_) in dialog.controls.items():
            page=next((i for i in range(dialog.pages.count()) if dialog.pages.widget(i).isAncestorOf(control)),None)
            if page is None:continue
            label=control.accessibleName() or key;detail=dialog.nav.item(page).text()
            self.entries.append((label,detail,page,control,folded(label+' '+detail+' '+aliases.get(key,'')+' '+('launcher tìm ứng dụng' if group=='launcher' else ''))))
        for page,buttons in ((0,dialog.theme_buttons),(1,dialog.surface_preset_buttons),(0,{key:value[0] for key,value in dialog.text_color_presets.items()})):
            for key,button in buttons.items():
                label=button.accessibleName() or button.text();detail=dialog.nav.item(page).text()
                self.entries.append((label,detail,page,button,folded(label+' '+detail+' '+key)))
        self.field.textChanged.connect(self.update);self.field.returnPressed.connect(self.activate)
        self.field.installEventFilter(self);self.results.itemActivated.connect(lambda _:self.activate());self.results.itemClicked.connect(lambda _:self.activate())
        self.shortcut=QShortcut(QKeySequence.StandardKey.Find,dialog);self.shortcut.activated.connect(self.focus)
    def focus(self):self.field.setFocus(Qt.FocusReason.OtherFocusReason);self.field.selectAll()
    def update(self,text):
        query=folded(text).strip();self.results.clear()
        self.dialog.content_stack.setCurrentIndex(1 if query else 0)
        if not query:return
        words=query.split()
        matches=[e for e in self.entries if all(word in e[4] for word in words)]
        for label,detail,page,control,_ in matches[:30]:
            item=QListWidgetItem(label+'\n'+detail);item.setSizeHint(QSize(300,58));item.setData(Qt.ItemDataRole.UserRole,(page,control));self.results.addItem(item)
        if matches:self.results.setCurrentRow(0)
        else:
            item=QListWidgetItem('Không tìm thấy cài đặt. Thử từ ngắn hơn.');item.setFlags(Qt.ItemFlag.NoItemFlags);self.results.addItem(item)
    def activate(self):
        item=self.results.currentItem();data=item.data(Qt.ItemDataRole.UserRole) if item else None
        if data is None:return
        page,control=data;self.field.clear()
        self.dialog.nav.setCurrentRow(page)
        if self.dialog.pages.currentIndex()!=page:return
        parent=control
        while parent is not None:
            form=getattr(parent,'_settings_form',None)
            if form is not None and form.disclosure is not None:form.disclosure.setChecked(True)
            parent=parent.parentWidget()
        self.dialog.pages.widget(page).widget().layout().activate()
        control.setFocus(Qt.FocusReason.OtherFocusReason)
        def reveal():
            if self.dialog.pages.currentIndex()==page and not self.field.text() and control.isVisible():self.dialog.pages.widget(page).ensureWidgetVisible(getattr(control,'_settings_row',control),12,24)
        QTimer.singleShot(0,reveal);QTimer.singleShot(duration('section',self.dialog)+20,reveal)
    def eventFilter(self,obj,event):
        if event.type()!=QEvent.Type.KeyPress:return False
        if event.key()==Qt.Key.Key_Escape and self.field.text():self.field.clear();return True
        if self.field.text() and event.key() in (Qt.Key.Key_Down,Qt.Key.Key_Up):
            direction=1 if event.key()==Qt.Key.Key_Down else -1
            self.results.setCurrentRow(max(0,min(self.results.count()-1,self.results.currentRow()+direction)));return True
        return False

def save_feedback(dialog,text):
    if text.startswith('Chưa lưu:'):short='Chưa lưu'
    elif 'nâng cao' in text and ('chưa' in text or 'cần' in text):short='Có thay đổi chờ áp dụng'
    elif text.startswith('Đang'):short='Đang lưu…'
    else:short='Tự động lưu'
    dialog.save_status.setText(short);dialog.save_status.setToolTip(text);dialog.save_status.setAccessibleDescription(text)
