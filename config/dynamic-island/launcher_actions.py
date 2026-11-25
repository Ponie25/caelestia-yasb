"""Fixed Windows actions and asynchronous local control; never execute query text."""
import ctypes,json,logging,os,subprocess,threading
from ctypes import wintypes as w
from pathlib import Path
from PySide6.QtCore import QObject,QTimer,Signal
from PySide6.QtNetwork import QLocalSocket

class ControlRequest(QObject):
    finished=Signal(bool,str)
    def __init__(self,parent):
        super().__init__(parent);self.socket=QLocalSocket(self);self.buffer=bytearray();self.done=False
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(2000)
        self.socket.connected.connect(lambda:self.socket.write(self.payload))
        self.socket.readyRead.connect(self._read)
        self.socket.errorOccurred.connect(lambda *_:self._finish(False,'Không kết nối được với thanh bar.'))
        self.timer.timeout.connect(lambda:self._finish(False,'Thanh bar chưa phản hồi. Hãy thử lại.'))
    def start(self,name,payload):
        self.payload=(json.dumps(payload,ensure_ascii=False)+'\n').encode('utf-8');self.timer.start();self.socket.connectToServer(name)
    def _read(self):
        self.buffer.extend(bytes(self.socket.readAll()))
        if len(self.buffer)>4096:self._finish(False,'Phản hồi không hợp lệ.');return
        if b'\n' not in self.buffer:return
        try:
            response=json.loads(bytes(self.buffer).split(b'\n',1)[0]);ok=isinstance(response,dict) and response.get('ok') is True
            self._finish(ok,'' if ok else 'Chưa áp dụng được. Mở Settings để kiểm tra thay đổi đang chờ lưu.')
        except (ValueError,TypeError):self._finish(False,'Phản hồi không hợp lệ.')
    def _finish(self,ok,message):
        if self.done:return
        self.done=True;self.timer.stop();self.socket.abort();self.finished.emit(ok,message);self.deleteLater()

class BackgroundAction(QObject):
    finished=Signal(bool,str)
    def __init__(self,parent,function):super().__init__(parent);self.function=function
    def start(self):threading.Thread(target=self._run,daemon=True,name='launcher-action').start()
    def _run(self):
        try:self.function();result=(True,'')
        except Exception as error:
            logging.warning('Launcher command failed',exc_info=True);result=(False,str(error)[:200] or 'Windows không thực hiện được lệnh này.')
        try:self.finished.emit(*result)
        except RuntimeError:pass

def power_action(action):
    if action=='lock':
        if not ctypes.windll.user32.LockWorkStation():raise ctypes.WinError()
        return
    if action=='sleep':
        _sleep();return
    flags={'shutdown':'/s','reboot':'/r','logout':'/l'}
    if action not in flags:raise ValueError('Lệnh nguồn không hợp lệ.')
    program=Path(os.environ.get('WINDIR',r'C:\Windows'))/'System32/shutdown.exe'
    args=[str(program),flags[action]]+([] if action=='logout' else ['/t','0'])
    result=subprocess.run(args,capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise OSError('Windows từ chối lệnh nguồn. Công việc đang mở có thể cần được lưu.')

def _sleep():
    class Luid(ctypes.Structure):_fields_=[('low',w.DWORD),('high',w.LONG)]
    class Privilege(ctypes.Structure):_fields_=[('luid',Luid),('attributes',w.DWORD)]
    class Privileges(ctypes.Structure):_fields_=[('count',w.DWORD),('values',Privilege*1)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);adv=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel.GetCurrentProcess.restype=w.HANDLE;kernel.CloseHandle.argtypes=[w.HANDLE]
    adv.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)]
    adv.LookupPrivilegeValueW.argtypes=[w.LPCWSTR,w.LPCWSTR,ctypes.POINTER(Luid)]
    adv.AdjustTokenPrivileges.argtypes=[w.HANDLE,w.BOOL,ctypes.POINTER(Privileges),w.DWORD,ctypes.POINTER(Privileges),ctypes.POINTER(w.DWORD)]
    token=w.HANDLE();wanted=Privileges();old=Privileges();size=w.DWORD()
    if not adv.OpenProcessToken(kernel.GetCurrentProcess(),0x20|0x8,ctypes.byref(token)):raise ctypes.WinError()
    try:
        wanted.count=1;wanted.values[0].attributes=2
        if not adv.LookupPrivilegeValueW(None,'SeShutdownPrivilege',ctypes.byref(wanted.values[0].luid)):raise ctypes.WinError()
        ctypes.set_last_error(0)
        if not adv.AdjustTokenPrivileges(token,False,ctypes.byref(wanted),ctypes.sizeof(old),ctypes.byref(old),ctypes.byref(size)) or ctypes.get_last_error()==1300:raise ctypes.WinError()
        suspend=ctypes.WinDLL('powrprof',use_last_error=True).SetSuspendState
        suspend.argtypes=[ctypes.c_ubyte]*3;suspend.restype=ctypes.c_ubyte
        try:
            if not suspend(False,False,False):raise ctypes.WinError()
        finally:
            if old.count:adv.AdjustTokenPrivileges(token,False,ctypes.byref(old),0,None,None)
    finally:kernel.CloseHandle(token)
