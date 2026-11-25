"""Compare DLLs in an owned, non-activating Qt scene; never capture the desktop.

Run with the installed Python runtime: benchmark_glass.py <install> <dll> <output-dir>
Each DLL must be measured in a fresh process. Results are not a gaming benchmark.
"""
from pathlib import Path
import ctypes,json,os,sys,time,faulthandler,threading,traceback
install=Path(sys.argv[1]).resolve();dll=Path(sys.argv[2]).resolve();output=Path(sys.argv[3]).resolve();output.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(install/'config/dynamic-island/runtime'))
faulthandler.enable();faulthandler.dump_traceback_later(20,repeat=True)
from PySide6.QtCore import Qt,QRectF,QTimer
from PySide6.QtGui import QColor,QPainter,QLinearGradient
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest
import psutil

app=QApplication([]);app.setQuitOnLastWindowClosed(False)
lib=ctypes.CDLL(str(dll))
lib.lg_create_wgc.argtypes=[ctypes.c_void_p,ctypes.c_int];lib.lg_create_wgc.restype=ctypes.c_void_p
lib.lg_set.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_float),ctypes.c_int,ctypes.POINTER(ctypes.c_float),ctypes.c_int]
lib.lg_info.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_long),ctypes.POINTER(ctypes.c_long),ctypes.POINTER(ctypes.c_int)]
lib.lg_error.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_long)]
lib.lg_suspend.argtypes=[ctypes.c_void_p,ctypes.c_int];lib.lg_set_fps.argtypes=[ctypes.c_void_p,ctypes.c_int]
lib.lg_dump.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p];lib.lg_dump.restype=ctypes.c_int
lib.lg_destroy.argtypes=[ctypes.c_void_p];lib.lg_shutdown.argtypes=[]
if hasattr(lib,'lg_resource_info'):
    lib.lg_resource_info.argtypes=[ctypes.POINTER(ctypes.c_uint),ctypes.POINTER(ctypes.c_uint),ctypes.POINTER(ctypes.c_ulonglong),ctypes.POINTER(ctypes.c_ulonglong)]
process=psutil.Process();rows=[];context=None
flags=Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.WindowDoesNotAcceptFocus
class Backdrop(QWidget):
    phase=0
    def paintEvent(self,event):
        p=QPainter(self);g=QLinearGradient(0,0,self.width(),self.height());g.setColorAt(0,QColor('#201a2c'));g.setColorAt(.58,QColor('#a2344b'));g.setColorAt(1,QColor('#f2d9b8'));p.fillRect(self.rect(),g)
        p.setPen(QColor('#08070e'))
        for x in range(-100,self.width()+100,44):p.drawLine(x+self.phase,0,x-100+self.phase,self.height())
        p.end()
    def advance(self):self.phase=(self.phase+1)%44;self.update()
back=Backdrop(None,flags);back.setWindowTitle('Caelestia owned benchmark backdrop');back.resize(1000,720)
class Front(QWidget):
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor(0,0,0,1));painter.end()
front=Front(None,flags);front.setWindowTitle('Caelestia owned benchmark surface');front.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground);front.resize(728,456 if os.environ.get('GLASS_BENCH_OPEN')=='1' else 32)
geo=app.primaryScreen().availableGeometry();back.move(geo.center().x()-500,geo.center().y()-360);front.move(back.x()+136,back.y()+132)
side=Backdrop(None,flags);side.setWindowTitle('Caelestia owned off-pill layer');side.resize(180,180);side.move(front.x()+5,front.y()+5)
back.show();side.show();front.show();front.raise_();QTest.qWait(500)
scale=front.devicePixelRatioF();timer=QTimer();timer.setInterval(16);timer.timeout.connect(back.advance)
def info():
    frame=ctypes.c_long();update=ctypes.c_long();micros=ctypes.c_int()
    lib.lg_info(context,ctypes.byref(frame),ctypes.byref(update),ctypes.byref(micros))
    return frame.value,update.value,micros.value
def resources():
    if not hasattr(lib,'lg_resource_info'):return None
    caps=ctypes.c_uint();dup=ctypes.c_uint();copies=ctypes.c_ulonglong();pools=ctypes.c_ulonglong()
    lib.lg_resource_info(ctypes.byref(caps),ctypes.byref(dup),ctypes.byref(copies),ctypes.byref(pools))
    return dict(captures=caps.value,desktop_duplications=dup.value,capture_copies_bytes=copies.value,pool_frame_estimate_bytes=pools.value)
