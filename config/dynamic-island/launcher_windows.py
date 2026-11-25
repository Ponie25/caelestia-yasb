"""Windows app discovery, lazy icons and the explicitly assigned Alt+Space key."""
import ctypes
from collections import OrderedDict
from ctypes import wintypes as w
import json
import logging
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from PySide6.QtCore import QObject,Signal
from PySide6.QtGui import QImage
from launcher_core import normalized


def write_json(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temporary.replace(path)


def read_json(path,fallback):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return fallback


def known_folder(name):
    import uuid
    guid=uuid.UUID({'downloads':'374DE290-123F-4565-9164-39C4925E467B','documents':'FDD39AD0-238F-46AF-ADB4-6C85480369C7'}[name])
    data=(ctypes.c_byte*16).from_buffer_copy(guid.bytes_le);result=ctypes.c_void_p()
    shell=ctypes.windll.shell32;shell.SHGetKnownFolderPath.argtypes=[ctypes.c_void_p,w.DWORD,w.HANDLE,ctypes.POINTER(ctypes.c_void_p)]
    if shell.SHGetKnownFolderPath(ctypes.byref(data),0,None,ctypes.byref(result))!=0:raise OSError('Known Folder unavailable')
    try:return Path(ctypes.wstring_at(result))
    finally:
        ctypes.windll.ole32.CoTaskMemFree.argtypes=[ctypes.c_void_p];ctypes.windll.ole32.CoTaskMemFree(result)


class Catalog(QObject):
    ICON_CACHE_LIMIT = 64
    changed=Signal(object)
    image_ready=Signal(str,QImage)
    def __init__(self,root):
        super().__init__();self.root=Path(root);self.apps=[];self.images=OrderedDict();self.visible_icons=set();self.pending=set();self.closing=threading.Event()
        cached=read_json(self.root/'launcher-apps.json',[])
        if isinstance(cached,list):self.apps=[r for r in cached if isinstance(r,dict) and all(isinstance(r.get(k),str) for k in ('id','name','target'))][:3000]
        history=read_json(self.root/'launcher-history.json',{})
        self.history={k:v for k,v in history.items() if isinstance(v,dict) and type(v.get('count')) is int and type(v.get('at')) in (int,float)} if isinstance(history,dict) else {}
        self.icons=queue.Queue();self.image_ready.connect(self._received)
        self.worker=threading.Thread(target=self._index,name='launcher-catalog',daemon=True)
        self.icon_worker=threading.Thread(target=self._icons,name='launcher-icons',daemon=True)
    def start(self):self.worker.start();self.icon_worker.start()
    def stop(self):
        self.closing.set();self.icons.put(None)
    def _publish(self,rows):
        unique={}
        for row in rows:
            name=normalized(row['name'])
            if name not in unique:unique[name]=row
        result=sorted(unique.values(),key=lambda r:normalized(r['name']))
        if not self.closing.is_set():self.changed.emit(result)
        return result
    def _index(self):
        rows=[]
        for base in (Path(os.environ.get('APPDATA',''))/'Microsoft/Windows/Start Menu/Programs',Path(os.environ.get('PROGRAMDATA',r'C:\ProgramData'))/'Microsoft/Windows/Start Menu/Programs'):
            if not base.is_dir():continue
            for path in base.rglob('*'):
                if self.closing.is_set():return
                if path.suffix.casefold() not in ('.lnk','.url','.appref-ms'):continue
                rows.append(dict(id=str(path),name=path.stem,target=str(path),description='Ứng dụng · '+path.parent.name))
        rows.append(dict(id='windows-explorer',name='File Explorer',target=str(Path(os.environ.get('WINDIR',r'C:\Windows'))/'explorer.exe'),description='Trình quản lý tệp'))
        self._publish(rows)
        powershell=Path(os.environ.get('WINDIR',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        try:
            completed=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-Command',
                '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); @(Get-StartApps | Select-Object Name,AppID) | ConvertTo-Json -Compress'],
                capture_output=True,encoding='utf-8-sig',errors='replace',timeout=18,creationflags=subprocess.CREATE_NO_WINDOW)
            entries=json.loads(completed.stdout) if completed.returncode==0 else []
            if isinstance(entries,dict):entries=[entries]
            for entry in entries:
                if not isinstance(entry,dict):continue
                name,app_id=entry.get('Name'),entry.get('AppID')
                if not isinstance(name,str) or not isinstance(app_id,str) or not name or not app_id:continue
                rows.append(dict(id='app:'+app_id,name=name,target='shell:AppsFolder\\'+app_id,description='Ứng dụng Windows'))
        except (OSError,ValueError,subprocess.TimeoutExpired):logging.info('Launcher using Start Menu catalog; optional AppsFolder enumeration unavailable')
        result=self._publish(rows)
        if not self.closing.is_set():
            try:write_json(self.root/'launcher-apps.json',result)
            except OSError:logging.warning('Could not cache launcher apps',exc_info=True)
    def accept(self,apps):self.apps=apps
    def remember(self,result):
        previous=self.history.get(result.key,{})
        self.history[result.key]={'count':min(100000,previous.get('count',0)+1),'at':time.time()}
        try:write_json(self.root/'launcher-history.json',self.history)
        except OSError:logging.warning('Could not save launcher usage',exc_info=True)
    def request_icons(self,results):
        results=tuple(results);self.visible_icons={result.key for result in results if result.kind=='app'}
        for result in results:
            if result.kind!='app':continue
            if result.key in self.images:self.images.move_to_end(result.key);continue
            if result.key in self.pending:continue
            self.pending.add(result.key);self.icons.put((result.key,result.value))
    def _received(self,key,image):
        self.pending.discard(key)
        self.images[key]=image
        self.images.move_to_end(key)
        while len(self.images)>self.ICON_CACHE_LIMIT:
            victim=next((key for key in self.images if key not in self.visible_icons),next(iter(self.images)))
            del self.images[victim]
    def _icons(self):
        shell=ctypes.WinDLL('shell32');ole=ctypes.WinDLL('ole32');user=ctypes.WinDLL('user32')
        class FileInfo(ctypes.Structure):
            _fields_=[('icon',w.HICON),('index',ctypes.c_int),('attributes',w.DWORD),('display',w.WCHAR*260),('type',w.WCHAR*80)]
        shell.SHGetFileInfoW.argtypes=[ctypes.c_void_p,w.DWORD,ctypes.POINTER(FileInfo),w.UINT,w.UINT];shell.SHGetFileInfoW.restype=ctypes.c_size_t
        shell.SHParseDisplayName.argtypes=[w.LPCWSTR,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p),w.DWORD,ctypes.c_void_p];shell.SHParseDisplayName.restype=ctypes.c_long
        ole.CoTaskMemFree.argtypes=[ctypes.c_void_p];user.DestroyIcon.argtypes=[w.HICON]
        hr=ole.CoInitializeEx(None,2)
        try:
            while not self.closing.is_set():
                task=self.icons.get()
                if task is None:break
                key,target=task;info=FileInfo();pidl=ctypes.c_void_p();image=QImage()
                try:
                    if target.startswith('shell:'):
                        if shell.SHParseDisplayName(target,None,ctypes.byref(pidl),0,None)<0:continue
                        pointer=pidl;flags=0x100|0x8
                    else:pointer=ctypes.cast(ctypes.c_wchar_p(target),ctypes.c_void_p);flags=0x100
                    if shell.SHGetFileInfoW(pointer,0,ctypes.byref(info),ctypes.sizeof(info),flags) and info.icon:
                        image=QImage.fromHICON(int(info.icon)).copy()
                except Exception:logging.debug('App icon unavailable',exc_info=True)
                finally:
                    if info.icon:user.DestroyIcon(info.icon)
                    if pidl:ole.CoTaskMemFree(pidl)
                    if not self.closing.is_set():self.image_ready.emit(key,image)
        finally:
            if hr>=0:ole.CoUninitialize()


