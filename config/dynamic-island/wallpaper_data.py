"""Read-only wallpaper metadata and perceptual color math; no Qt dependency."""
import json,math,os,re,time
from pathlib import Path
from urllib.request import Request,urlopen

def engine_metadata(engine):
    result={'favorites':set(),'current':'','preview':''}
    try:
        config=Path(engine).parent/'config.json'
        if config.stat().st_size>8_000_000:return result
        data=json.loads(config.read_text(encoding='utf-8-sig'))
        name=os.environ.get('USERNAME','').casefold()
        profiles=[v for k,v in data.items() if isinstance(v,dict) and 'general' in v]
        profile=next((v for k,v in data.items() if k.casefold()==name and isinstance(v,dict)),None)
        if profile is None:profile=profiles[0] if len(profiles)==1 else {}
        general=profile.get('general',{})
        # Some versions cache numeric favorites locally; saved search lists are ignored.
        cached=general.get('browser',{}).get('explore',{}).get('favorites',[])
        result['favorites']={str(v) for v in cached if isinstance(v,(str,int)) and re.fullmatch(r'\d{5,20}',str(v))}
        selected=general.get('wallpaperconfig',{}).get('selectedwallpapers',{})
        rows=list(selected.values()) if isinstance(selected,dict) else []
        for row in rows:
            value=row.get('file') if isinstance(row,dict) else None
            if not isinstance(value,str) or not Path(value).is_absolute():continue
            project=Path(value).parent/'project.json'
            if not project.is_file():continue
            result['current']=str(project)
            if project.stat().st_size>1_000_000:break
            item=json.loads(project.read_text(encoding='utf-8-sig'))
            preview=(project.parent/str(item.get('preview','preview.jpg'))).resolve()
            if preview.is_relative_to(project.parent.resolve()) and preview.is_file():result['preview']=str(preview)
            break
    except (OSError,ValueError,TypeError,AttributeError):pass
    return result

def steam_account():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam\ActiveProcess') as key:
            value=winreg.QueryValueEx(key,'ActiveUser')[0]
            return value if type(value) is int and 0<value<2**32 else None
    except (OSError,ImportError):return None

def favorite_cache(cached):
    cached=cached if isinstance(cached,dict) else {};ids=cached.get('ids',[]);updated=cached.get('updated',0)
    return {'account':cached.get('account') if type(cached.get('account')) is int else None,
            'ids':[v for v in ids[:2000] if isinstance(v,str) and re.fullmatch(r'\d{5,20}',v)] if isinstance(ids,list) else [],
            'updated':updated if type(updated) in (int,float) and math.isfinite(updated) else 0,
            'error':str(cached.get('error',''))[:180]}

def steam_favorites(account,cached=None,force=False):
    """Anonymous, read-only Steam pages; never access cookies or login credentials."""
    cached=favorite_cache(cached);cached=cached if cached.get('account')==account else {}
    if not account:return {'account':None,'ids':[],'updated':0,'error':'Steam chưa đăng nhập trên máy này.'}
    if not force and time.time()-cached.get('updated',0)<300:return cached
    ids=set();pages=1
    try:
        for page in range(1,21):
            url=f'https://steamcommunity.com/profiles/{76561197960265728+account}/myworkshopfiles/?appid=431960&browsefilter=myfavorites&browsesort=myfavorites&numperpage=100&p={page}'
            with urlopen(Request(url,headers={'User-Agent':'CaelestiaYASB/1.0'}),timeout=5) as reply:
                raw=reply.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('Trang yêu thích quá lớn.')
            html=raw.decode('utf-8','replace')
            if 'profile_private_info' in html or 'workshopBrowseItems' not in html and 'workshopItemPreviewHolder' not in html:
                raise ValueError('Steam không cho đọc danh sách yêu thích công khai.')
            ids.update(re.findall(r'id="sharedfile_(\d+)"',html))
            pages=max([1]+[int(v) for v in re.findall(r'[?&](?:amp;)?p=(\d+)',html)])
            if page>=min(20,pages):break
        return {'account':account,'ids':sorted(ids),'updated':time.time(),'error':''}
    except (OSError,ValueError) as error:
        return {**cached,'account':account,'ids':cached.get('ids',[]),'updated':time.time(),'error':str(error)[:180]}

def _linear(v):return v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4
def _encoded(v):return 12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055

def lab(rgb):
    r,g,b=(_linear(v/255) for v in rgb)
    l=(.4122214708*r+.5363325363*g+.0514459929*b)**(1/3)
    m=(.2119034982*r+.6806995451*g+.1073969566*b)**(1/3)
    s=(.0883024619*r+.2817188376*g+.6299787005*b)**(1/3)
    return .2104542553*l+.793617785*m-.0040720468*s,1.9779984951*l-2.428592205*m+.4505937099*s,.0259040371*l+.7827717662*m-.808675766*s

