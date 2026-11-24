"""Qt-independent motion contract shared by the two UI runtimes."""
from functools import lru_cache
import ctypes,json,math,os,time
from pathlib import Path

DEFAULT={
    'curves':{'spatial':[.38,1.21,.22,1.],'fast':[.42,1.67,.21,.9],'effects':[.34,.8,.34,1.]},
    'durations':{'launcher':560,'popup':440,'menu':320,'dialog':360,'page':280,'section':320,'control':160,'close':220},
}
_os_cache=(0.,True)
@lru_cache(maxsize=8)
def _tokens(path,stamp):
    result={key:dict(value) for key,value in DEFAULT.items()}
    try:
        raw=json.loads(Path(path).read_text(encoding='utf-8'))
        for name,value in raw.get('curves',{}).items():
            if name in result['curves'] and isinstance(value,list) and len(value)==4 and all(type(x) in (int,float) and math.isfinite(x) for x in value) and 0<=value[0]<=1 and 0<=value[2]<=1 and all(-1<=x<=3 for x in value):result['curves'][name]=value
        for name,value in raw.get('durations',{}).items():
            if name in result['durations'] and type(value) is int and 40<=value<=1000:result['durations'][name]=value
    except (OSError,ValueError,TypeError,AttributeError):pass
    return result
def tokens(root):
    path=Path(root)/'motion-profile.json'
    try:stamp=path.stat().st_mtime_ns
    except OSError:stamp=0
    return _tokens(str(path),stamp)
def system_motion():
    global _os_cache
    if os.name!='nt' or os.environ.get('YASB_SETTINGS_NO_EXTERNAL')=='1':return True
    now=time.monotonic()
    if now-_os_cache[0]>2:
        enabled=ctypes.c_int(1)
        try:ctypes.windll.user32.SystemParametersInfoW(0x1042,0,ctypes.byref(enabled),0)
        except OSError:pass
        _os_cache=(now,bool(enabled.value))
    return _os_cache[1]
def profile(root,preferences=None):
    if preferences is None:
        try:preferences=json.loads((Path(root)/'bar-settings.json').read_text(encoding='utf-8'))
        except (OSError,ValueError,TypeError):preferences={}
    if not isinstance(preferences,dict):preferences={}
    animations=preferences.get('animations',{});island=preferences.get('island',{})
    if not isinstance(animations,dict):animations={}
    if not isinstance(island,dict):island={}
    base=animations.get('popup_ms',220);speed=island.get('speed',1.)
    if type(base) not in (int,float) or not math.isfinite(base):base=220
    if type(speed) not in (int,float) or not math.isfinite(speed):speed=1.
    fps=island.get('fps',120)
    if type(fps) is not int:fps=120
    return {'enabled':animations.get('enabled',True) is not False and base>0 and system_motion(),
            'scale':max(.15,min(3.,base/220*speed)),'fps':max(30,min(240,fps)),**tokens(root)}
def milliseconds(spec,kind):return round(spec['durations'].get(kind,320)*spec['scale']) if spec['enabled'] else 0
