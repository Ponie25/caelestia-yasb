"""Bar surface colors and inexpensive native backdrop updates."""
from core.utils.theme_tokens import blend,channels,contrast,is_light,luminance,on_accent,readable
from functools import lru_cache
from pathlib import Path
import os


def wallpaper_signature():
    """Read the wallpaper identity, never capture the screen or app contents."""
    if os.name!='nt' or os.environ.get('YASB_SETTINGS_NO_EXTERNAL')=='1':return None
    import ctypes
    buffer=ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.user32.SystemParametersInfoW(0x73,len(buffer),buffer,0):return None
    path=buffer.value
    try:stamp=Path(path).stat().st_mtime_ns if path else 0
    except OSError:stamp=0
    rgb=ctypes.windll.user32.GetSysColor(1)
    solid=f'#{rgb&255:02x}{(rgb>>8)&255:02x}{(rgb>>16)&255:02x}'
    screen=(ctypes.windll.user32.GetSystemMetrics(0),ctypes.windll.user32.GetSystemMetrics(1))
    edge='top';bar_height=34
    from ctypes import wintypes
    user=ctypes.windll.user32;user.FindWindowExW.restype=wintypes.HWND
    user.FindWindowExW.argtypes=[wintypes.HWND,wintypes.HWND,wintypes.LPCWSTR,wintypes.LPCWSTR]
    user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    hwnd=user.FindWindowExW(None,None,None,'YasbBar');bounds=wintypes.RECT()
    if hwnd and user.GetWindowRect(hwnd,ctypes.byref(bounds)):
        edge='bottom' if bounds.top>screen[1]/2 else 'top';bar_height=max(1,bounds.bottom-bounds.top)
    style='10';tile=False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Control Panel\Desktop') as key:
            style=str(winreg.QueryValueEx(key,'WallpaperStyle')[0]);tile=str(winreg.QueryValueEx(key,'TileWallpaper')[0])=='1'
    except OSError:pass
    return path,stamp,solid,screen,edge,bar_height,style,tile


