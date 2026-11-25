"""Render a reference board from the exact fixed palette files; no screen capture."""
from pathlib import Path
from html import escape
import argparse,json,os,sys
parser=argparse.ArgumentParser();parser.add_argument('--runtime');args=parser.parse_args()
if args.runtime:sys.path.insert(0,args.runtime)
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication,QFontDatabase,QImage,QPainter
from PySide6.QtSvg import QSvgRenderer
repo=Path(__file__).resolve().parent.parent;directory=repo/'config/wallpaper-presets'
app=QGuiApplication([]);identifier=QFontDatabase.addApplicationFont(str(repo/'config/dynamic-island/assets/GoogleSansFlex.ttf'));families=QFontDatabase.applicationFontFamilies(identifier);family=families[0] if families else 'Arial'
catalog=json.loads((directory/'catalog.json').read_text(encoding='utf-8'));shapes=[]
def text(x,y,value,color,size=14,weight=400):
    return f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}">{escape(value)}</text>'
shapes.append('<rect width="1440" height="810" fill="#101116"/>')
shapes.append(text(39,49,'18 preset cố định','#f0f0f5',32,600))
shapes.append(text(39,79,'9 bộ màu · Sáng và tối · Tự chọn preset khi đổi wallpaper','#a9a9b6',16))
for index,entry in enumerate(catalog):
    p=json.loads((directory/entry['id']/'palette.json').read_text());x=39+(index%6)*230;y=106+(index//6)*220
    shapes.append(f'<g transform="translate({x} {y})"><rect width="212" height="202" rx="18" fill="{p["MANTLE"]}" stroke="{p["SURFACE2"]}"/>')
    shapes.append(text(16,32,entry['family'].title(),p['TEXT'],19,600));shapes.append(text(157,31,entry['tone'].upper(),p['MUTED'],10,600))
    shapes.append(f'<rect x="16" y="53" width="180" height="32" rx="16" fill="{p["BASE"]}" stroke="{p["SURFACE2"]}"/>')
    shapes.append(text(29,74,'Ponie',p['TEXT'],13,600));shapes.append(f'<path d="M169 63h12m-12 6h12m-12 6h12" stroke="{p["MAUVE"]}" stroke-width="1.5"/>')
    shapes.append(f'<rect x="16" y="102" width="35" height="35" rx="10" fill="{p["SURFACE2"]}"/>')
    shapes.append(f'<path d="m25 121 4 5 12-13" fill="none" stroke="{p["MAUVE"]}" stroke-width="2"/>')
    shapes.append(text(61,117,'Now playing',p['TEXT'],15,600));shapes.append(text(61,135,'Media · Focus',p['MUTED'],12))
    shapes.append(f'<rect x="16" y="151" width="180" height="4" rx="2" fill="{p["SURFACE2"]}"/><rect x="16" y="151" width="109" height="4" rx="2" fill="{p["MAUVE"]}"/>')
    shapes.append(text(16,186,'Aa',p['TEXT'],20,600))
    for i,key in enumerate(('MAUVE','LAVENDER','PINK','ROSEWATER')):shapes.append(f'<circle cx="{130+i*18}" cy="180" r="5" fill="{p[key]}"/>')
    shapes.append('</g>')
shapes.append(text(39,787,'Màu chữ, nền, nút và viền lấy nguyên từ preset đã thiết kế. Wallpaper chỉ dùng để chọn bộ phù hợp.','#a9a9b6',14))
svg='<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="810" viewBox="0 0 1440 810"><g font-family="'+escape(family)+'">'+''.join(shapes)+'</g></svg>'
out=repo/'docs/screenshots';out.mkdir(exist_ok=True)
(out/'wallpaper-presets.svg').write_text(svg,encoding='utf-8')
image=QImage(1440,810,QImage.Format.Format_ARGB32_Premultiplied);image.fill(0);painter=QPainter(image);QSvgRenderer(svg.encode()).render(painter,QRectF(0,0,1440,810));painter.end();assert image.save(str(out/'wallpaper-presets.png'))
print(out/'wallpaper-presets.png')
