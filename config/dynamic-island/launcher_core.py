"""Offline launcher queries. No query is evaluated as Python or shell code."""
from dataclasses import dataclass
import ast
import math
import operator
import re
import unicodedata
from urllib.parse import quote_plus, urlsplit


@dataclass(frozen=True)
class Result:
    key: str
    title: str
    detail: str
    kind: str
    value: str = ''
    glyph: str = 'apps'


def normalized(value):
    value=value.casefold().replace('đ','d')
    return ''.join(c for c in unicodedata.normalize('NFKD',value) if not unicodedata.combining(c))


def rank(query,name):
    query,name=normalized(query).strip(),normalized(name)
    if not query:return 0
    if query==name:return 1000
    if name.startswith(query):return 850-len(name)/100
    if query in name:return 700-name.index(query)-len(name)/100
    tokens=query.split()
    if all(token in name for token in tokens):return 600-sum(name.index(token) for token in tokens)/10
    initials=''.join(word[0] for word in re.findall(r'\w+',name))
    if initials.startswith(query.replace(' ','')):return 550
    cursor=-1;gaps=0
    for char in query.replace(' ',''):
        at=name.find(char,cursor+1)
        if at<0:return None
        gaps+=at-cursor-1;cursor=at
    return 400-gaps*3-len(name)/100


FUNCS={name:getattr(math,name) for name in ('sqrt','sin','cos','tan','asin','acos','atan','log','log10','log2','exp','floor','ceil','degrees','radians')}
FUNCS.update(abs=abs,round=round,min=min,max=max)
OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,
     ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow}


