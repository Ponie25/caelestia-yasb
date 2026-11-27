"""Color roles shared by the settings window, menus and Island painters."""
import json
from pathlib import Path
from functools import lru_cache


def channels(color):
    return tuple(int(color[i:i+2],16) for i in (1,3,5))


def luminance(color):
    values=[v/255 for v in channels(color)]
    values=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
    return sum(v*w for v,w in zip(values,(.2126,.7152,.0722)))


def contrast(first,second):
    low,high=sorted((luminance(first),luminance(second)))
    return (high+.05)/(low+.05)


def blend(first,second,amount):
    return '#'+''.join(f'{round(a*(1-amount)+b*amount):02x}' for a,b in zip(channels(first),channels(second)))


@lru_cache(maxsize=64)
def on_accent(color):
    return max(('#111118','#ffffff'),key=lambda ink:contrast(ink,color))


def readable(color,backgrounds,minimum=4.5):
    if min(contrast(color,bg) for bg in backgrounds)>=minimum:return color
    target=max(('#111118','#ffffff'),key=lambda ink:min(contrast(ink,bg) for bg in backgrounds))
    for step in range(1,101):
        candidate=blend(color,target,step/100)
        if min(contrast(candidate,bg) for bg in backgrounds)>=minimum:return candidate
    return target


def normalize_palette(palette):
    result=dict(palette)
    backgrounds=[result[name] for name in ('MANTLE','BASE','SURFACE','SURFACE2')]
    result['TEXT']=readable(result['TEXT'],backgrounds,7.0)
    result['MUTED']=readable(result['MUTED'],backgrounds,4.8)
    for name in ('MAUVE','PINK','LAVENDER','ROSEWATER'):
        result[name]=readable(result[name],backgrounds,4.5)
    result['OVERLAY']=readable(result['OVERLAY'],backgrounds,3.0)
    return result


def effective_palette(root,profile):
    root=Path(root)
    from theme_catalog import load_catalog
    palette=json.loads((load_catalog(root).profile_dir(profile)/'palette.json').read_text(encoding='utf-8'))
    try:
        custom=json.loads((root/'bar-settings.json').read_text(encoding='utf-8')).get('palette',{})
        palette.update({key:value for key,value in custom.items() if key in palette})
    except (OSError,ValueError,TypeError):
        pass
    return normalize_palette(palette)


@lru_cache(maxsize=64)
def _track_color(base,edge):
    return readable(edge,[base],3.0)


def track_color(palette):
    return _track_color(palette['BASE'],palette['SURFACE2'])


def is_light(palette):
    return luminance(palette['MANTLE'])>.45


def glass_alpha(palette,kind='island'):
    if kind=='settings':return 234 if is_light(palette) else 236
    return 220 if is_light(palette) else 230