def memory(label):
    m=process.memory_info();row=dict(stage=label,rss_mib=m.rss/2**20,private_commit_mib=m.private/2**20,threads=process.num_threads(),native=resources());rows.append(row);print(json.dumps(row),flush=True)
def shape(width,height):
    params=(ctypes.c_float*13)(1.45,7.,3.5,.003,.85,.04,.15,0,.10,2.,.15,scale,1.)
    data=(ctypes.c_float*12)(364*scale,height/2*scale,width/2*scale,height/2*scale,min(19,height/2)*scale,1,1,0,.025,.018,.025,.32)
    lib.lg_set(context,params,13,data,1)
def ready():
    stage=ctypes.c_int();hr=ctypes.c_long();lib.lg_error(context,ctypes.byref(stage),ctypes.byref(hr))
    assert stage.value==0,(stage.value,hex(hr.value&0xffffffff))
    assert info()[0]>0,'No native frame produced'
def shutdown(value):
    def close():
        if value:lib.lg_destroy(value)
        lib.lg_shutdown()
    thread=threading.Thread(target=close,daemon=True);thread.start();started=time.perf_counter()
    while thread.is_alive() and time.perf_counter()-started<8:QTest.qWait(20)
    assert not thread.is_alive(),'Native shutdown exceeded eight seconds'
def dump(name):
    result=[];thread=threading.Thread(target=lambda:result.append(lib.lg_dump(context,str(output/name))),daemon=True)
    thread.start();started=time.perf_counter()
    while thread.is_alive() and time.perf_counter()-started<4:QTest.qWait(20)
    assert result and result[0],('Could not dump owned shader output',name)
try:
    memory('qt_base')
    context=lib.lg_create_wgc(int(front.winId()),1);assert context
    lib.lg_set_fps(context,120);shape(712,456) if front.height()>32 else shape(116,28);QTest.qWait(1800);ready();memory('initial')
    start=info();cpu=process.cpu_times();began=time.perf_counter();QTest.qWait(1400);elapsed=time.perf_counter()-began;end=info();after=process.cpu_times()
    static_frames=end[0]-start[0];print('Static frames',static_frames,flush=True);assert static_frames<=3,('Static backdrop is repainting',static_frames)
    idle_cpu=100*((after.user+after.system)-(cpu.user+cpu.system))/elapsed/psutil.cpu_count()
    dump('closed.bmp')
    if os.environ.get('GLASS_BENCH_SINGLE')!='1':front.resize(728,456);shape(712,456)
    QTest.qWait(1000);ready();memory('open' if front.height()>32 else 'closed')
    dump('open.bmp')
    timer.start();start=info();cpu=process.cpu_times();began=time.perf_counter();QTest.qWait(int(float(os.environ.get('GLASS_BENCH_SECONDS','1.8'))*1000));elapsed=time.perf_counter()-began;end=info();after=process.cpu_times();timer.stop()
    animated_frames=end[0]-start[0];assert animated_frames>=8,('Animated backdrop stopped updating',animated_frames)
    active_cpu=100*((after.user+after.system)-(cpu.user+cpu.system))/elapsed/psutil.cpu_count()
    for _ in range(0 if os.environ.get('GLASS_BENCH_SINGLE')=='1' else 3):
        front.resize(728,32);shape(116,28);QTest.qWait(170)
        front.resize(728,456);shape(712,456);QTest.qWait(170)
    QTest.qWait(700);ready();memory('after_cycles')
    lib.lg_suspend(context,1);QTest.qWait(600);start=info();QTest.qWait(350);assert info()[0]==start[0]
    lib.lg_suspend(context,0);QTest.qWait(1000);ready();assert info()[0]>start[0]
    diagnostic=resources()
    if diagnostic is not None:assert diagnostic['desktop_duplications']==0,diagnostic
    value,context=context,None;shutdown(value);QTest.qWait(300);memory('shutdown')
    if resources() is not None:assert resources()==dict(captures=0,desktop_duplications=0,capture_copies_bytes=0,pool_frame_estimate_bytes=0)
    result=dict(rows=rows,static_frames=static_frames,animated_frames=animated_frames,animated_seconds=elapsed,resize_cycles=0 if os.environ.get('GLASS_BENCH_SINGLE')=='1' else 3,idle_cpu_total_pct=idle_cpu,active_cpu_total_pct=active_cpu,scale=scale,logical_cpus=psutil.cpu_count(),validation='static redraw, live updates, selected resize mode, suspend/resume and shutdown passed')
    (output/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)
except BaseException:
    traceback.print_exc();sys.stdout.flush();raise
finally:
    timer.stop()
    if context:shutdown(context)
    front.hide();side.hide();back.hide()