def tonal(lightness,chroma,hue):
    def rgb(c):
        a,b=c*math.cos(hue),c*math.sin(hue)
        l=(lightness+.3963377774*a+.2158037573*b)**3
        m=(lightness-.1055613458*a-.0638541728*b)**3
        s=(lightness-.0894841775*a-1.291485548*b)**3
        return 4.0767416621*l-3.3077115913*m+.2309699292*s,-1.2684380046*l+2.6097574011*m-.3413193965*s,-.0041960863*l-.7034186147*m+1.707614701*s
    values=rgb(chroma)
    if min(values)<0 or max(values)>1:
        low,high=0.,chroma
        for _ in range(14):
            mid=(low+high)/2;candidate=rgb(mid)
            if min(candidate)>=0 and max(candidate)<=1:low=mid
            else:high=mid
        values=rgb(low)
    return '#'+''.join(f'{round(max(0,min(1,_encoded(v)))*255):02x}' for v in values)

def dominant(pixels):
    """Favor populous chromatic regions, rather than averaging an image to brown."""
    bins={};neutral=[]
    for r,g,b in pixels:
        light,a,bb=lab((r,g,b));chroma=math.hypot(a,bb)
        if .12<light<.94:neutral.append((r,g,b))
        if chroma<.035 or not .18<light<.92:continue
        hue=math.atan2(bb,a)%(2*math.pi);key=round(hue*36/(2*math.pi))%36
        bucket=bins.setdefault(key,[0,0.,0.,0.]);weight=.3+min(.22,chroma)*4
        bucket[0]+=weight;bucket[1]+=r*weight;bucket[2]+=g*weight;bucket[3]+=b*weight
    if bins:
        at=max(bins,key=lambda k:bins[k][0]+.5*bins.get((k-1)%36,[0])[0]+.5*bins.get((k+1)%36,[0])[0])
        group=[bins[k] for k in ((at-1)%36,at,(at+1)%36) if k in bins];total=sum(v[0] for v in group)
        rgb=tuple(round(sum(v[i] for v in group)/total) for i in (1,2,3))
    else:rgb=tuple(round(sum(v[i] for v in neutral)/len(neutral)) for i in range(3)) if neutral else (128,128,128)
    return '#'+''.join(f'{v:02x}' for v in rgb)

def make_palette(seed,dark=True):
    _,a,b=lab(tuple(int(seed[i:i+2],16) for i in (1,3,5)));c=math.hypot(a,b);h=math.atan2(b,a)
    neutral=min(.025,c*.18);accent=min(.18,max(.07,c)) if c>.025 else 0.012
    roles={'CRUST':(.11,.006),'MANTLE':(.15,.012),'BASE':(.19,.016),'SURFACE':(.25,.022),'SURFACE2':(.31,.025),
           'OVERLAY':(.64,.02),'MUTED':(.80,.02),'TEXT':(.95,.012)} if dark else {
           'CRUST':(.99,.004),'MANTLE':(.975,.008),'BASE':(.955,.012),'SURFACE':(.92,.018),'SURFACE2':(.87,.02),
           'OVERLAY':(.48,.02),'MUTED':(.36,.02),'TEXT':(.20,.012)}
    result={key:tonal(light,min(chroma,neutral),h) for key,(light,chroma) in roles.items()}
    result.update(MAUVE=tonal(.80 if dark else .43,accent,h),LAVENDER=tonal(.81 if dark else .44,accent*.55,h),
                  PINK=tonal(.83 if dark else .44,accent*.75,h+math.pi/3),ROSEWATER=tonal(.88 if dark else .42,accent*.35,h+math.pi/6))
    return result

def render_css(template,palette,reference):
    aliases={'#11111b':'CRUST','#181825':'MANTLE','#1e1e2e':'BASE','#313244':'SURFACE','#45475a':'SURFACE2',
             '#6c7086':'OVERLAY','#a6adc8':'MUTED','#cdd6f4':'TEXT','#ffffff':'TEXT','#b4befe':'LAVENDER',
             '#cba6f7':'MAUVE','#f5c2e7':'PINK','#f5e0dc':'ROSEWATER'}
    aliases.update({value.lower():key for key,value in reference.items()})
    def mapped(color):
        role=aliases.get(color.lower())
        return palette[role] if role in palette else color
    css=re.sub(r'#[0-9a-fA-F]{6}\b',lambda m:mapped(m[0]),template)
    def rgb(match):
        color='#'+''.join(f'{int(match[i]):02x}' for i in (2,3,4));new=mapped(color)
        if new==color:return match[0]
        values=','.join(str(int(new[i:i+2],16)) for i in (1,3,5))
        return match[1]+'('+values+((','+match[5]) if match[5] is not None else '')+')'
    css=re.sub(r'\b(rgb|rgba)\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([0-9.]+)\s*)?\)',rgb,css)
    ink='#111118' if sum(int(palette['MAUVE'][i:i+2],16) for i in (1,3,5))>420 else '#ffffff'
    return css+'\n/* Wallpaper palette: preserve control contrast. */\n.control-center-menu .section.quick-actions .button.active .icon {color:'+ink+';}\n'