@lru_cache(maxsize=4)
def _wallpaper_colors(path,stamp,solid,screen,edge,bar_height,style,tile):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QImageReader
    if not path:return (solid,)
    reader=QImageReader(path);size=reader.size()
    if not size.isValid():return (solid,)
    reader.setScaledSize(QSize(192,max(2,round(size.height()*192/size.width()))))
    image=reader.read()
    if image.isNull():return (solid,)
    sw,sh=screen;iw,ih=size.width(),size.height()
    sx,sy=sw/iw,sh/ih
    if style in ('10','22'):sx=sy=max(sx,sy)
    elif style=='6':sx=sy=min(sx,sy)
    elif style!='2':sx=sy=1.
    ox,oy=(sw-iw*sx)/2,(sh-ih*sy)/2
    solid_rgb=channels(solid);bins={};total=0
    for row in (.2,.5,.8):
        yy=bar_height*row if edge=='top' else sh-bar_height*row
        for column in range(96):
            xx=sw*(column+.5)/96
            px,py=((xx%iw),(yy%ih)) if tile else ((xx-ox)/sx,(yy-oy)/sy)
            if 0<=px<iw and 0<=py<ih:
                r,g,b,a=image.pixelColor(min(image.width()-1,int(px/iw*image.width())),min(image.height()-1,int(py/ih*image.height()))).getRgb()
                if a<255:r,g,b=(round(c*a/255+base*(1-a/255)) for c,base in zip((r,g,b),solid_rgb))
            else:r,g,b=solid_rgb
            key=(r//32,g//32,b//32)
            item=bins.setdefault(key,[0,0,0,0]);item[0]+=1;item[1]+=r;item[2]+=g;item[3]+=b;total+=1
    colors=[]
    for count,r,g,b in sorted(bins.values(),reverse=True)[:3]:
        if count<total*.10 and colors:continue
        colors.append(f'#{round(r/count):02x}{round(g/count):02x}{round(b/count):02x}')
    return tuple(colors) or (solid,)


def wallpaper_colors():
    signature=wallpaper_signature()
    return _wallpaper_colors(*signature) if signature else ()


def surface_spec(preferences,palette,wallpaper=None):
    a=preferences['appearance'];mode=a['background']
    enabled=mode in ('glass','custom')
    color=palette['MANTLE'] if mode=='glass' and a['background_source']=='theme' else a['background_color']
    second=palette['BASE'] if mode=='glass' and a['background_source']=='theme' else a['background_color2']
    colors=(color,second) if a['background_gradient'] else (color,)
    alphas=(a['background_opacity'],a['background_opacity2']) if a['background_gradient'] else (a['background_opacity'],)
    walls=wallpaper_colors() if wallpaper is None else wallpaper
    walls=walls or (palette['MANTLE'],)
    theme_alpha=.86 if is_light(palette) else .01
    backgrounds=[blend(wall,c,alpha) for wall in walls for c,alpha in zip(colors,alphas)] if enabled else [blend(wall,palette['MANTLE'],theme_alpha) if mode=='theme' else wall for wall in walls]
    # A chosen white/dark material must keep its ink polarity even when the
    # desktop wallpaper differs from the app or live wallpaper beneath it.
    # Only a genuinely transparent surface derives its roles from wallpaper.
    material=enabled and (max(alphas)>0 or mode=='glass' and a['background_blur']) or mode=='theme' and theme_alpha>.5
    reading_backgrounds=list(colors) if enabled and material else [palette['MANTLE']] if material else backgrounds
    preferred=max(('#000000','#ffffff'),key=lambda c:min(contrast(c,bg) for bg in reading_backgrounds))
    if a['foreground']=='custom':ink=a['text_color']
    elif a['foreground']=='tint':ink=readable(a['text_color'],reading_backgrounds,4.5)
    elif a['foreground']=='auto':ink=preferred
    else:ink=palette['TEXT'] if min(contrast(palette['TEXT'],bg) for bg in reading_backgrounds)>=4.5 else preferred
    accent=readable(palette['MAUVE'],reading_backgrounds,4.5)
    secondary=readable(palette['MUTED'],reading_backgrounds,4.5)
    if a['foreground']=='custom':secondary=ink
    translucent=(min(alphas)<.99 if enabled else theme_alpha<.99 if mode=='theme' else True)
    return dict(enabled=enabled,blur=mode=='glass' and a['background_blur'],color=color,second=second,
                alpha=a['background_opacity'],alpha2=a['background_opacity2'],gradient=a['background_gradient'],
                direction=a['gradient_direction'],ink=ink,secondary=secondary,accent=accent,
                edge=palette['MAUVE'] if a['border_color_source']=='theme' else a['border_color'],
                contrast=min(contrast(ink,bg) for bg in backgrounds),backgrounds=backgrounds,
                reading_backgrounds=reading_backgrounds,theme_alpha=theme_alpha,material=material,
                translucent=translucent,light_ink=luminance(ink)>.179,material_light=preferred=='#000000')


def rgba(color,opacity):
    return 'rgba('+','.join(map(str,channels(color)))+f',{opacity:.4f})'


def surface_css(preferences,palette):
    a=preferences['appearance'];s=surface_spec(preferences,palette)
    css='\n/* Full bar surface */\n'
    if s['enabled']:
        fill=rgba(s['color'],s['alpha'])
        if s['gradient']:
            end='x2:1,y2:0' if s['direction']=='horizontal' else 'x2:0,y2:1'
            fill=f"qlineargradient(x1:0,y1:0,{end},stop:0 {fill},stop:1 {rgba(s['second'],s['alpha2'])})"
        css+=f'.yasb-bar {{background:{fill};background-color:{fill};}}\n'
    elif a['background']=='transparent':css+='.yasb-bar {background:rgba(0,0,0,0.004);background-color:rgba(0,0,0,0.004);}\n'
    elif a['background']=='theme':
        fill=rgba(palette['MANTLE'],s['theme_alpha']);css+=f'.yasb-bar {{background:{fill};background-color:{fill};}}\n'
    css+=f".yasb-bar .label,.yasb-bar .widget .label,.yasb-bar .widget .icon,.yasb-bar .komorebi-workspaces .ws-btn.populated {{color:{s['ink']};}}\n"
    css+=f".yasb-bar .komorebi-workspaces .ws-btn.empty,.yasb-bar .bar-divider .label {{color:{s['secondary']};}}\n"
    css+=f".yasb-bar .komorebi-workspaces .ws-btn:hover {{color:{s['ink']};}}\n"
    css+=f".yasb-bar .komorebi-workspaces .ws-btn.active,.yasb-bar .komorebi-workspaces .ws-btn.active:hover {{color:{s['accent']};}}\n"
    shadow=('0 0 2px rgba(0,0,0,0.85)' if s['light_ink'] else '0 0 2px rgba(255,255,255,0.85)') if s['translucent'] else 'none'
    css+=f'.yasb-bar .label,.yasb-bar .widget .icon,.yasb-bar .komorebi-workspaces .ws-btn {{text-shadow:{shadow};}}\n'
    css+='.yasb-bar {border:none;}\n'
    if a['border']:
        edge=rgba(s['edge'],a['border_opacity']);width=a['border_width']
        prop='border' if a['border_edges']=='all' else 'border-'+a['border_edges']
        css+=f'.yasb-bar {{{prop}:{width}px solid {edge};}}\n'
    return css


def apply_backdrops(manager,preferences,palette):
    """Update existing bar HWNDs without reloading widgets or reserving space again."""
    from PyQt6.QtCore import QEvent,QObject
    from PyQt6.QtGui import QPainterPath,QRegion
    from core.utils.win32.backdrop import enable_blur,set_accent_policy
    import logging

    spec=surface_spec(preferences,palette)
    class CornerClip(QObject):
        def __init__(self,bar):super().__init__(bar);self.bar=bar;self.radius=0
        def update(self):
            if self.radius:
                from PyQt6.QtCore import QRectF
                path=QPainterPath();path.addRoundedRect(QRectF(self.bar.rect()),self.radius,self.radius)
                self.bar.setMask(QRegion(path.toFillPolygon().toPolygon()))
            else:self.bar.clearMask()
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Type.Resize:self.update()
            return False
    for bar in getattr(manager,'bars',[]):
        try:
            native=getattr(getattr(bar,'config',None),'blur_effect',None)
            wanted=spec['blur'] or (preferences['appearance']['background']=='theme' and getattr(native,'enabled',False))
            surface_light=spec['material_light'] if spec['material'] else is_light(palette)
            signature=(wanted,surface_light)
            if getattr(bar,'_custom_backdrop_signature',None)!=signature:
                if wanted:enable_blur(bar.winId(),DarkMode=not surface_light,RoundCorners=False,BorderColor='None')
                else:
                    set_accent_policy(int(bar.winId()),0)
                # enable_blur only sets the dark flag when True. Clear it too
                # when switching to a light material on the same bar HWND.
                import ctypes
                from core.utils.win32.bindings.dwmapi import DwmSetWindowAttribute
                from core.utils.win32.constants import DWMWA_USE_IMMERSIVE_DARK_MODE
                dark=ctypes.c_int(not surface_light)
                DwmSetWindowAttribute(int(bar.winId()),DWMWA_USE_IMMERSIVE_DARK_MODE,ctypes.byref(dark),ctypes.sizeof(dark))
                bar._custom_backdrop_signature=signature
            clip=getattr(bar,'_custom_corner_clip',None)
            if clip is None:
                clip=CornerClip(bar);bar._custom_corner_clip=clip;bar.installEventFilter(clip)
            clip.radius=preferences['appearance']['radius'];clip.update()
        except (OSError,RuntimeError):logging.warning('Could not update bar backdrop',exc_info=True)
