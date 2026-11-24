"""Caelestia launcher presentation adapted to an Island on a horizontal bar.

Reference: caelestia-dots/shell 5cbf60e7, modules/launcher and SearchBar.qml.
57px rows, 8px gaps, 16px padding, full search radius, 16px selection radius.
The top-bar version mirrors the original bottom-anchored search vertically.
"""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QAbstractListModel,QEvent,QModelIndex,QPointF,QRectF,QSize,Qt,QVariantAnimation,Signal,QEasingCurve
from PySide6.QtGui import QColor,QFont,QFontDatabase,QIcon,QKeyEvent,QPainter,QPainterPath,QPalette,QPen,QRegion
from PySide6.QtWidgets import QApplication,QAbstractItemView,QGraphicsOpacityEffect,QLineEdit,QListView,QPushButton,QStyledItemDelegate,QWidget
from PySide6.QtSvg import QSvgRenderer
import palette

WIDTH=632
ROW=57
GAP=8
PADDING=16
SEARCH=56
_font=None


def font(size=14,weight=QFont.Weight.Normal):
    global _font
    if _font is None:
        identifier=QFontDatabase.addApplicationFont(str(Path(__file__).resolve().parent/'assets/GoogleSansFlex.ttf'))
        families=QFontDatabase.applicationFontFamilies(identifier)
        _font=families[0] if families else 'Segoe UI'
    result=QFont(_font);result.setPixelSize(size);result.setWeight(weight);return result


@lru_cache(maxsize=3)
def curve(name='spatial'):
    result=QEasingCurve(QEasingCurve.Type.BezierSpline)
    from motion_spec import tokens
    a,b,c,d=tokens(Path(__file__).resolve().parent.parent)['curves'][name]
    result.addCubicBezierSegment(QPointF(a,b),QPointF(c,d),QPointF(1,1));return result


