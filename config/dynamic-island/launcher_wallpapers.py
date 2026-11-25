"""On-demand local wallpaper discovery and small bounded previews."""
from collections import OrderedDict
from pathlib import Path
import json,logging,os,queue,random,subprocess,threading,time
from PySide6.QtCore import QObject,QSize,Qt,Signal
from PySide6.QtGui import QImage,QImageReader
from launcher_windows import read_json,write_json

EXTENSIONS=frozenset(('.jpg','.jpeg','.png','.bmp','.webp'))
LIMIT=2000

def running_engine():
    import psutil
    for process in psutil.process_iter(['name','exe']):
        try:
            if (process.info['name'] or '').casefold() in ('wallpaper64.exe','wallpaper32.exe'):
                path=Path(process.info['exe'] or '')
                if path.is_file():return path
        except (OSError,psutil.Error):pass
    return None

def _project(directory):
    path=directory/'project.json'
    try:
        if path.stat().st_size>1024*1024:return None
        data=json.loads(path.read_text(encoding='utf-8-sig'));name=' '.join(str(data.get('title') or directory.name).split())[:180]
        preview=(directory/str(data.get('preview') or 'preview.jpg')).resolve()
        if not preview.is_relative_to(directory.resolve()) or preview.suffix.casefold() not in EXTENSIONS:preview=Path()
        return dict(path=str(path.resolve()),name=name,preview=str(preview) if preview.is_file() else '',engine=True)
    except (OSError,ValueError,TypeError,AttributeError):return None

def discover(directory,engine=None,cancel=lambda:False):
    roots=[(Path(directory),2)]
    if engine:
        base=Path(engine).parent
        roots.extend(((base/'projects/myprojects',1),(base.parent.parent/'workshop/content/431960',1)))
    found={};visited=0;scanned=0
    def visit(folder,depth):
        nonlocal visited,scanned
        if cancel() or len(found)>=LIMIT or visited>=5000 or scanned>=12000:return
        visited+=1
        project=_project(folder)
        if project:
            found[project['path']]=project;return
        try:
            with os.scandir(folder) as entries:
                for count,entry in enumerate(entries):
                    scanned+=1
                    if scanned>12000 or cancel() or len(found)>=LIMIT:break
                    if entry.is_symlink():continue
                    path=Path(entry.path)
                    if entry.is_file(follow_symlinks=False) and path.suffix.casefold() in EXTENSIONS:
                        key=str(path.resolve());found[key]=dict(path=key,name=path.stem,preview=key,engine=False)
                    elif depth and entry.is_dir(follow_symlinks=False):visit(path,depth-1)
        except OSError:pass
    for folder,depth in roots:visit(folder,depth)
    return sorted(found.values(),key=lambda item:item['name'].casefold())

