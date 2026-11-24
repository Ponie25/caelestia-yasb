"""Common reveal, page, section and scrolling motion; no idle animation timer."""
import time
from PyQt6.QtCore import QObject,QPointF,QRectF,QTimer,QEvent,Qt,pyqtSignal,QEasingCurve
from PyQt6.QtGui import QPainter,QPainterPath,QRegion
from PyQt6.QtWidgets import QApplication,QWidget,QMenu,QComboBox,QDialog
from core.utils import motion_spec

def options(widget=None):
    from settings import DEFAULT_CONFIG_DIRECTORY
    parent=widget;preferences=None;root=DEFAULT_CONFIG_DIRECTORY
    while parent is not None:
        if hasattr(parent,'_collect_preferences') and getattr(parent,'_immediate_ready',False):
            preferences=parent._collect_preferences();root=parent.root;break
        parent=parent.parentWidget() if isinstance(parent,QWidget) else None
    return motion_spec.profile(root,preferences)
def curve(name='spatial',spec=None):
    spec=spec or options();a,b,c,d=spec['curves'][name]
    result=QEasingCurve(QEasingCurve.Type.BezierSpline)
    result.addCubicBezierSegment(QPointF(a,b),QPointF(c,d),QPointF(1,1));return result
def duration(kind='menu',widget=None):return motion_spec.milliseconds(options(widget),kind)

class Timeline(QObject):
    valueChanged=pyqtSignal(float)
    finished=pyqtSignal()
    def __init__(self,parent=None):
        super().__init__(parent);self.value=0.;self.timer=QTimer(self);self.timer.setTimerType(Qt.TimerType.PreciseTimer);self.timer.timeout.connect(self._tick)
    def start(self,end,ms,spec,start=None):
        self.timer.stop();self.origin=self.value if start is None else float(start);self.value=self.origin;self.end=float(end);self.ms=max(0,ms);self.started=time.perf_counter()
        if not ms:self.value=self.end;self.valueChanged.emit(self.value);self.finished.emit();return
        self.timer.setInterval(max(4,round(1000/spec['fps'])));self.timer.start();self.valueChanged.emit(self.value)
    def stop(self):self.timer.stop()
    def _tick(self):
        if not self.timer.isActive():return
        t=min(1.,(time.perf_counter()-self.started)*1000/self.ms)
        self.value=self.origin+(self.end-self.origin)*t;self.valueChanged.emit(self.value)
        if t>=1:self.timer.stop();self.finished.emit()

class WindowReveal(QObject):
    finished=pyqtSignal(bool)
    def __init__(self,widget,kind='popup'):
        super().__init__(widget);self.widget=widget;self.kind=kind;self.timeline=Timeline(self);self.timeline.valueChanged.connect(self._frame);self.timeline.finished.connect(self._done);self.closing=False;self.original_mask=None
    def open(self,alignment='left',direction='down',resume=False):
        self.spec=options(self.widget);self.spatial=curve('spatial',self.spec);self.effects=curve('effects',self.spec);self.alignment=alignment;self.direction=direction;self.closing=False
        if self.original_mask is None:self.original_mask=self.widget.mask()
        start=self.timeline.value if resume else 0.
        self.timeline.start(1.,motion_spec.milliseconds(self.spec,self.kind)*max(.15,1-start),self.spec,start)
    def close(self):
        self.closing=True;spec=options(self.widget);self.spec=spec
        self.timeline.start(0.,motion_spec.milliseconds(spec,'close')*max(.15,self.timeline.value),spec)
    def _frame(self,value):
        t=max(0.,min(1.,value));w,h=self.widget.width(),self.widget.height()
        if self.kind!='dialog' and self.spec['enabled'] and t<1:
            header=max(0.,min(1.,self.spatial.valueForProgress(min(1.,t/.7)**2)))
            body=max(0.,min(1.,self.spatial.valueForProgress(max(0.,(t-.24)/.76)**2)))
            start_w=min(w,max(56,min(140,w*.35)));start_h=min(h,28.)
            width=start_w+(w-start_w)*header
            height=start_h+(min(h,56.)-start_h)*header+max(0,h-56)*body
            x=w-width if self.alignment=='right' else (w-width)/2 if self.alignment=='center' else 0
            y=h-height if self.direction=='up' else 0
            path=QPainterPath();path.addRoundedRect(QRectF(x,y,max(1,width),max(1,height)),min(14,height/2),min(14,height/2))
            self.widget.setMask(QRegion(path.toFillPolygon().toPolygon()))
        else:self._restore_mask()
        self.widget.setWindowOpacity(max(.01,self.effects.valueForProgress(min(1.,t/.68))))
    def _restore_mask(self):
        if self.original_mask is not None and not self.original_mask.isEmpty():self.widget.setMask(self.original_mask)
        else:self.widget.clearMask()
    def _done(self):
        if not self.closing:self._restore_mask();self.widget.setWindowOpacity(1.)
        self.finished.emit(self.closing)
    def stop(self):
        self.timeline.stop();self._restore_mask();self.widget.setWindowOpacity(1.);self.original_mask=None

