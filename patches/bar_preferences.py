"""Persisted settings shared by the bar settings UI and theme controller."""
from copy import deepcopy
from datetime import datetime
from importlib import import_module
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

DEFAULTS = {
    'settings_window': {'mode':'system'},
    'appearance': {'font_family': 'JetBrainsMono NFP', 'font_size': 12, 'font_weight': 600,
                   'spacing': 6, 'padding': 8, 'radius': 0, 'background': 'theme',
                   'background_color': '#181825', 'background_opacity': 0.92,
                   'border': False, 'border_color': '#45475a',
                   'background_source':'theme','background_blur':True,'background_gradient':False,
                   'background_color2':'#1e1e2e','background_opacity2':0.72,'gradient_direction':'vertical',
                   'foreground':'auto','text_color':'#f7eeee','border_color_source':'custom',
                   'border_opacity':0.5,'border_width':1.0,'border_edges':'all'},
    'animations': {'enabled': True, 'popup_ms': 220},
    'launcher': {'enabled':True,'hotkey':True,'max_results':7},
    'island': {'enabled': True, 'hover': True, 'glass': True, 'outline': True,
               'material':'liquid-soft','liquid_refraction':1.0,'liquid_frost':0.4,
               'liquid_tint':0.32,'liquid_reflection':1.0,'liquid_fps':120,'liquid_contrast':True,
               'media': True, 'codex': True, 'notifications': True, 'timer': True,
               'stopwatch': True, 'output': True, 'notification_seconds': 5,
               'idle_width': 116, 'speed': 1.0, 'fps': 120,
               'default_tab': 'Dashboard', 'remember_tab': False},
    'weather': {'city': 'Hà Nội', 'latitude': 21.0245, 'longitude': 105.84117, 'timezone': 'Asia/Bangkok'},
    'palette': {},
    'komorebi': {'mode':'theme','single_color':'#cba6f7','stack_color':'#f5c2e7',
                 'monocle_color':'#cba6f7','floating_color':'#f5c2e7',
                 'unfocused_color':'#45475a','unfocused_locked_color':'#b4befe'},
}
COLORS = ('CRUST','MANTLE','BASE','SURFACE','SURFACE2','OVERLAY','MUTED','TEXT','LAVENDER','MAUVE','PINK','ROSEWATER')

STYLE_KEYS=('background','background_color','background_opacity','background_source','background_blur',
            'background_gradient','background_color2','background_opacity2','gradient_direction','foreground','text_color',
            'border','border_color','border_color_source','border_opacity','border_width','border_edges','radius')
GLASS_KEYS=('glass','outline','liquid_refraction','liquid_frost','liquid_tint','liquid_reflection','liquid_contrast')


def material_preset(name):
    """Canonical optical values; performance and feature switches are separate."""
    if name not in ('liquid-soft','liquid-clear','frosted','outline'):raise ValueError('Unknown material preset')
    result={key:deepcopy(DEFAULTS['island'][key]) for key in GLASS_KEYS}
    result['material']=name
    return result


def appearance_preset(palette,name='theme'):
    result={key:deepcopy(DEFAULTS['appearance'][key]) for key in STYLE_KEYS}
    result.update(background_color=palette['MANTLE'],background_color2=palette['BASE'],text_color=palette['TEXT'],
                  border_color=palette['MAUVE'],border_color_source='theme',background_source='theme',foreground='auto')
    if name=='clear':result.update(background='transparent',background_opacity=0.,background_blur=False)
    elif name in ('soft','balanced','solid'):
        result.update(background='glass',background_opacity={'soft':.36,'balanced':.56,'solid':1.}[name],background_blur=name!='solid')
    return result


def theme_preset(preferences,palette):
    result=deepcopy(preferences);result['palette']={}
    result['appearance'].update(appearance_preset(palette))
    result['island'].update(material_preset('liquid-soft'))
    return result


def merged(default, data):
    result = deepcopy(default)
    if isinstance(data, dict):
        for key,value in data.items():
            result[key] = merged(result[key],value) if key in result and isinstance(result[key],dict) else value
    return result


def load_preferences(root):
    try:
        data = json.loads((Path(root)/'bar-settings.json').read_text(encoding='utf-8'))
        return validate_preferences(data)
    except (OSError, ValueError, TypeError):
        return deepcopy(DEFAULTS)


def popup_duration(default=220):
    from core.utils.ui_motion import duration
    return duration('menu')