class Shortcut(QObject):
    activated=Signal()
    status=Signal(str)
    def __init__(self,target=0):
        super().__init__();self.target=target;self.active=False;self.thread_id=None;self.ready=threading.Event();self.closing=threading.Event()
        self.thread=threading.Thread(target=self._run,name='launcher-alt-space',daemon=True)
    def _trigger(self):
        if not self.target:self.activated.emit();return
        from launcher_focus import toggle_sync
        started=time.perf_counter()
        if toggle_sync(self.target):logging.info('Launcher keyboard handoff confirmed in %.1f ms',(time.perf_counter()-started)*1000)
        else:self.status.emit('Không chuyển được bàn phím sang Island. Hãy bấm nút Search để mở lại.')
    def start(self):
        if self.thread.is_alive():return
        self.closing.clear();self.ready.clear();self.thread_id=None
        self.thread=threading.Thread(target=self._run,name='launcher-alt-space',daemon=True);self.thread.start()
    def stop(self):
        self.closing.set()
        if self.thread_id:ctypes.windll.user32.PostThreadMessageW(self.thread_id,0x12,0,0)
        if self.thread.is_alive():self.thread.join(1.5)
    def _run(self):
        user=ctypes.WinDLL('user32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        user.GetMessageW.argtypes=[ctypes.POINTER(w.MSG),w.HWND,w.UINT,w.UINT];user.GetMessageW.restype=ctypes.c_int
        msg=w.MSG();user.PeekMessageW(ctypes.byref(msg),None,0,0,0)
        self.thread_id=kernel.GetCurrentThreadId();registered=False;hook=None
        # Only the requested Alt+Space chord is consumed. The fallback allows
        # it to work when another launcher already registered that chord.
        # Other keys are passed through immediately; no keystrokes are stored.
        # Install the synchronous hook even when RegisterHotKey is available:
        # WM_HOTKEY alone would leave the same cross-process queueing gap.
        class Key(ctypes.Structure):_fields_=[('vk',w.DWORD),('scan',w.DWORD),('flags',w.DWORD),('time',w.DWORD),('extra',ctypes.c_size_t)]
        callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,ctypes.c_int,w.WPARAM,w.LPARAM)
        user.CallNextHookEx.argtypes=[w.HHOOK,ctypes.c_int,w.WPARAM,w.LPARAM];user.CallNextHookEx.restype=ctypes.c_ssize_t
        user.SetWindowsHookExW.argtypes=[ctypes.c_int,callback_type,w.HINSTANCE,w.DWORD];user.SetWindowsHookExW.restype=w.HHOOK
        user.UnhookWindowsHookEx.argtypes=[w.HHOOK];kernel.GetModuleHandleW.restype=w.HMODULE
        user.GetAsyncKeyState.argtypes=[ctypes.c_int];user.GetAsyncKeyState.restype=ctypes.c_short
        user.GetForegroundWindow.argtypes=[];user.GetForegroundWindow.restype=w.HWND
        pressed=False;escape_pressed=False
        @callback_type
        def callback(code,message,data):
            nonlocal pressed,escape_pressed
            if code>=0:
                key=ctypes.cast(data,ctypes.POINTER(Key)).contents
                if key.vk==0x1b:
                    down=message in (0x100,0x104);up=message in (0x101,0x105)
                    if escape_pressed:
                        if up:escape_pressed=False
                        return 1
                    modified=any(user.GetAsyncKeyState(vk)<0 for vk in (0x10,0x11,0x5b,0x5c)) if down else False
                    if down and not modified and self.active and user.GetForegroundWindow()==self.target:
                        from launcher_focus import close_sync
                        escape_pressed=True
                        if close_sync(self.target):return 1
                        escape_pressed=False
                if key.vk==0x20:
                    down=message in (0x100,0x104);up=message in (0x101,0x105)
                    modified=any(user.GetAsyncKeyState(vk)<0 for vk in (0x10,0x11,0x5b,0x5c)) if down else False
                    if down and key.flags&0x20 and not modified:
                        if not pressed:
                            pressed=True
                            self._trigger()
                        return 1
                    if up and pressed:pressed=False;return 1
                elif key.vk in (0x12,0xa4,0xa5) and message in (0x101,0x105):pressed=False
            return user.CallNextHookEx(None,code,message,data)
        hook=user.SetWindowsHookExW(13,callback,kernel.GetModuleHandleW(None),0)
        if not hook:
            registered=bool(user.RegisterHotKey(None,0x5949,0x4001,0x20))
            if not registered:self.status.emit('Không đăng ký được Alt+Space. Bạn vẫn có thể mở bằng nút Search.');self.ready.set();return
        logging.info('Launcher Alt+Space ready (%s)','registered fallback' if registered else 'synchronous chord')
        self.ready.set()
        try:
            while not self.closing.is_set() and user.GetMessageW(ctypes.byref(msg),None,0,0)>0:
                if msg.message==0x312 and msg.wParam==0x5949:self._trigger()
                user.TranslateMessage(ctypes.byref(msg));user.DispatchMessageW(ctypes.byref(msg))
        finally:
            if registered:user.UnregisterHotKey(None,0x5949)
            if hook:user.UnhookWindowsHookEx(hook)
            self.thread_id=None
