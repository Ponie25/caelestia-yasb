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

def load_presets(root):
    directory=Path(root)/'wallpaper-presets';path=directory/'catalog.json'
    if path.stat().st_size>100_000:raise ValueError('Danh sách preset quá lớn.')
    catalog=json.loads(path.read_text(encoding='utf-8'));seen=set()
    if not isinstance(catalog,list) or not 2<=len(catalog)<=64:raise ValueError('Danh sách preset không hợp lệ.')
    for entry in catalog:
        if not isinstance(entry,dict) or not re.fullmatch(r'[a-z][a-z0-9-]{1,47}',entry.get('id','')):raise ValueError('Mã preset không hợp lệ.')
        if entry['id'] in seen or entry.get('tone') not in ('light','dark') or not re.fullmatch(r'#[0-9a-fA-F]{6}',entry.get('match_color','')):raise ValueError('Thông tin preset không hợp lệ.')
        if not isinstance(entry.get('family'),str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,30}',entry['family']):raise ValueError('Nhóm preset không hợp lệ.')
        if not isinstance(entry.get('name'),str) or not entry['name'] or len(entry['name'])>80:raise ValueError('Tên preset không hợp lệ.')
        folder=(directory/entry['id']).resolve()
        if not folder.is_relative_to(directory.resolve()) or not all((folder/name).is_file() for name in ('palette.json','styles.css')):raise ValueError('Thiếu file preset.')
        seen.add(entry['id'])
    return catalog

def choose_preset(seed,dark,catalog):
    """Select an existing ID. Wallpaper pixels never become interface colors."""
    _,a,b=lab(tuple(int(seed[i:i+2],16) for i in (1,3,5)));chroma=math.hypot(a,b);hue=math.atan2(b,a)
    candidates=[entry for entry in catalog if entry['tone']==('dark' if dark else 'light')]
    if not candidates:raise ValueError('Không có preset cho tông sáng/tối này.')
    if chroma<.028:return next((entry for entry in candidates if entry['family']=='graphite'),candidates[0])
    def distance(entry):
        if entry['family']=='graphite':return 4.,entry['id']
        _,x,y=lab(tuple(int(entry['match_color'][i:i+2],16) for i in (1,3,5)))
        return abs((hue-math.atan2(y,x)+math.pi)%(2*math.pi)-math.pi),entry['id']
    return min(candidates,key=distance)
