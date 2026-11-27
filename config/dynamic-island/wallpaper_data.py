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

def lab(rgb):
    r,g,b=(_linear(v/255) for v in rgb)
    l=(.4122214708*r+.5363325363*g+.0514459929*b)**(1/3)
    m=(.2119034982*r+.6806995451*g+.1073969566*b)**(1/3)
    s=(.0883024619*r+.2817188376*g+.6299787005*b)**(1/3)
    return .2104542553*l+.793617785*m-.0040720468*s,1.9779984951*l-2.428592205*m+.4505937099*s,.0259040371*l+.7827717662*m-.808675766*s

NEUTRAL_CHROMA=.035
NEUTRAL_SHARE=.2

def analyze(pixels):
    """Summarize opaque pixels as weighted OKLab hue regions; None when no pixel is usable.

    Regions are 10-degree hue bins weighted by pixel coverage times chroma. An image is
    neutral when fewer than 20% of its valid pixels reach OKLab chroma 0.035.
    """
    total=colored=0;bins={}
    for r,g,b in pixels:
        total+=1
        _,a,bb=lab((r,g,b));chroma=math.hypot(a,bb)
        if chroma<NEUTRAL_CHROMA:continue
        colored+=1
        key=round(math.atan2(bb,a)%(2*math.pi)*36/(2*math.pi))%36
        item=bins.setdefault(key,[0,0.,0.,0.]);item[0]+=1;item[1]+=chroma;item[2]+=a;item[3]+=bb
    if not total:return None
    regions=[(math.atan2(item[3],item[2]),item[1]/item[0],item[1]) for _,item in sorted(bins.items())]
    weight=sum(region[2] for region in regions)
    regions=[(hue,chroma,share/weight) for hue,chroma,share in regions] if weight else []
    return {'valid':total,'colored':colored,'neutral':not regions or colored<total*NEUTRAL_SHARE,'regions':regions}

def _anchor(color):
    _,a,b=lab(tuple(int(color[i:i+2],16) for i in (1,3,5)));return math.atan2(b,a),math.hypot(a,b)

def score(analysis,color):
    """Lower is closer: weighted hue distance plus a smaller chroma distance."""
    hue,chroma=_anchor(color);total=0.
    for region_hue,region_chroma,weight in analysis['regions']:
        turn=abs((region_hue-hue+math.pi)%(2*math.pi)-math.pi)/math.pi
        total+=weight*(turn+.5*abs(region_chroma-chroma)/.3)
    return round(total,9)

def choose_preset(analysis,tone,entries,default_id):
    """Return an existing original preset ID of the requested tone. Pixels never become colors."""
    candidates=sorted((entry for entry in entries if entry['tone']==tone and entry['origin']=='caelestia'),key=lambda entry:entry['id'])
    if not candidates:raise ValueError('Không có preset cho tông sáng/tối này.')
    if analysis['neutral']:
        if default_id not in {entry['id'] for entry in candidates}:raise ValueError('Thiếu preset Caelestia Default cho tông này.')
        return default_id
    return min(candidates,key=lambda entry:(score(analysis,entry['match_color']),entry['id']))['id']
