"""Live, capture-visible optical Island material with an ordinary blur fallback."""
import ctypes
import json
import logging
import math
from pathlib import Path
import time
from PySide6.QtCore import QTimer
from glass import GlassLayer
from functools import lru_cache
from theme_tokens import readable,luminance,is_light
import palette


@lru_cache(maxsize=64)
def compact_colors(optical,ink,mauve,pink,lavender,edge):
    if not optical:return dict(TEXT=ink,MAUVE=mauve,PINK=pink,LAVENDER=lavender,SURFACE2=edge)
    if luminance(ink)<.3:
        return dict(TEXT=ink,MAUVE=readable(mauve,['#bbbbbb'],3),PINK=readable(pink,['#bbbbbb'],3),LAVENDER=readable(lavender,['#bbbbbb'],3),SURFACE2='#777780')
    return dict(TEXT='#f7eeee',MAUVE=readable(mauve,['#666666'],3),PINK=readable(pink,['#666666'],3),LAVENDER=readable(lavender,['#666666'],3),SURFACE2='#897c83')


class MaterialLayer:
    def __init__(self,root,owner):
        self.root=Path(root);self.owner=owner;self.legacy=GlassLayer()
        self.options={};self.material='liquid-soft';self.enabled=True;self.failed=False
        self.context=None;self.lib=None;self._visible=False;self._ready=False;self._ready_at=0;self._first_attempt=0
        self._resume_floor=0;self._legacy_prepared=False
        self._buffer_size=None
        self._signature=None;self._configured=None;self._last_status=None
        self.timer=QTimer(owner);self.timer.setInterval(16);self.timer.timeout.connect(self._health)

    @property
    def wants_compact(self):return self.enabled and self.material!='outline'
    @property
    def wants_optical(self):return self.enabled and self.material.startswith('liquid-')
    @property
    def hwnd(self):return self.context or self.legacy.hwnd
    @property
    def optical(self):return self.wants_optical and self._ready and self._visible and not self.failed
    @property
    def visible(self):return self.optical or self.legacy.visible
    @property
    def mix(self):return min(1.,max(0.,(time.monotonic()-self._ready_at)/.16)) if self.optical else 0.

    def _status(self,state,message):
        value=(self.material,state,message)
        if self._last_status==value:return
        self._last_status=value
        path=self.root/'material-status.json';temporary=path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(dict(material=self.material,state=state,message=message,updated=time.time()),ensure_ascii=False),encoding='utf-8')
            temporary.replace(path)
        except OSError:logging.debug('Could not save material status',exc_info=True)

    def configure(self,options):
        previous=self.material;self.options=dict(options);self.material=options.get('material','liquid-soft')
        for key,default,low,high in (('liquid_refraction',1.,0,2),('liquid_frost',.4,0,1),('liquid_tint',.32,0,.85),('liquid_reflection',1.,0,2),('liquid_fps',120,30,240)):
            value=self.options.get(key,default)
            if type(value) not in (int,float) or not math.isfinite(value):value=default
            self.options[key]=max(low,min(high,value))
        if type(self.options.get('liquid_contrast',True)) is not bool:self.options['liquid_contrast']=True
        if self.material not in ('liquid-soft','liquid-clear','frosted','outline'):self.material='liquid-soft'
        self.enabled=bool(options.get('glass',True))
        if previous!=self.material or not self.context:self.failed=False
        self._configured=None;self._legacy_prepared=False
        if not self.wants_optical:
            self._stop_native();self.legacy.hide()
            self._status('ready','Hiệu ứng kính đang tắt.' if not self.enabled else 'Kính mờ Windows.' if self.material=='frosted' else 'Nền viền trong suốt.')
        if self.wants_optical:self.legacy.hide()
        self.owner.update()

    def _load(self):
        if self.lib:return
        lib=ctypes.CDLL(str(self.root/'native/liquid_glass.dll'))
        lib.lg_create_wgc.argtypes=[ctypes.c_void_p,ctypes.c_int];lib.lg_create_wgc.restype=ctypes.c_void_p
        lib.lg_set.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_float),ctypes.c_int,ctypes.POINTER(ctypes.c_float),ctypes.c_int]
        lib.lg_set_look.argtypes=[ctypes.c_void_p,ctypes.c_float,ctypes.c_float]
        lib.lg_set_look2.argtypes=[ctypes.c_void_p,ctypes.c_float,ctypes.c_float]
        lib.lg_light.argtypes=[ctypes.c_void_p,ctypes.c_float,ctypes.c_float]
        lib.lg_set_fps.argtypes=[ctypes.c_void_p,ctypes.c_int]
        lib.lg_suspend.argtypes=[ctypes.c_void_p,ctypes.c_int]
        lib.lg_error.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_long)]
        lib.lg_info.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_long),ctypes.POINTER(ctypes.c_long),ctypes.POINTER(ctypes.c_int)]
        lib.lg_destroy.argtypes=[ctypes.c_void_p];lib.lg_shutdown.argtypes=[]
        self.lib=lib

    def prepare(self):
        if not self.enabled:return
        if not self.wants_optical or self.failed:
            if not self._legacy_prepared:self.legacy.prepare();self._legacy_prepared=True
            return
        if self.context:return
        try:
            self._load();self.context=self.lib.lg_create_wgc(int(self.owner.winId()),1)
            if not self.context:raise OSError('Native material did not create a context.')
            self._first_attempt=time.monotonic();self._ready=False;self._resume_floor=0;self._signature=None;self.timer.setInterval(16);self.timer.start()
            self.lib.lg_light(self.context,0,-.25)
            self._status('starting','Đang khởi tạo Liquid Glass…')
        except (OSError,AttributeError) as error:self._fallback(str(error))

    def _fallback(self,reason):
        logging.warning('Liquid Glass fallback: %s',reason)
        self.failed=True;self._stop_native();self.legacy.prepare();self._legacy_prepared=True
        self._status('fallback','Đang dùng kính mờ: '+reason[:180]);self.owner.update()

    def _health(self):
        if not self.context:return
        stage=ctypes.c_int();hr=ctypes.c_long();frames=ctypes.c_long();updates=ctypes.c_long();us=ctypes.c_int()
        self.lib.lg_error(self.context,ctypes.byref(stage),ctypes.byref(hr))
        self.lib.lg_info(self.context,ctypes.byref(frames),ctypes.byref(updates),ctypes.byref(us))
        if stage.value:
            self._fallback(f'GPU {stage.value} / 0x{hr.value&0xffffffff:08x}');return
        if frames.value>self._resume_floor and not self._ready:
            self._ready=True;self._ready_at=time.monotonic();self._status('ready','Liquid Glass đang chạy bằng GPU.');self.owner.update()
        if self._ready:
            if time.monotonic()-self._ready_at<.2:self.owner.update()
            else:self.timer.setInterval(2000)
        elif self._visible and time.monotonic()-self._first_attempt>5:self._fallback('Không lấy được nền desktop.')

    def sync(self,front,bounds,rect,radius,scale):
        if not self.enabled:self.hide();return
        if not self.wants_optical or self.failed:
            self.legacy.sync(front,bounds,rect,radius,scale);return
        self.prepare()
        if not self.context:return
        if not self._visible:
            self.lib.lg_suspend(self.context,0);self._visible=True;self._first_attempt=time.monotonic()
            self.timer.setInterval(16);self.timer.start()
        size=(round(self.owner.width()*scale),round(self.owner.height()*scale))
        if size!=self._buffer_size:
            frames=ctypes.c_long();updates=ctypes.c_long();us=ctypes.c_int()
            self.lib.lg_info(self.context,ctypes.byref(frames),ctypes.byref(updates),ctypes.byref(us))
            self._buffer_size=size;self._resume_floor=frames.value;self._ready=False;self._signature=None
            self._first_attempt=time.monotonic();self.timer.setInterval(16);self.timer.start()
        strength=self.options.get('liquid_refraction',1.)
        clear=self.material=='liquid-clear'
        thickness=(5. if clear else 7.)*strength
        bevel=3.2 if clear else 3.5
        blur=(.30 if clear else .85)*self.options.get('liquid_frost',.4)/.4
        light=is_light(vars(palette))
        protection=(-1. if light else 1.) if self.options.get('liquid_contrast',True) else 0.
        params=(1.42 if clear else 1.45,thickness,bevel,.002 if clear else .003,blur,.035 if clear else .04,.15,0.,.10,2.,.15,scale,protection)
        configured=(self.material,params,self.options.get('outline',True),self.options.get('liquid_reflection',1.),self.options.get('liquid_fps',120))
        if configured!=self._configured:
            self.lib.lg_set_look(self.context,float(self.options.get('liquid_reflection',1.)),1. if self.options.get('outline',True) else 0.)
            self.lib.lg_set_look2(self.context,0,1);self.lib.lg_set_fps(self.context,int(self.options.get('liquid_fps',120)))
            self._configured=configured
        tint=(.96,.965,.98) if light else (.025,.018,.025)
        shape=(rect.center().x()*scale,rect.center().y()*scale,rect.width()/2*scale,rect.height()/2*scale,radius*scale,1.,1.,0.,*tint,self.options.get('liquid_tint',.32))
        signature=(params,shape)
        if signature!=self._signature:
            p=(ctypes.c_float*len(params))(*params);s=(ctypes.c_float*12)(*shape)
            self.lib.lg_set(self.context,p,len(params),s,1);self._signature=signature
        self.legacy.hide()

    def hide(self):
        self.legacy.hide()
        if self.context and self._visible:
            frames=ctypes.c_long();updates=ctypes.c_long();us=ctypes.c_int()
            self.lib.lg_info(self.context,ctypes.byref(frames),ctypes.byref(updates),ctypes.byref(us))
            self._resume_floor=frames.value;self._ready=False;self.timer.stop()
            self.lib.lg_suspend(self.context,1)
        self._visible=False

    def _stop_native(self):
        self.timer.stop()
        if self.context:
            self.lib.lg_destroy(self.context);self.context=None
            self.lib.lg_shutdown()
        self._visible=False;self._ready=False;self._signature=None;self._buffer_size=None

    def close(self):self._stop_native();self.legacy.close()