class Wallpapers(QObject):
    changed=Signal()
    image_ready=Signal(str,QImage)
    preview_finished=Signal(int,str,QImage)
    indexed=Signal(int,object,object)
    def __init__(self,root):
        super().__init__();self.root=Path(root);self.directory=self.root.parent/'wallpapers';self.items=[];self.images=OrderedDict();self.pending=set()
        self.loading=False;self.loaded=False;self.engine=None;self.generation=0;self.closed=threading.Event();self.jobs=queue.Queue();self.worker=None
        state=read_json(self.root/'wallpaper-state.json',{});self.current=state.get('path','') if isinstance(state,dict) else ''
        self.indexed.connect(self._indexed);self.preview_finished.connect(self._image)
    def configure(self,directory):
        value=Path(directory) if directory else self.root.parent/'wallpapers'
        if value!=self.directory:
            self.directory=value;self.generation+=1;self.loaded=False;self.loading=False;self.items=[];self.images.clear();self.pending.clear()
    def ensure(self,force=False):
        if self.loading or self.closed.is_set() or self.loaded and not force:return
        if force:self.generation+=1;self.images.clear();self.pending.clear()
        self.loading=True;generation=self.generation
        def index():
            engine=None;items=[]
            try:
                engine=running_engine();items=discover(self.directory,engine,lambda:self.closed.is_set() or generation!=self.generation)
            except Exception:logging.warning('Could not read wallpaper library',exc_info=True)
            if not self.closed.is_set():self.indexed.emit(generation,items,engine)
        threading.Thread(target=index,daemon=True,name='launcher-wallpaper-index').start()
    def _indexed(self,generation,items,engine):
        if generation!=self.generation:return
        self.items=items;self.engine=engine;self.loading=False;self.loaded=True;self.changed.emit()
    def get(self,path):return next((item for item in self.items if item['path']==path),None)
    def random(self):
        choices=[item for item in self.items if item['path']!=self.current] or self.items
        return random.SystemRandom().choice(choices) if choices else None
    def remember(self,path):
        self.current=path
        try:write_json(self.root/'wallpaper-state.json',dict(path=path))
        except OSError:logging.debug('Could not save wallpaper selection',exc_info=True)
    def request_previews(self,rows):
        if self.worker is None:
            self.worker=threading.Thread(target=self._previews,daemon=True,name='launcher-wallpaper-previews');self.worker.start()
        for row in rows:
            if not row.preview:continue
            if row.key in self.images:self.images.move_to_end(row.key);continue
            if row.key in self.pending:continue
            self.pending.add(row.key);self.jobs.put((self.generation,row.key,row.preview))
    def _image(self,generation,key,image):
        if generation!=self.generation:return
        self.pending.discard(key);self.images[key]=image
        while len(self.images)>32:self.images.popitem(last=False)
        self.image_ready.emit(key,image)
    def _previews(self):
        while not self.closed.is_set():
            job=self.jobs.get()
            if job is None:return
            generation,key,path=job
            if generation!=self.generation:continue
            image=QImage();reader=None
            try:
                reader=QImageReader(path);reader.setAutoTransform(True);size=reader.size()
                if size.isValid() and size.width()*size.height()<=24000000:
                    reader.setScaledSize(size.scaled(QSize(320,180),Qt.AspectRatioMode.KeepAspectRatio));image=reader.read()
            except (OSError,RuntimeError):pass
            finally:del reader
            if not self.closed.is_set() and generation==self.generation:self.preview_finished.emit(generation,key,image)
    def stop(self):self.closed.set();self.jobs.put(None)

def apply_wallpaper(item,engine=None):
    path=Path(item['path'])
    if not path.is_file():raise OSError('Hình nền không còn ở vị trí cũ.')
    engine=running_engine() or engine
    if item.get('engine'):
        if not engine or not Path(engine).is_file():raise OSError('Mở Wallpaper Engine trước khi chọn project này.')
        result=subprocess.run([str(engine),'-control','openWallpaper','-file',str(path)],capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise OSError('Wallpaper Engine chưa nhận được hình nền.')
        return
    if path.suffix.casefold() not in EXTENSIONS:raise ValueError('Định dạng ảnh không được hỗ trợ.')
    from comtypes import COMMETHOD,GUID,HRESULT,IUnknown,CoInitialize,CoUninitialize
    from comtypes.client import CreateObject
    from ctypes import c_wchar_p
    class DesktopWallpaper(IUnknown):
        _iid_=GUID('{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}')
        _methods_=[COMMETHOD([],HRESULT,'SetWallpaper',(['in'],c_wchar_p,'monitorID'),(['in'],c_wchar_p,'wallpaper'))]
    CoInitialize()
    try:
        desktop=CreateObject('{C2CF3110-460E-4FC1-B9D0-8A1C0C9CC4BD}',interface=DesktopWallpaper)
        desktop.SetWallpaper(None,str(path));del desktop
    finally:CoUninitialize()
    if engine:
        result=subprocess.run([str(engine),'-control','stop'],capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise OSError('Đã đặt ảnh Windows nhưng chưa dừng được Wallpaper Engine.')
