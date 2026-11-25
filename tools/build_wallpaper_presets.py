"""Build checked-in palettes/CSS from hand-authored roles, never from a wallpaper.

Developer utility only. Runtime selection copies these exact files.
"""
from pathlib import Path
import json,re,sys
repo=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(repo/'config/dynamic-island'))
from theme_tokens import normalize_palette,on_accent

ROLES=('CRUST','MANTLE','BASE','SURFACE','SURFACE2','OVERLAY','MUTED','TEXT','MAUVE','LAVENDER','PINK','ROSEWATER')
# Each row explicitly defines every role. Hue matching never edits these values.
DESIGNS={
 'lavender':('Lavender','#9b7de0',
  '120f1c 191522 211b2c 2b2439 372e48 8b819d bcb2cc eee8f8 c6a5ef b9b7f4 e5b1d0 e2d3e7',
  'ffffff f8f5fc f0ebf7 e9e2f2 dfd6ea 81718e 61526f 282036 67429e 575797 913c72 7a4c67'),
 'rose':('Rose','#ec74b1',
  '180f16 20161d 2a1d26 352732 42323f 9d8595 cfb4c4 f7e9f1 efb0ce d2b4e5 f3c1b6 f1dce5',
  'fffafb fbf3f7 f6e9ef efdee7 e7d4df 8b6c80 6d4e62 34212e 96386c 6d4b93 9a463e 7e4b63'),
 'ruby':('Ruby','#ef535f',
  '170f12 21161b 2b1d23 37262d 46333b a78a97 d2b8c3 f8eaf0 f3a0aa d4b1d6 f2bbb0 f0d6d6',
  'fffafb fcf2f4 f7e8ed f0dde4 e7d2dc 916b7d 714d5c 35212b a12f4b 79457f 954b39 854853'),
 'amber':('Amber','#e7a64a',
  '16120d 201a14 2a221b 362d23 443a2e 9e927e cabca4 f5ede0 e8bf80 c8c49a e2ac91 ebdac0',
  'fffdf8 faf6ec f4eddf ece2d1 e2d7c3 88785e 695941 33291d 92500c 65622d 965035 7e563c'),
 'sage':('Sage','#70ad6b',
  '101610 182019 202a23 29372d 34443a 879b87 b6c8b5 eaf4e9 b0cca1 99c9be d4c49d dae6d0',
  'fcfefa f5f8f0 edf2e5 e2ead9 d6e1cb 73836b 52644b 243023 41672d 256b5d 756129 566542'),
 'teal':('Teal','#48b8ad',
  '0d1515 152020 1d2a2b 273638 334548 819e98 b0cac5 e7f4f1 99cec3 a6c3e2 c0c99f d6e7de',
  'fbfefd f1f8f5 e7f2ed dbeae3 cddfd7 6a8579 4c665c 20322d 126858 3c5c89 5e662b 466757'),
 'cyan':('Cyan','#52b7d1',
  '0d141a 141e26 1c2832 273541 344452 819bab b4c6d3 e8f2f8 9acde3 b5c0ed a4d0c0 d5e6eb',
  'fbfdff f1f7fa e7f0f5 dbe7ee cedde6 6e8290 4d626e 21303a 146482 52588a 25694f 486471'),
 'blue':('Blue','#6b9fe8',
  '0e121b 161d28 1e2835 293545 364557 8196b0 b5c4db eaf0fa a9c4ed c8b8e7 99cbd3 d6e2f3',
  'fcfdff f3f6fc eaf0f8 dee6f1 d1dcea 72839c 50617b 233046 315c9a 6b4c96 1b6874 4e607c'),
 'graphite':('Graphite','#9b9ba5',
  '121317 1a1b20 22242a 2d3038 3a3e48 8d93a3 bfc3cf eceef3 c3c9d6 b7bfd1 c5c3cf dedfe5',
  'ffffff f7f7fa eff0f4 e6e8ee dbdee6 7b8292 596071 262933 4d576b 545b73 66566a 5c606c'),
}

def render_css(template,palette,reference):
    aliases={'#11111b':'CRUST','#181825':'MANTLE','#1e1e2e':'BASE','#313244':'SURFACE','#45475a':'SURFACE2',
             '#6c7086':'OVERLAY','#a6adc8':'MUTED','#cdd6f4':'TEXT','#ffffff':'TEXT','#b4befe':'LAVENDER',
             '#cba6f7':'MAUVE','#f5c2e7':'PINK','#f5e0dc':'ROSEWATER'}
    aliases.update({value.lower():key for key,value in reference.items()})
    def mapped(color):
        role=aliases.get(color.lower());return palette[role] if role in palette else color
    css=re.sub(r'#[0-9a-fA-F]{6}\b',lambda m:mapped(m[0]),template)
    def rgb(match):
        color='#'+''.join(f'{int(match[i]):02x}' for i in (2,3,4));new=mapped(color)
        if new==color:return match[0]
        values=','.join(str(int(new[i:i+2],16)) for i in (1,3,5))
        return match[1]+'('+values+((','+match[5]) if match[5] is not None else '')+')'
    css=re.sub(r'\b(rgb|rgba)\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([0-9.]+)\s*)?\)',rgb,css)
    return css+'\n/* Fixed preset: readable selected controls. */\n.control-center-menu .section.quick-actions .button.active .icon {color:'+on_accent(palette['MAUVE'])+';}\n'

def main():
    target=repo/'config/wallpaper-presets';target.mkdir(exist_ok=True)
    template=(repo/'config/theme-profiles/catppuccin/styles.css').read_text(encoding='utf-8')
    reference=json.loads((repo/'config/theme-profiles/catppuccin/palette.json').read_text(encoding='utf-8'))
    catalog=[]
    for family,(label,anchor,dark,light) in DESIGNS.items():
        for tone,row in (('dark',dark),('light',light)):
            values=row.split();assert len(values)==len(ROLES),family
            # Offline contrast review. The final files are immutable at runtime.
            palette=normalize_palette(dict(zip(ROLES,('#'+value for value in values))))
            assert normalize_palette(palette)==palette
            entry={'id':family+'-'+tone,'name':label+' · '+('Tối' if tone=='dark' else 'Sáng'),'family':family,'tone':tone,'match_color':anchor}
            directory=target/entry['id'];directory.mkdir(exist_ok=True)
            (directory/'palette.json').write_text(json.dumps(palette,indent=2)+'\n',encoding='utf-8')
            (directory/'styles.css').write_text(render_css(template,palette,reference),encoding='utf-8')
            catalog.append(entry)
    (target/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name in ('palette.json','styles.css'):
        (repo/'config/theme-profiles/wallpaper'/name).write_bytes((target/'lavender-dark'/name).read_bytes())
    print(f'Built {len(catalog)} fixed presets. Runtime never creates new palette colors.')

if __name__=='__main__':main()