PATHS={
    'search':'<path d="m21 21-5.2-5.2"/><circle cx="10.5" cy="10.5" r="6.5"/>',
    'x':'<path d="m6 6 12 12M18 6 6 18"/>',
    'apps':'<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
    'calculate':'<rect x="5" y="2" width="14" height="20" rx="3"/><path d="M8 6h8M8 10h2m4 0h2M8 14h2m4 0h2M8 18h2m4 0h2"/>',
    'settings':'<path d="m9 3 .5 3-2 1.2-2.7-1-3 5.3 2.5 1.8v2.3L1.8 17l3 5.2 2.8-1 2 1.1.4 3h6l.5-3 2-1.1 2.7 1 3-5.2-2.5-1.8V13l2.5-1.8-3-5.3-2.8 1-2-1.1-.4-3z" transform="translate(1 -1) scale(.85)"/><circle cx="12" cy="12" r="3"/>',
    'folder':'<path d="M3 6a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    'globe':'<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
    'timer':'<circle cx="12" cy="14" r="7"/><path d="M9 2h6m-3 0v5m0 3v5l2 1m4-9 2-2"/>',
}
@lru_cache(maxsize=96)
def svg(name,color):
    return QSvgRenderer(('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="'+color+'" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+PATHS.get(name,PATHS['apps'])+'</svg>').encode())
def glyph(painter,name,rect,color=None):svg(name,color or palette.MUTED).render(painter,QRectF(rect))


class Search(QWidget):
    def __init__(self,parent):
        super().__init__(parent);self.backdrop_strength=1.;self.edit=QLineEdit(self)
        self.edit.setAccessibleName('Tìm ứng dụng, tính toán hoặc lệnh nhanh')
        self.edit.setPlaceholderText('Tìm ứng dụng · tính toán · gõ > để xem lệnh')
        self.edit.setMaxLength(512);self.edit.setFont(font(14))
        self.clear_button=QPushButton(self);self.clear_button.setAccessibleName('Xóa tìm kiếm');self.clear_button.setToolTip('Xóa tìm kiếm')
        self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.clear_button.clicked.connect(self.edit.clear)
        self.edit.textChanged.connect(lambda value:self.clear_button.setVisible(bool(value)))
        self.clear_button.hide();self.theme()
    def theme(self):
        colors=self.edit.palette();colors.setColor(QPalette.ColorRole.PlaceholderText,QColor(palette.MUTED));self.edit.setPalette(colors)
        self.edit.setStyleSheet('QLineEdit {background:transparent;border:0;padding:0;color:'+palette.TEXT+';selection-background-color:'+palette.MAUVE+';selection-color:'+palette.BASE+';}')
        self.clear_button.setStyleSheet('QPushButton {background:transparent;border:0;border-radius:18px;} QPushButton:hover {background:'+palette.SURFACE2+';}')
        from PySide6.QtGui import QPixmap
        image=QPixmap(20,20);image.fill(Qt.GlobalColor.transparent);p=QPainter(image);glyph(p,'x',QRectF(1,1,18,18),palette.MUTED);p.end();self.clear_button.setIcon(QIcon(image))
        self.update()
    def resizeEvent(self,event):
        self.edit.setGeometry(54,0,max(10,self.width()-108),SEARCH)
        self.clear_button.setGeometry(self.width()-48,10,36,36)
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color=QColor(palette.TEXT);color.setAlphaF(.055*self.backdrop_strength)
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(color);painter.drawRoundedRect(QRectF(self.rect()),28,28)
        glyph(painter,'search',QRectF(19,18,20,20),palette.MUTED);painter.end()


class Model(QAbstractListModel):
    def __init__(self):super().__init__();self.rows=[]
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        row=self.rows[index.row()]
        if role==Qt.ItemDataRole.DisplayRole:return row.title
        if role in (Qt.ItemDataRole.AccessibleTextRole,Qt.ItemDataRole.ToolTipRole):return row.title+' · '+row.detail
        if role==Qt.ItemDataRole.SizeHintRole:return QSize(600,ROW+GAP)
    def replace(self,rows):self.beginResetModel();self.rows=rows;self.endResetModel()


class Delegate(QStyledItemDelegate):
    def __init__(self,view,catalog):super().__init__(view);self.view=view;self.catalog=catalog
    def sizeHint(self,option,index):return QSize(600,ROW+GAP)
    def paint(self,painter,option,index):
        row=self.view.model().rows[index.row()];rect=QRectF(option.rect);rect.setHeight(ROW)
        painter.save();painter.setRenderHints(QPainter.RenderHint.Antialiasing|QPainter.RenderHint.SmoothPixmapTransform)
        image=self.catalog.images.get(row.key)
        art=QRectF(rect.left()+12,rect.center().y()-18,36,36)
        if image is not None and not image.isNull():painter.drawImage(art,image)
        else:glyph(painter,row.glyph,art.adjusted(4,4,-4,-4),palette.MUTED)
        left=rect.left()+60;available=max(0,rect.width()-left-16)
        painter.setFont(font(14));painter.setPen(QColor(palette.TEXT))
        painter.drawText(QRectF(left,rect.top()+9,available,21),Qt.AlignmentFlag.AlignVCenter,painter.fontMetrics().elidedText(row.title,Qt.TextElideMode.ElideRight,round(available)))
        painter.setFont(font(12));painter.setPen(QColor(palette.MUTED))
        painter.drawText(QRectF(left,rect.top()+30,available,18),Qt.AlignmentFlag.AlignVCenter,painter.fontMetrics().elidedText(row.detail,Qt.TextElideMode.ElideRight,round(available)))
        painter.restore()


class Results(QListView):
    def __init__(self,catalog,parent):
        super().__init__(parent);self.setModel(Model());self.setItemDelegate(Delegate(self,catalog));self.setAccessibleName('Kết quả tìm kiếm')
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True);self.setUniformItemSizes(True);self.setFrameShape(QListView.Shape.NoFrame)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setStyleSheet('QListView {background:transparent;border:0;outline:0;padding:0;} QListView::item {background:transparent;}')
        self.viewport().setAutoFillBackground(False);self.highlight=0.
        self.animation=QVariantAnimation(self);self.animation.setDuration(350);self.animation.setEasingCurve(curve('fast'))
        self.animation.valueChanged.connect(self._move_highlight)
        self.selectionModel().currentChanged.connect(self._selected)
        self.entered.connect(self.setCurrentIndex)
    def _move_highlight(self,value):self.highlight=float(value);self.viewport().update()
    def _selected(self,index,previous):
        self.animation.stop();self.animation.setStartValue(self.highlight);self.animation.setEndValue(float(max(0,index.row())*(ROW+GAP)));self.animation.start()
    def paintEvent(self,event):
        if self.currentIndex().isValid():
            painter=QPainter(self.viewport());painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            color=QColor(palette.TEXT);color.setAlphaF(.08);painter.setBrush(color);painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(0,self.highlight-self.verticalScrollBar().value(),self.viewport().width(),ROW),16,16);painter.end()
        super().paintEvent(event)


