"""Windows shortcut entry point for YASB's Settings window."""
from pathlib import Path
import ctypes,hashlib,json,os,subprocess,sys,time

root=Path(__file__).resolve().parent
key=hashlib.sha256(os.fsencode(os.path.normcase(str(root.resolve())))).hexdigest()[:20]
pipe='\\\\.\\pipe\\yasb-settings-'+key
def send():
    try:
        with open(pipe,'r+b',buffering=0) as client:client.write(b'{"action":"open"}\n')
        return True
    except OSError:return False

if not send():
    candidate=Path(sys.argv[1]) if len(sys.argv)>1 else None
    if candidate is None:
        portable=root.parent/"yasb/yasb.exe"
        if portable.is_file():candidate=portable
    if candidate is None or not candidate.is_file():
        candidates=sorted((Path(os.environ.get('LOCALAPPDATA',''))/'YASB').glob('*/yasb.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
        candidate=candidates[0] if candidates else None
    if candidate is not None:
        subprocess.Popen([str(candidate)],cwd=str(candidate.parent),creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(40):
            time.sleep(.15)
            if send():break
        else:ctypes.windll.user32.MessageBoxW(None,'Chưa mở được cài đặt. Hãy đợi thanh bar khởi động rồi thử lại.','Cài đặt thanh bar',0x40)
    else:ctypes.windll.user32.MessageBoxW(None,'Không tìm thấy YASB. Hãy mở thanh bar rồi thử lại.','Cài đặt thanh bar',0x40)
