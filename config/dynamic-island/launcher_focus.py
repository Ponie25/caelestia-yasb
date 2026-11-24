"""Synchronous, bounded native keyboard handoff for the explicit launcher chord.

No text is intercepted or replayed. Windows keeps subsequent physical input
ordered while the Alt+Space handler waits for the Island's acknowledgement.
"""
import ctypes
from ctypes import wintypes as w

user=ctypes.WinDLL('user32',use_last_error=True)
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
user.RegisterWindowMessageW.argtypes=[w.LPCWSTR];user.RegisterWindowMessageW.restype=w.UINT
TOGGLE_MESSAGE=user.RegisterWindowMessageW('CaelestiaYASB.Island.Launcher.Toggle.v1')
if not TOGGLE_MESSAGE:raise ctypes.WinError(ctypes.get_last_error())
user.SendMessageTimeoutW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,ctypes.POINTER(ctypes.c_size_t)]
user.SendMessageTimeoutW.restype=ctypes.c_ssize_t
user.GetForegroundWindow.argtypes=[];user.GetForegroundWindow.restype=w.HWND
user.SetForegroundWindow.argtypes=[w.HWND];user.SetForegroundWindow.restype=w.BOOL
user.SetFocus.argtypes=[w.HWND];user.SetFocus.restype=w.HWND
user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)];user.GetWindowThreadProcessId.restype=w.DWORD
user.AttachThreadInput.argtypes=[w.DWORD,w.DWORD,w.BOOL];user.AttachThreadInput.restype=w.BOOL
kernel.GetCurrentThreadId.restype=w.DWORD
kernel.GetTickCount64.restype=ctypes.c_ulonglong


def foreground():return user.GetForegroundWindow()


def request_valid(deadline):return bool(deadline and kernel.GetTickCount64()<=deadline)


def activate(hwnd):
    """Called on the owning GUI thread, only for an explicit open request."""
    if foreground()==hwnd:return True
    user.SetForegroundWindow(hwnd)
    if foreground()==hwnd:return True
    previous=foreground();current=kernel.GetCurrentThreadId()
    source=user.GetWindowThreadProcessId(previous,None) if previous else 0
    attached=source and source!=current and user.AttachThreadInput(current,source,True)
    try:
        if attached:
            user.SetForegroundWindow(hwnd)
            if foreground()==hwnd:user.SetFocus(hwnd)
    finally:
        if attached:user.AttachThreadInput(current,source,False)
    return foreground()==hwnd


def _request(hwnd,action,timeout):
    result=ctypes.c_size_t()
    # BLOCK prevents nested chord callbacks. ERRORONEXIT avoids using a stale
    # HWND during shutdown. Never broadcast or wait without a deadline.
    deadline=kernel.GetTickCount64()+timeout
    sent=user.SendMessageTimeoutW(hwnd,TOGGLE_MESSAGE,deadline,action,0x1|0x2|0x20,timeout,ctypes.byref(result))
    return bool(sent and result.value==1)


def toggle_sync(hwnd,timeout=250):return _request(hwnd,0,timeout)
def close_sync(hwnd,timeout=250):return _request(hwnd,1,timeout)
