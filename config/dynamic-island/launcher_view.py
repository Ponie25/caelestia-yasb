"""Caelestia launcher presentation adapted to an Island on a horizontal bar.

Reference: caelestia-dots/shell 5cbf60e7, modules/launcher and SearchBar.qml.
57px rows, 8px gaps, 16px padding, full search radius, 16px selection radius.
The top-bar version mirrors the original bottom-anchored search vertically.
"""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QAbstractListModel,QEvent,QModelIndex,QPointF,QRectF,QSize,Qt,QVariantAnimation,Signal,QEasingCurve
from PySide6.QtGui import QColor,QCursor,QFont,QFontDatabase,QIcon,QKeyEvent,QPainter,QPainterPath,QPalette,QPen,QRegion
from PySide6.QtWidgets import QApplication,QAbstractItemView,QGraphicsOpacityEffect,QHBoxLayout,QLabel,QLineEdit,QListView,QPushButton,QStyledItemDelegate,QWidget
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
    'palette':'<path d="M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 1-4h-1a1.5 1.5 0 0 1 0-3h3a5 5 0 0 0 0-10z"/><path d="M7 8h.01M11 6h.01M16 8h.01M6 13h.01"/>',
    'image':'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 3-3 6 6"/>',
    'dice':'<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M7 7h.01M17 7h.01M12 12h.01M7 17h.01M17 17h.01"/>',
    'sun':'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
    'moon':'<path d="M20 15A8 8 0 0 1 9 4a8 8 0 1 0 11 11z"/>',
    'lock':'<rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
    'power':'<path d="M12 2v9m-6-6a9 9 0 1 0 12 0"/>',
    'restart':'<path d="M20 7V3m0 4h-4M4 17v4m0-4h4M20 7A8 8 0 0 0 6 5m-2 12a8 8 0 0 0 14 2"/>',
    'logout':'<path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5m5-13 5 5-5 5m5-5H9"/>',
    'check':'<path d="m5 12 4 4L19 6"/>',
    'star':'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
    'star-filled':'<path fill="currentColor" d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
}
@lru_cache(maxsize=96)
def svg(name,color):
    return QSvgRenderer(('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="'+color+'" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+PATHS.get(name,PATHS['apps']).replace('currentColor',color)+'</svg>').encode())
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
    def sizeHint(self,option,index):return QSize(192,158) if self.view.gallery else QSize(600,ROW+GAP)
    def paint(self,painter,option,index):
        row=self.view.model().rows[index.row()];rect=QRectF(option.rect);rect.setHeight(ROW)
        painter.save();painter.setRenderHints(QPainter.RenderHint.Antialiasing|QPainter.RenderHint.SmoothPixmapTransform)
        if self.view.gallery:
            self._wallpaper(painter,rect,row,index.row());painter.restore();return
        image=self.catalog.images.get(row.key)
        art=QRectF(rect.left()+12,rect.center().y()-18,36,36)
        if row.swatch:
            clip=QPainterPath();clip.addEllipse(art);painter.save();painter.setClipPath(clip)
            painter.fillRect(art,QColor(row.swatch[0]));painter.fillRect(QRectF(art.center().x(),art.top(),art.width()/2,art.height()),QColor(row.swatch[-1]));painter.restore()
        elif image is not None and not image.isNull():painter.drawImage(art,image)
        else:glyph(painter,row.glyph,art.adjusted(4,4,-4,-4),palette.MUTED)
        left=rect.left()+60;available=max(0,rect.width()-left-(46 if row.current else 16))
        if row.current:glyph(painter,'check',QRectF(rect.right()-34,rect.center().y()-10,20,20),palette.MAUVE)
        painter.setFont(font(14));painter.setPen(QColor(palette.TEXT))
        painter.drawText(QRectF(left,rect.top()+9,available,21),Qt.AlignmentFlag.AlignVCenter,painter.fontMetrics().elidedText(row.title,Qt.TextElideMode.ElideRight,round(available)))
        painter.setFont(font(12));painter.setPen(QColor(palette.MUTED))
        painter.drawText(QRectF(left,rect.top()+30,available,18),Qt.AlignmentFlag.AlignVCenter,painter.fontMetrics().elidedText(row.detail,Qt.TextElideMode.ElideRight,round(available)))
        painter.restore()

    def _wallpaper(self,painter,rect,row,at):
        rect.setWidth(184);rect.setHeight(150)
        amount=max(0.,1-abs(self.view.highlight-at*192)/192);scale=.86+.14*amount
        painter.translate(rect.center());painter.scale(scale,scale);painter.translate(-rect.center())
        art=QRectF(rect.left()+10,rect.top()+10,164,92)
        path=QPainterPath();path.addRoundedRect(art,12,12);painter.save();painter.setClipPath(path);painter.fillRect(art,QColor(palette.SURFACE))
        image=self.view.wallpapers.images.get(row.key) if self.view.wallpapers else None
        if image is not None and not image.isNull():
            source=QRectF(image.rect());ratio=art.width()/art.height()
            if source.width()/source.height()>ratio:source.setWidth(source.height()*ratio);source.moveCenter(QRectF(image.rect()).center())
            else:source.setHeight(source.width()/ratio);source.moveCenter(QRectF(image.rect()).center())
            painter.drawImage(art,image,source)
        else:glyph(painter,row.glyph,QRectF(art.center().x()-18,art.center().y()-18,36,36),palette.MUTED)
        painter.restore()
        if row.kind=='wallpaper' and row.favorite:
            badge=QRectF(art.right()-27,art.top()+4,24,24);color=QColor(palette.BASE);color.setAlphaF(.94)
            painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(color);painter.drawEllipse(badge)
            glyph(painter,'star-filled' if row.favorite else 'star',badge.adjusted(4,4,-4,-4),palette.MAUVE if row.favorite else palette.TEXT)
        painter.setFont(font(12));painter.setPen(QColor(palette.TEXT))
        painter.drawText(QRectF(rect.left()+10,rect.top()+108,164,20),Qt.AlignmentFlag.AlignCenter,painter.fontMetrics().elidedText(row.title,Qt.TextElideMode.ElideRight,164))
        painter.setFont(font(10));painter.setPen(QColor(palette.MUTED))
        painter.drawText(QRectF(rect.left()+10,rect.top()+129,164,16),Qt.AlignmentFlag.AlignCenter,painter.fontMetrics().elidedText(row.detail,Qt.TextElideMode.ElideRight,164))


class Results(QListView):
    def __init__(self,catalog,parent):
        super().__init__(parent);self.gallery=False;self.wallpapers=parent.wallpapers;self.setModel(Model());self.setItemDelegate(Delegate(self,catalog));self.setAccessibleName('Kết quả tìm kiếm')
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True);self.setUniformItemSizes(True);self.setFrameShape(QListView.Shape.NoFrame)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setStyleSheet('QListView {background:transparent;border:0;outline:0;padding:0;} QListView::item {background:transparent;}')
        self.viewport().setAutoFillBackground(False);self.highlight=0.
        self.animation=QVariantAnimation(self);self.animation.setDuration(350);self.animation.setEasingCurve(curve('spatial'))
        self.animation.valueChanged.connect(self._move_highlight)
        self.scroll_animation=QVariantAnimation(self);self.scroll_animation.setEasingCurve(curve('spatial'));self.scroll_animation.valueChanged.connect(lambda value:self.horizontalScrollBar().setValue(round(value)))
        self.last_mouse=QCursor.pos();self.motion_ms=350
        self.selectionModel().currentChanged.connect(self._selected)
    def _move_highlight(self,value):self.highlight=float(value);self.viewport().update()
    def _selected(self,index,previous):
        if not index.isValid():return
        self.animation.setDuration(self.motion_ms)
        self.animation.stop();self.animation.setStartValue(self.highlight);self.animation.setEndValue(float(max(0,index.row())*(192 if self.gallery else ROW+GAP)));self.animation.start()
        if self.gallery:
            self.scrollTo(index,QAbstractItemView.ScrollHint.PositionAtCenter)
            if self.wallpapers:
                rows=self.model().rows;at=index.row();near=[at,at-1,at+1,at-2,at+2]
                self.wallpapers.request_previews([rows[i] for i in near if 0<=i<len(rows)])
    def scrollTo(self,index,hint=QAbstractItemView.ScrollHint.EnsureVisible):
        if not getattr(self,'gallery',False):super().scrollTo(index,hint);return
        if not index.isValid():return
        bar=self.horizontalScrollBar();target=max(0,min(bar.maximum(),index.row()*192+92-self.viewport().width()/2))
        self.scroll_animation.stop();self.scroll_animation.setDuration(self.motion_ms);self.scroll_animation.setStartValue(float(bar.value()));self.scroll_animation.setEndValue(float(target));self.scroll_animation.start()
    def move_selection(self,delta):
        self.last_mouse=QCursor.pos();count=self.model().rowCount()
        if count:self.setCurrentIndex(self.model().index((self.currentIndex().row()+delta)%count,0))
    def mouseMoveEvent(self,event):
        position=event.globalPosition().toPoint()
        if (position-self.last_mouse).manhattanLength()>2:
            self.last_mouse=position;index=self.indexAt(event.position().toPoint())
            if index.isValid():self.setCurrentIndex(index)
        super().mouseMoveEvent(event)
    def set_gallery(self,enabled):
        if self.gallery==enabled:return
        self.gallery=enabled;self.animation.stop();self.scroll_animation.stop();self.highlight=0.
        self.setFlow(QListView.Flow.LeftToRight if enabled else QListView.Flow.TopToBottom);self.setWrapping(False)
        self.setGridSize(QSize(192,158) if enabled else QSize());self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.horizontalScrollBar().setValue(0);self.verticalScrollBar().setValue(0)
    def wheelEvent(self,event):
        if self.gallery and event.angleDelta().y():
            self.move_selection(-1 if event.angleDelta().y()>0 else 1)
            event.accept();return
        super().wheelEvent(event)
    def paintEvent(self,event):
        if self.currentIndex().isValid():
            painter=QPainter(self.viewport());painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            color=QColor(palette.TEXT);color.setAlphaF(.08);painter.setBrush(color);painter.setPen(Qt.PenStyle.NoPen)
            target=QRectF(self.highlight-self.horizontalScrollBar().value(),0,184,150) if self.gallery else QRectF(0,self.highlight-self.verticalScrollBar().value(),self.viewport().width(),ROW)
            painter.drawRoundedRect(target,16,16);painter.end()
        super().paintEvent(event)


class LauncherView(QWidget):
    query_changed=Signal(str)
    accepted=Signal(object)
    dismissed=Signal()
    height_changed=Signal()
    favorite_filter_changed=Signal(bool)
    wallpaper_refresh_requested=Signal()
    def __init__(self,parent,catalog):
        super().__init__(parent);self.catalog=catalog;self.wallpapers=getattr(parent,'wallpapers',None);self.bottom=False;self.max_rows=7;self.morph_margin=16.;self.search=Search(self);self.results=Results(catalog,self)
        self.effect=QGraphicsOpacityEffect(self.search);self.effect.setOpacity(0);self.search.setGraphicsEffect(self.effect)
        self.results_effect=QGraphicsOpacityEffect(self.results);self.results_effect.setOpacity(0);self.results.setGraphicsEffect(self.results_effect)
        self.search.edit.textChanged.connect(self.query_changed)
        QApplication.instance().installEventFilter(self);self.results.clicked.connect(self._accept_index)
        self.search.edit.returnPressed.connect(self.accept_current)
        self.wallpaper_mode=False;self.wallpaper_tools=QWidget(self);tools=QHBoxLayout(self.wallpaper_tools);tools.setContentsMargins(0,0,0,0);tools.setSpacing(6)
        self.favorites_button=QPushButton('Yêu thích');self.all_button=QPushButton('Tất cả')
        for button in (self.favorites_button,self.all_button):button.setCheckable(True);button.setFixedHeight(26);button.setFocusPolicy(Qt.FocusPolicy.NoFocus);button.setFont(font(11));tools.addWidget(button)
        self.favorites_button.clicked.connect(lambda:self.favorite_filter_changed.emit(True));self.all_button.clicked.connect(lambda:self.favorite_filter_changed.emit(False))
        self.wallpaper_info=QLabel('Lên/Xuống chọn · Enter đổi nền');hint_font=QFont('Segoe UI');hint_font.setPixelSize(11);self.wallpaper_info.setFont(hint_font);tools.addStretch();tools.addWidget(self.wallpaper_info)
        self.wallpaper_refresh=QPushButton();self.wallpaper_refresh.setFixedSize(28,26);self.wallpaper_refresh.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.wallpaper_refresh.setToolTip('Làm mới yêu thích và thư viện · Ctrl+R');self.wallpaper_refresh.setAccessibleName('Làm mới thư viện hình nền');self.wallpaper_refresh.clicked.connect(self.wallpaper_refresh_requested);tools.addWidget(self.wallpaper_refresh)
        self.wallpaper_refresh.setObjectName('wallpaperRefresh')
        self.tools_effect=QGraphicsOpacityEffect(self.wallpaper_tools);self.wallpaper_tools.setGraphicsEffect(self.tools_effect)
        self.wallpaper_tools.hide();self.refresh_theme()
        catalog.image_ready.connect(lambda *_:self.results.viewport().update())
        if self.wallpapers:self.wallpapers.image_ready.connect(lambda *_:self.results.viewport().update())
        self.hide()
    def rows(self):return self.results.model().rows
    def set_results(self,rows,preserve=False):
        selected=self.results.currentIndex().row()
        old=self.rows()[selected].key if 0<=selected<len(self.rows()) else None
        self.results.set_gallery(any(row.kind=='wallpaper' for row in rows));model=self.results.model()
        if [row.key for row in rows]==[row.key for row in model.rows]:
            model.rows=rows
            if rows:model.dataChanged.emit(model.index(0,0),model.index(len(rows)-1,0))
        else:model.replace(rows)
        at=next((i for i,row in enumerate(rows) if row.key==old),min(selected,max(0,len(rows)-1))) if preserve else next((i for i,row in enumerate(rows) if row.current),0) if self.results.gallery else 0
        if rows:self.results.setCurrentIndex(self.results.model().index(at,0))
        if self.wallpaper_mode:self.wallpaper_info.setText(f"{sum(row.kind=='wallpaper' for row in rows)} ảnh · Lên/Xuống chọn · Enter đổi")
        self.catalog.request_icons(rows)
        self.height_changed.emit();self.layout_contents()
    def set_wallpaper_mode(self,enabled,favorites_only=True,status=''):
        self.wallpaper_mode=enabled;self.wallpaper_tools.setVisible(enabled);self.favorites_button.setChecked(favorites_only);self.all_button.setChecked(not favorites_only)
        self.wallpaper_info.setToolTip(status)
    def body_height(self):return 158 if self.results.gallery else max(ROW,min(self.max_rows,len(self.rows()))*(ROW+GAP)-GAP)
    def preferred_height(self):return PADDING*3+SEARCH+self.body_height()+(32 if self.wallpaper_mode else 0)
    def resizeEvent(self,event):self.layout_contents()
    def layout_contents(self):
        if not hasattr(self,'results'):return
        height=self.body_height()
        margin=round(self.morph_margin)
        self.search.setGeometry(margin,self.height()-margin-SEARCH if self.bottom else margin,self.width()-2*margin,SEARCH)
        tools_y=PADDING+height if self.bottom else margin*2+SEARCH
        self.wallpaper_tools.setGeometry(PADDING,tools_y,self.width()-2*PADDING,28)
        self.results.setGeometry(PADDING,PADDING if self.bottom else margin*2+SEARCH+(32 if self.wallpaper_mode else 0),self.width()-2*PADDING,height)
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
            if self.wallpaper_mode and event.modifiers()&Qt.KeyboardModifier.ControlModifier:
                if key==Qt.Key.Key_R:self.wallpaper_refresh_requested.emit();return True
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
                self.results.move_selection(delta)
                return True
        elif event.type()==QEvent.Type.InputMethod and obj is not self.search.edit and not self.search.edit.hasFocus():
            self.search.edit.setFocus(Qt.FocusReason.OtherFocusReason)
            QApplication.sendEvent(self.search.edit,event);return True
        return super().eventFilter(obj,event)
    def _accept_index(self,index):
        if index.isValid():self.accepted.emit(self.rows()[index.row()])
    def accept_current(self):self._accept_index(self.results.currentIndex())
    def refresh_theme(self):
        self.search.theme();self.results.viewport().update()
        if hasattr(self,'wallpaper_tools'):
            self.wallpaper_tools.setStyleSheet('QPushButton {color:'+palette.MUTED+';background:transparent;border:0;border-radius:12px;padding:3px 9px;} QPushButton#wallpaperRefresh {padding:0;} QPushButton:checked {color:'+palette.TEXT+';background:'+palette.SURFACE2+';} QPushButton:hover {background:'+palette.SURFACE+';} QLabel {color:'+palette.MUTED+';background:transparent;}')
            from PySide6.QtGui import QPixmap
            pixmap=QPixmap(16,16);pixmap.fill(Qt.GlobalColor.transparent);p=QPainter(pixmap);glyph(p,'restart',QRectF(1,1,14,14),palette.MUTED);p.end();self.wallpaper_refresh.setIcon(QIcon(pixmap))
    def effects(self,enabled,opacity):
        for effect in (self.effect,self.results_effect,self.tools_effect):effect.setEnabled(enabled);effect.setOpacity(opacity)
    def reveal(self,search_amount,body_amount,path):
        if self.effect.isEnabled():self.effect.setOpacity(search_amount)
        if self.results_effect.isEnabled():self.results_effect.setOpacity(body_amount)
        if self.tools_effect.isEnabled():self.tools_effect.setOpacity(body_amount)
        self.search.backdrop_strength=body_amount;self.search.update()
        if not self.parentWidget().animation.isActive():self.clearMask();return
        local=QPainterPath(path);local.translate(-self.x(),-self.y())
        self.setMask(QRegion(local.toFillPolygon().toPolygon()))