class LauncherView(QWidget):
    query_changed=Signal(str)
    accepted=Signal(object)
    dismissed=Signal()
    height_changed=Signal()
    def __init__(self,parent,catalog):
        super().__init__(parent);self.catalog=catalog;self.bottom=False;self.max_rows=7;self.morph_margin=16.;self.search=Search(self);self.results=Results(catalog,self)
        self.effect=QGraphicsOpacityEffect(self.search);self.effect.setOpacity(0);self.search.setGraphicsEffect(self.effect)
        self.results_effect=QGraphicsOpacityEffect(self.results);self.results_effect.setOpacity(0);self.results.setGraphicsEffect(self.results_effect)
        self.search.edit.textChanged.connect(self.query_changed)
        QApplication.instance().installEventFilter(self);self.results.clicked.connect(self._accept_index)
        self.search.edit.returnPressed.connect(self.accept_current)
        catalog.image_ready.connect(lambda *_:self.results.viewport().update())
        self.hide()
    def rows(self):return self.results.model().rows
    def set_results(self,rows,preserve=False):
        selected=self.results.currentIndex().row()
        old=self.rows()[selected].key if 0<=selected<len(self.rows()) else None
        self.results.model().replace(rows)
        at=next((i for i,row in enumerate(rows) if row.key==old),0) if preserve else 0
        if rows:self.results.setCurrentIndex(self.results.model().index(at,0))
        self.catalog.request_icons(rows);self.height_changed.emit();self.layout_contents()
    def preferred_height(self):return PADDING*3+SEARCH+max(ROW,min(self.max_rows,len(self.rows()))*(ROW+GAP)-GAP)
    def resizeEvent(self,event):self.layout_contents()
    def layout_contents(self):
        if not hasattr(self,'results'):return
        height=max(ROW,min(self.max_rows,len(self.rows()))*(ROW+GAP)-GAP)
        margin=round(self.morph_margin)
        self.search.setGeometry(margin,self.height()-margin-SEARCH if self.bottom else margin,self.width()-2*margin,SEARCH)
        self.results.setGeometry(PADDING,PADDING if self.bottom else margin*2+SEARCH,self.width()-2*PADDING,height)
    def eventFilter(self,obj,event):
        island=self.parentWidget()
        if not getattr(island,'launcher_active',False):return False
        owned=(obj is island or obj is island.windowHandle()
               or isinstance(obj,QWidget) and obj.window() is island)
        if not owned:return False
        if event.type()==QEvent.Type.ShortcutOverride and event.key()==Qt.Key.Key_Escape:
            event.accept();return True
        if event.type()==QEvent.Type.KeyPress:
            key=event.key()
            if key==Qt.Key.Key_Escape:self.dismissed.emit();return True
            # During activation an event can reach the window before Qt has
            # assigned a child focus receiver. Route that first text event to
            # the real editor, preserving layout, modifiers and composition.
            if (obj is not self.search.edit and not self.search.edit.hasFocus()
                    and event.text() and event.text().isprintable()):
                self.search.edit.setFocus(Qt.FocusReason.OtherFocusReason)
                copy=QKeyEvent(event.type(),key,event.modifiers(),event.text(),event.isAutoRepeat(),event.count())
                QApplication.sendEvent(self.search.edit,copy);return True
            delta=-1 if key in (Qt.Key.Key_Up,Qt.Key.Key_Backtab) else 1 if key in (Qt.Key.Key_Down,Qt.Key.Key_Tab) else 0
            if delta:
                count=len(self.rows())
                if count:self.results.setCurrentIndex(self.results.model().index((self.results.currentIndex().row()+delta)%count,0))
                return True
        elif event.type()==QEvent.Type.InputMethod and obj is not self.search.edit and not self.search.edit.hasFocus():
            self.search.edit.setFocus(Qt.FocusReason.OtherFocusReason)
            QApplication.sendEvent(self.search.edit,event);return True
        return super().eventFilter(obj,event)
    def _accept_index(self,index):
        if index.isValid():self.accepted.emit(self.rows()[index.row()])
    def accept_current(self):self._accept_index(self.results.currentIndex())
    def refresh_theme(self):self.search.theme();self.results.viewport().update()
    def effects(self,enabled,opacity):
        for effect in (self.effect,self.results_effect):effect.setEnabled(enabled);effect.setOpacity(opacity)
    def reveal(self,search_amount,body_amount,path):
        if self.effect.isEnabled():self.effect.setOpacity(search_amount)
        if self.results_effect.isEnabled():self.results_effect.setOpacity(body_amount)
        self.search.backdrop_strength=body_amount;self.search.update()
        if not self.parentWidget().animation.isActive():self.clearMask();return
        local=QPainterPath(path);local.translate(-self.x(),-self.y())
        self.setMask(QRegion(local.toFillPolygon().toPolygon()))