class MenuMotionFilter(QObject):
    def __init__(self,app):super().__init__(app);self.windows={}
    def eventFilter(self,obj,event):
        if not isinstance(obj,QWidget) or not obj.isWindow():return False
        kind='dialog' if isinstance(obj,QDialog) and obj.objectName()=='BarSettings' else 'menu' if isinstance(obj,QMenu) or obj.metaObject().className()=='QComboBoxPrivateContainer' else None
        if kind is None:return False
        if event.type()==QEvent.Type.Show:
            if not options(obj)['enabled']:
                if obj in self.windows:self.windows[obj].stop()
                obj.setWindowOpacity(1.);return False
            if obj not in self.windows:
                self.windows[obj]=WindowReveal(obj,kind);obj.destroyed.connect(lambda _,key=obj:self.windows.pop(key,None))
            obj.setWindowOpacity(.01);QTimer.singleShot(0,lambda obj=obj:self._start(obj))
        elif event.type()==QEvent.Type.Hide and obj in self.windows:self.windows[obj].stop()
        return False
    def _start(self,obj):
        try:
            if not obj.isVisible():return
            parent=obj.parentWidget();direction='up' if parent and obj.y()<parent.mapToGlobal(parent.rect().topLeft()).y() else 'down'
            self.windows[obj].open('right' if parent and obj.x()<parent.mapToGlobal(parent.rect().center()).x()-obj.width()/2 else 'left',direction)
        except RuntimeError:pass
def install_menu_motion(app):
    if not hasattr(app,'_yasb_menu_motion'):
        app._yasb_menu_motion=MenuMotionFilter(app);app.installEventFilter(app._yasb_menu_motion)

class PageOverlay(QWidget):
    def __init__(self,stack):
        super().__init__(stack);self.stack=stack;self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground);self.timeline=Timeline(self);self.timeline.valueChanged.connect(lambda _:self.update());self.timeline.finished.connect(self.hide);self.hide()
    def begin(self,image,direction=1):
        self.image=image;self.direction=direction;self.spec=options(self.stack);self.ease=curve('effects',self.spec)
        if not self.spec['enabled']:self.timeline.stop();self.hide();return
        self.setGeometry(self.stack.rect());self.show();self.raise_();self.timeline.start(1.,motion_spec.milliseconds(self.spec,'page'),self.spec,0.)
    def paintEvent(self,event):
        t=self.ease.valueForProgress(self.timeline.value);p=QPainter(self);p.setOpacity(1-t);p.drawPixmap(round(-12*t*self.direction),0,self.image);p.end()

class SectionReveal(QObject):
    def __init__(self,button,body):
        super().__init__(body);self.body=body;self.button=button;self.timeline=Timeline(self);self.timeline.valueChanged.connect(self._frame);self.timeline.finished.connect(self._done);button.toggled.connect(self.start)
    def start(self,opened):
        spec=options(self.body);self.ease=curve('spatial',spec);self.opened=opened
        current=self.body.height() if self.body.isVisible() else 0
        self.body.setVisible(True);self.body.layout().activate();self.target=max(1,self.body.layout().sizeHint().height())
        self.origin=current;self.end=self.target if opened else 0
        self.timeline.start(1.,motion_spec.milliseconds(spec,'section'),spec,0.)
    def _frame(self,t):self.body.setMaximumHeight(max(0,round(self.origin+(self.end-self.origin)*self.ease.valueForProgress(t))))
    def _done(self):
        self.body.setVisible(self.opened);self.body.setMaximumHeight(16777215 if self.opened else 0)

class SmoothScroll(QObject):
    def __init__(self,area):
        super().__init__(area);self.area=area;self.timeline=Timeline(self);self.timeline.valueChanged.connect(self._frame);area.viewport().installEventFilter(self);area.verticalScrollBar().sliderPressed.connect(self.timeline.stop)
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Hide:
            self.timeline.stop();return False
        if event.type()!=QEvent.Type.Wheel:return False
        if event.pixelDelta().y():self.timeline.stop();return False
        if not event.angleDelta().y():return False
        bar=self.area.verticalScrollBar();spec=options(self.area)
        if not spec['enabled'] or bar.maximum()<=0:return False
        target=getattr(self,'end',bar.value()) if self.timeline.timer.isActive() else bar.value()
        self.origin=bar.value();self.end=max(bar.minimum(),min(bar.maximum(),target-event.angleDelta().y()/120*bar.singleStep()*3))
        self.ease=curve('effects',spec);self.timeline.start(1.,motion_spec.milliseconds(spec,'control'),spec,0.);event.accept();return True
    def _frame(self,t):self.area.verticalScrollBar().setValue(round(self.origin+(self.end-self.origin)*self.ease.valueForProgress(t)))