def calculate(expression):
    expression=expression.strip().replace('×','*').replace('÷','/').replace('−','-').replace('^','**').replace('π','pi')
    if not expression or len(expression)>180:return None
    expression=re.sub(r'(\d+(?:\.\d+)?)\s*%\s*(?:of|cua)\s*',r'(\1/100)*',expression,flags=re.I)
    expression=re.sub(r'(\d+(?:\.\d+)?)\s*%(?!\s*[\d.])',r'(\1/100)',expression)
    try:
        tree=ast.parse(expression,mode='eval')
        if len(list(ast.walk(tree)))>90:return None
        def visit(node):
            if isinstance(node,ast.Expression):return visit(node.body)
            if isinstance(node,ast.Constant) and type(node.value) in (int,float):value=float(node.value)
            elif isinstance(node,ast.Name) and node.id in ('pi','e','tau'):value=getattr(math,node.id)
            elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
                value=visit(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
            elif isinstance(node,ast.BinOp) and type(node.op) in OPS:
                left,right=visit(node.left),visit(node.right)
                if isinstance(node.op,ast.Pow) and abs(right)>1000:raise ValueError()
                value=OPS[type(node.op)](left,right)
            elif isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in FUNCS and not node.keywords and 0<len(node.args)<=4:
                args=[visit(arg) for arg in node.args]
                if node.func.id=='round' and len(args)==2:args[1]=max(-15,min(15,int(args[1])))
                value=FUNCS[node.func.id](*args)
            else:raise ValueError()
            if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>1e100:raise ValueError()
            return value
        return f'{visit(tree):.12g}'
    except (ArithmeticError,ValueError,TypeError,SyntaxError,RecursionError):return None


UNITS={}
def _units(category,entries):
    for aliases,factor in entries:
        for alias in aliases.split('|'):UNITS[alias.casefold()]=(category,factor)
_units('length',[('m|met|meter',1),('km',1000),('cm',.01),('mm',.001),('mi|mile|miles',1609.344),('ft|feet',.3048),('in|inch|inches',.0254),('yd',.9144)])
_units('mass',[('kg|kilogram',1),('g|gram',.001),('mg',.000001),('lb|lbs',.45359237),('oz',.028349523125)])
_units('time',[('s|sec|second|seconds',1),('min|minute|minutes',60),('h|hr|hour|hours',3600),('day|days',86400)])
_units('volume',[('l|liter|litre',1),('ml',.001),('gal|gallon',3.785411784)])
_units('data',[('b|byte|bytes',1),('kb',1000),('mb',1e6),('gb',1e9),('tb',1e12),('kib',1024),('mib',1024**2),('gib',1024**3),('tib',1024**4)])


def convert(expression):
    match=re.fullmatch(r'\s*([-+]?\d+(?:\.\d+)?)\s*([\w°]+)\s+(?:to|in|sang|=)\s*([\w°]+)\s*',normalized(expression))
    if not match:return None
    number,source,target=match.groups();number=float(number);source=source.replace('°','');target=target.replace('°','')
    if source in ('c','f','k') and target in ('c','f','k'):
        c=(number-32)*5/9 if source=='f' else number-273.15 if source=='k' else number
        if c < -273.15:return None
        result=c*9/5+32 if target=='f' else c+273.15 if target=='k' else c
    elif source in UNITS and target in UNITS and UNITS[source][0]==UNITS[target][0]:result=number*UNITS[source][1]/UNITS[target][1]
    else:return None
    return f'{result:.12g} {match.group(3)}'


COMMANDS=(
    Result('calc','Máy tính','Tính biểu thức, phần trăm và đổi đơn vị','complete','>calc ','calculate'),
    Result('web','Tìm trên web','Gõ nội dung rồi Enter để tìm bằng trình duyệt','complete','>web ','search'),
    Result('bar','Cài đặt thanh bar','Đổi giao diện, nền bar và Dynamic Island','action','bar','settings'),
    Result('settings','Cài đặt Windows','Mở ứng dụng Settings','action','settings','settings'),
    Result('downloads','Tải xuống','Mở thư mục Downloads','action','downloads','folder'),
    Result('documents','Tài liệu','Mở thư mục Documents','action','documents','folder'),
    Result('island','Menu Dynamic Island','Mở Dashboard và các tab hiện có','action','island','apps'),
    Result('timer','Hẹn giờ','Mở Live Activity để đặt hẹn giờ','action','timer','timer'),
)


def query(text,apps,history=None):
    """Return bounded rows; only Enter/click ever runs a result."""
    text=text.strip();history=history or {}
    if text.startswith('>'):
        command,_,rest=text[1:].partition(' ')
        if command.casefold() in ('calc','calculate'):
            answer=convert(rest) or calculate(rest)
            return [Result('answer',answer or 'Nhập biểu thức để tính','Enter để sao chép' if answer else 'Ví dụ: sqrt(144) · 15% of 200 · 10 km to mi','copy' if answer else 'hint',answer or '', 'calculate')]
        if command.casefold() in ('web','google') and rest:
            return [Result('web-result',rest,'Tìm bằng Google · Enter để mở trình duyệt','url','https://www.google.com/search?q='+quote_plus(rest),'search')]
        rows=[(rank(command,row.key+' '+row.title),row) for row in COMMANDS]
        return [row for score,row in sorted((r for r in rows if r[0] is not None),key=lambda r:r[0],reverse=True)][:7]
    answer=convert(text) or (calculate(text) if re.search(r'[\dπ]|^(?:sqrt|sin|cos|tan|log|abs|round|pi|tau)\b',text) else None)
    if answer:return [Result('answer',answer,'Enter để sao chép kết quả','copy',answer,'calculate')]
    if re.fullmatch(r'[\d\s.+*/()%^-]+',text) and re.search(r'\d',text) and re.search(r'[+*/()%^\-]',text):
        return [Result('math-hint','Nhập tiếp biểu thức…' if text[-1:] in '+-*/^(' else 'Chưa tính được biểu thức này','Kiểm tra dấu ngoặc, phép chia và các con số','hint','','calculate')]
    if re.match(r'^(https?://|www\.)',text,re.I):
        url=text if '://' in text else 'https://'+text
        if urlsplit(url).hostname:return [Result('url',text,'Mở trong trình duyệt mặc định','url',url,'globe')]
    ranked=[]
    for app in apps:
        score=rank(text,app['name'])
        if score is None:continue
        frequency=history.get(app['id'],{})
        score+=min(35,math.log1p(max(0,frequency.get('count',0)))*8)
        if not text:score+=frequency.get('at',0)/1e9
        if not text and not history:
            initial=('file explorer','windows terminal','notepad','calculator','settings','zen browser','visual studio code')
            name=normalized(app['name'])
            if name in initial:score+=100-initial.index(name)*5
        ranked.append((score,app))
    ranked.sort(key=lambda r:(-r[0],normalized(r[1]['name'])))
    rows=[Result(app['id'],app['name'],app.get('description') or 'Ứng dụng','app',app['target']) for _,app in ranked[:7]]
    if text and len(rows)<7:rows.append(Result('web-result','Tìm “'+text+'” trên web','Mở kết quả bằng trình duyệt','url','https://www.google.com/search?q='+quote_plus(text),'search'))
    return rows