def validate_preferences(data):
    if not isinstance(data,dict):raise ValueError('Settings JSON cần là một object.')
    for group in DEFAULTS:
        if group in data and not isinstance(data[group],dict):raise ValueError(f'{group}: cần là một object.')
    legacy_border=isinstance(data.get('appearance'),dict) and data['appearance'].get('border') is True and 'border_opacity' not in data['appearance']
    data = merged(DEFAULTS, data)
    if legacy_border:data['appearance']['border_opacity']=1.0
    ranges = {
        ('appearance','font_size'):(8,24), ('appearance','font_weight'):(100,900),
        ('appearance','spacing'):(0,32), ('appearance','padding'):(0,60), ('appearance','radius'):(0,40),
        ('appearance','background_opacity'):(0,1), ('animations','popup_ms'):(0,600),
        ('appearance','background_opacity2'):(0,1),('appearance','border_opacity'):(0,1),
        ('appearance','border_width'):(0.5,8),
        ('launcher','max_results'):(3,7),
        ('island','notification_seconds'):(1,30), ('island','idle_width'):(80,240),
        ('island','speed'):(0.25,3), ('island','fps'):(30,240),
        ('island','liquid_refraction'):(0,2),('island','liquid_frost'):(0,1),
        ('island','liquid_tint'):(0,0.85),('island','liquid_reflection'):(0,2),('island','liquid_fps'):(30,240),
        ('weather','latitude'):(-90,90), ('weather','longitude'):(-180,180),
    }
    for (group,key),(low,high) in ranges.items():
        value=data[group][key]
        if type(value) not in (int,float) or not low <= value <= high:
            raise ValueError(f'{group}.{key}: cần nằm trong {low}–{high}.')
        if type(DEFAULTS[group][key]) is int and type(value) is not int:
            raise ValueError(f'{group}.{key}: cần là số nguyên.')
    for group in DEFAULTS:
        for key,value in DEFAULTS[group].items():
            if type(value) is bool and type(data[group][key]) is not bool:
                raise ValueError(f'{group}.{key}: cần là true/false.')
    if data['appearance']['background'] not in ('theme','transparent','custom','glass'):
        raise ValueError('Kiểu nền không hợp lệ.')
    enums={'background_source':('theme','custom'),'gradient_direction':('horizontal','vertical'),
           'foreground':('theme','auto','tint','custom'),'border_color_source':('theme','custom'),
           'border_edges':('all','top','bottom')}
    for key,choices in enums.items():
        if data['appearance'][key] not in choices:raise ValueError(f'appearance.{key}: giá trị không hợp lệ.')
    if data['komorebi']['mode'] not in ('theme','custom','original','off'):raise ValueError('Chế độ viền Komorebi không hợp lệ.')
    if data['settings_window']['mode'] not in ('system','light','dark'):raise ValueError('Chế độ cửa sổ cần là system, light hoặc dark.')
    for key in ('font_family',):
        if not isinstance(data['appearance'][key],str) or not data['appearance'][key].strip() or any(c in data['appearance'][key] for c in '\n\r";{}'):
            raise ValueError('Tên font không hợp lệ.')
    for color in (data['appearance']['background_color'],data['appearance']['background_color2'],data['appearance']['border_color'],data['appearance']['text_color'],*data['palette'].values(),*(v for k,v in data['komorebi'].items() if k.endswith('_color'))):
        if not isinstance(color,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',color):
            raise ValueError(f'Màu không hợp lệ: {color!r}. Dùng dạng #RRGGBB.')
    if any(k not in COLORS for k in data['palette']):
        raise ValueError('Tên màu trong palette không hợp lệ.')
    if data['island']['default_tab'] not in ('Dashboard','Media','Performance','Weather','Live Activity'):
        raise ValueError('Tab Dynamic Island không hợp lệ.')
    if data['island']['material'] not in ('liquid-soft','liquid-clear','frosted','outline'):
        raise ValueError('Chất liệu Dynamic Island không hợp lệ.')
    if not isinstance(data['weather']['city'],str) or not data['weather']['city'].strip():
        raise ValueError('Tên thành phố không được để trống.')
    if not isinstance(data['weather']['timezone'],str) or not re.fullmatch(r'UTC|auto|[A-Za-z_]+(?:/[A-Za-z_+\-0-9]+)+',data['weather']['timezone']):
        raise ValueError('Múi giờ cần có dạng Asia/Bangkok.')
    return data


def validate_config(config):
    from core.validation.config import YasbConfig
    model=YasbConfig.model_validate(deepcopy(config))
    for name,item in model.widgets.items():
        module,cls=item['type'].rsplit('.',1)
        widget=getattr(import_module('core.widgets.'+module),cls)
        widget.validation_schema.model_validate(item.get('options',{}))
    for name,bar in model.bars.items():
        for widget in (*bar.widgets.left,*bar.widgets.center,*bar.widgets.right):
            if widget not in model.widgets:
                raise ValueError(f'Bar {name}: widget {widget!r} chưa được khai báo.')
    return model


def atomic_write(path, data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if isinstance(data,str):data=data.encode('utf-8')
    descriptor,temp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(descriptor,'wb') as file:
            file.write(data);file.flush();os.fsync(file.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def compose_styles(root, profile):
    root=Path(root)
    settings=load_preferences(root)
    css=(root/'theme-profiles'/profile/'styles.css').read_text(encoding='utf-8')
    from core.utils.theme_tokens import effective_palette,on_accent
    raw_palette=json.loads((root/'theme-profiles'/profile/'palette.json').read_text(encoding='utf-8'))
    base_palette=effective_palette(root,profile)
    overrides=settings['palette']
    if overrides:
        mapping={raw_palette[k].lower():base_palette[k] for k in overrides if k in base_palette and k!='MAUVE'}
        css=re.sub(r'#[0-9a-fA-F]{6}\b',lambda m:mapping.get(m[0].lower(),m[0]),css)
    if 'MAUVE' in overrides:
        accent=base_palette['MAUVE'];ink=on_accent(accent)
        css+=f"\n.yasb-bar .komorebi-workspaces .ws-btn.active {{color:{accent};}}\n.control-center-menu .section.quick-actions .button.active .icon {{background-color:{accent};color:{ink};}}\n.control-center-menu QSlider.slider-control::sub-page:horizontal {{background-color:{accent};}}\n.bar-theme-menu::indicator:checked {{background-color:{accent};}}\n"
    appearance=settings['appearance']
    css+=f'''\n/* Bar settings overrides */
.yasb-bar {{ padding: 0 {appearance['padding']}px; border-radius: {appearance['radius']}px; }}
.yasb-bar .label {{ font-family: "{appearance['font_family']}"; font-size: {appearance['font_size']}px; font-weight: {appearance['font_weight']}; }}
'''
    if appearance['spacing']!=DEFAULTS['appearance']['spacing']:
        css+=f"\n.yasb-bar .widget {{ padding-left: {appearance['spacing']}px; padding-right: {appearance['spacing']}px; }}\n"
    from core.utils.bar_surface import surface_css
    css+=surface_css(settings,base_palette)
    custom=root/'custom.css'
    if custom.exists():css+='\n/* Custom CSS */\n'+custom.read_text(encoding='utf-8')
    return css


def create_snapshot(root, label='Tự động trước khi áp dụng'):
    root=Path(root)
    directory=root/'settings-backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    directory.mkdir(parents=True)
    files=[]
    for name in ('config.yaml','styles.css','theme.json','bar-settings.json','custom.css'):
        if (root/name).is_file():
            shutil.copy2(root/name,directory/name);files.append(name)
    atomic_write(directory/'manifest.json',json.dumps({'label':label,'created':datetime.now().isoformat(),'files':files},ensure_ascii=False,indent=2))
    return directory


def restore_snapshot(root,directory):
    root,directory=Path(root),Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    allowed={'config.yaml','styles.css','theme.json','bar-settings.json','custom.css'}
    files=manifest.get('files',[])
    if not isinstance(files,list) or any(name not in allowed for name in files):
        raise ValueError('Bản sao lưu không hợp lệ.')
    import yaml
    validate_config(yaml.safe_load((directory/'config.yaml').read_bytes()))
    if 'theme.json' in files:
        theme=json.loads((directory/'theme.json').read_text(encoding='utf-8'))
        if not isinstance(theme,dict) or theme.get('name') not in ('light','dark','catppuccin','everforest','red-white','red-black'):
            raise ValueError('Theme trong bản sao lưu không hợp lệ.')
    if 'bar-settings.json' in files:
        validate_preferences(json.loads((directory/'bar-settings.json').read_text(encoding='utf-8')))
    for name in files:
        if not (directory/name).is_file():raise ValueError(f'Bản sao lưu thiếu {name}.')
    if 'custom.css' in files:validate_custom_css((directory/'custom.css').read_text(encoding='utf-8'))
    create_snapshot(root,'Trước khi khôi phục')
    for name in files:atomic_write(root/name,(directory/name).read_bytes())
    # Older snapshots predate preferences; reset only these new overrides.
    if 'bar-settings.json' not in files:atomic_write(root/'bar-settings.json',json.dumps(DEFAULTS))
    if 'custom.css' not in files:atomic_write(root/'custom.css','')


def validate_custom_css(css):
    stripped=re.sub(r'/\*.*?\*/','',css,flags=re.S)
    stripped=re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'','',stripped)
    balance=0
    for char in stripped:
        if char=='{':balance+=1
        elif char=='}':balance-=1
        if balance<0:raise ValueError('CSS có dấu } thừa.')
    if balance:raise ValueError('CSS thiếu dấu }.')
