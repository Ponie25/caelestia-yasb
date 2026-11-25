"""Command/gallery regressions. All power, wallpaper and theme mutations are mocked."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib.machinery,importlib.util,json,os,sys,tempfile,traceback,uuid,time,io
install=Path(sys.argv[1]).resolve();root=install/'config/dynamic-island'
os.environ['QT_QPA_PLATFORM']='offscreen';sys.path[:0]=[str(root),str(root/'runtime')]
os.environ['YASB_SETTINGS_NO_EXTERNAL']='1'
from PySide6.QtCore import QEventLoop,QTimer,Qt,QPointF
from PySide6.QtGui import QColor,QCursor,QImage,QKeyEvent,QMouseEvent
from PySide6.QtWidgets import QApplication
from launcher_core import query,Result
from launcher_windows import Catalog,Shortcut
from launcher_wallpapers import discover,Wallpapers,apply_wallpaper
from launcher_actions import ControlRequest,power_action
from PySide6.QtNetwork import QLocalServer
import launcher as launcher_module
from launcher_view import LauncherView
from wallpaper_data import steam_favorites,dominant,load_presets,choose_preset
from theme_tokens import normalize_palette,contrast
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
errors=[]
def error(kind,value,tb):
    text=''.join(traceback.format_exception(kind,value,tb));errors.append(text);print(text,flush=True)
sys.excepthook=error
def wait(ms=500):
    loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec()

# Real asynchronous local sockets, confined to a random test server.
for response in (b'{"ok":true}\n',b'not json\n',None):
    server=QLocalServer();name='caelestia-command-test-'+uuid.uuid4().hex;assert server.listen(name)
    received=[];replies=[];connections=[]
    def connected():
        socket=server.nextPendingConnection();connections.append(socket)
        def read():
            received.append(bytes(socket.readAll()))
            if response is not None:socket.write(response);socket.disconnectFromServer()
        socket.readyRead.connect(read)
    server.newConnection.connect(connected)
    request=ControlRequest(None);request.finished.connect(lambda ok,message:replies.append((ok,message)))
    request.start(name,{'action':'theme','name':'dark'});wait(2300 if response is None else 150)
    assert len(replies)==1 and replies[0][0]==(response==b'{"ok":true}\n'),replies
    assert json.loads(b''.join(received))=={'action':'theme','name':'dark'}
    for socket in connections:socket.abort()
    server.close()
rows=query('>',[]);assert len(rows)>7 and not any(row.value in ('shutdown','reboot','logout') for row in rows)
assert query('>shutdown',[])[0].kind=='hint'
assert query('>restart',[],context={'dangerous_actions':True})[0].value=='reboot'
assert query('>scheme cat',[],context={'theme':'catppuccin','palettes':{'catppuccin':['#111111','#cba6f7']}})[0].current
assert query('>calc sqrt(144)',[])[0].value=='12'
assert query('>scheme missing99',[])[0].kind=='hint'
html=b'<div class="workshopBrowseItems"><div id="sharedfile_123456"><div id="sharedfile_654321"></div>'
with patch('wallpaper_data.urlopen',return_value=io.BytesIO(html)):
    assert steam_favorites(123)['ids']==['123456','654321']
with patch('wallpaper_data.urlopen',side_effect=[io.BytesIO(b'<div class="workshopBrowseItems" id="sharedfile_123456"><a href="?p=2">Next</a>'),io.BytesIO(html)]) as fetch:
    assert steam_favorites(123)['ids']==['123456','654321'] and fetch.call_count==2
many=[dict(path=str(i),name=f'Wallpaper {i}',favorite=True) for i in range(40)]
assert len(query('>wallpaper ',[],context={'wallpapers':many}))==40,'Every installed favorite must be reachable using arrows, not only the first page'
with patch('wallpaper_data.urlopen',side_effect=OSError('offline')):
    assert steam_favorites(123,{'account':123,'ids':['123456'],'updated':0},force=True)['ids']==['123456']
assert dominant([(240,40,60)]*100+[(110,110,110)]*1000).startswith('#f0')
catalog=load_presets(root.parent);assert len(catalog)==18
import wallpaper_data
assert not hasattr(wallpaper_data,'make_palette'),'Runtime must only select existing palettes'
for entry in catalog:
    assert choose_preset(entry['match_color'],entry['tone']=='dark',catalog)['id']==entry['id']
    palette=json.loads((root.parent/'wallpaper-presets'/entry['id']/'palette.json').read_text())
    assert normalize_palette(palette)==palette
    for bg in ('BASE','MANTLE','SURFACE','SURFACE2'):
        assert contrast(palette['TEXT'],palette[bg])>=7
        assert contrast(palette['MUTED'],palette[bg])>=4.8
        for key in ('MAUVE','LAVENDER','PINK','ROSEWATER'):assert contrast(palette[key],palette[bg])>=4.5
for dark in (True,False):
    for gray in ('#000000','#808080','#ffffff'):assert choose_preset(gray,dark,catalog)['family']=='graphite'
    assert choose_preset('#ff0000',dark,catalog)['family']=='ruby'
    assert choose_preset('#00ff00',dark,catalog)['family']=='sage'
    assert choose_preset('#0000ff',dark,catalog)['family']=='blue'
with patch('launcher_actions.subprocess.run',return_value=SimpleNamespace(returncode=0)) as command:
    power_action('reboot');assert command.call_args.args[0][-3:]==['/r','/t','0']
with patch('launcher_actions._sleep') as sleep:power_action('sleep');sleep.assert_called_once()
with patch('launcher_actions.ctypes.windll.user32.LockWorkStation',return_value=1) as lock:power_action('lock');lock.assert_called_once()
try:power_action('reboot /f')
except ValueError:pass
else:raise AssertionError('Query text reached an executable action')

loader=importlib.machinery.SourceFileLoader('command_island',str(root/'island.pyw'));spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);loader.exec_module(module)
class Glass:
    hwnd=None;failed=True;wants_compact=False;wants_optical=False;visible=False;mix=0;enabled=False
    def __init__(self,*_):pass
    def configure(self,*_):pass
    def prepare(self):pass
    def sync(self,*_):pass
    def hide(self):pass
    def close(self):pass
with tempfile.TemporaryDirectory(prefix='launcher-commands-') as directory:
    folder=Path(directory)
    for name,color in [('Aurora','#6359ac'),('Forest','#426659'),('Rose','#9b475a'),('Sky','#527ca5')]:
        image=QImage(640,360,QImage.Format.Format_RGB32);image.fill(QColor(color));assert image.save(str(folder/(name+'.png')))
    project=folder/'Project';project.mkdir();(project/'project.json').write_text(json.dumps({'title':'Engine scene','preview':'../Aurora.png','workshopid':'123456'}),encoding='utf-8')
    items=discover(folder);assert len(items)==5
    assert next(item for item in items if item['engine'])['preview']=='','Project preview must stay inside its own directory'
    engine=folder/'wallpaper64.exe';engine.write_bytes(b'fixture')
    with patch('launcher_wallpapers.running_engine',return_value=engine),patch('launcher_wallpapers.subprocess.run',return_value=SimpleNamespace(returncode=0)) as launch:
        apply_wallpaper(next(item for item in items if item['engine']),engine)
        assert launch.call_args.args[0][1:4]==['-control','openWallpaper','-file']
    with patch('launcher_wallpapers.running_engine',return_value=None),patch('comtypes.client.CreateObject',return_value=SimpleNamespace(SetWallpaper=lambda *args:None)) as desktop:
        apply_wallpaper(items[0]);assert desktop.called
    with patch.object(module,'MaterialLayer',Glass),patch.object(module.Island,'_warm_up'),patch.object(Catalog,'start'),patch.object(Shortcut,'start'),patch('launcher_focus.activate',return_value=True):
        island=module.Island(lambda *_:None,lambda:None);island.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        island.dock.pressed_buttons=lambda:set();island._launcher_focus_lost=lambda:None
        island.follow_bar=lambda:island.show()
        island.catalog.apps=[dict(id='notes',name='Notepad',target=str(folder/'fake.lnk'))]
        island.wallpapers.items=items;island.wallpapers.loaded=True;island.wallpapers.checked=time.time();island.wallpapers.current=items[0]['path']
        island.launcher_options['wallpaper_favorites_only']=False
        island.open_launcher();wait(650)
        edit=island.launcher_view.search.edit
        edit.setText('>scheme ');wait(650)
        assert not island.launcher_view.results.gallery and len(island.launcher_view.rows())==7
        assert island.launcher_view.geometry().bottom()<island.height(),'More command rows must grow the native window as well as its painted surface'
        themes=[];island._launcher_control=lambda payload,after=None:themes.append(payload)
        island._launcher_accept(island.launcher_view.rows()[0]);assert themes[-1]['action']=='theme'
        edit.setText('>wallpaper ');wait(650)
        assert island.launcher_view.results.gallery and island.launcher_view.body_height()==158
        assert island.launcher_view.results.horizontalScrollBar().maximum()>0
        assert edit.hasFocus(),'Changing to wallpaper gallery stole typing focus'
        view=island.launcher_view.results;start=view.horizontalScrollBar().value()
        for _ in range(3):app.sendEvent(edit,QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_Down,Qt.KeyboardModifier.NoModifier))
        assert view.currentIndex().row()==3 and edit.hasFocus()
        assert view.horizontalScrollBar().value()==start,'Keyboard navigation must not jump the viewport'
        wait(70);middle=view.horizontalScrollBar().value();target=round(view.scroll_animation.endValue())
        assert start<middle<target,(start,middle,target)
        view.entered.emit(view.model().index(0,0));assert view.currentIndex().row()==3,'Hover enter while scrolling must not steal keyboard selection'
        position=QCursor.pos();view.last_mouse=position
        event=QMouseEvent(QMouseEvent.Type.MouseMove,QPointF(10,10),QPointF(position),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
        app.sendEvent(view.viewport(),event);assert view.currentIndex().row()==3
        app.sendEvent(edit,QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_Up,Qt.KeyboardModifier.NoModifier));assert view.currentIndex().row()==2
        wait(650)
        island.wallpapers.engine_favorites={'123456'};island._launcher_filter_wallpapers(True);wait(400)
        assert len(island.launcher_view.rows())==1 and island.launcher_view.rows()[0].favorite
        assert island.launcher_view.rows()[0].value==str(project/'project.json')
        island.wallpapers.engine_favorites=set();island.wallpapers.changed.emit();wait(400)
        assert not any(row.kind=='wallpaper' for row in island.launcher_view.rows()),'An empty favorites list must never fall back to all wallpapers'
        island._launcher_filter_wallpapers(False);wait(400)
        island.wallpapers.items=[];edit.setText('>wallpaper missing');wait(400)
        assert not island.launcher_view.results.gallery,'Empty libraries must show readable instructions, not a blank carousel'
        island.wallpapers.items=items
        edit.setText('>calc 2+3');wait(650);assert not island.launcher_view.results.gallery and island.launcher_view.rows()[0].value=='5'
        power=[]
        with patch.object(launcher_module,'power_action',side_effect=lambda action:power.append(action)):
            edit.setText('>shutdown');island._launcher_accept(Result('bad','test','','power','shutdown'));assert not power
            island.launcher_options['dangerous_actions']=True
            edit.setText('>reboot');island._launcher_accept(query('>reboot',[],context={'dangerous_actions':True})[0])
            assert island.launcher_confirmation=='reboot' and island.launcher_view.rows()[0].kind=='power_cancel' and not power
            confirmation=island.launcher_view.rows()[1];edit.setText('>calc 2+2');island._launcher_accept(confirmation);assert not power
            edit.setText('>sleep');island._launcher_accept(query('>sleep',[])[0]);island._launcher_accept(island.launcher_view.rows()[1]);wait(700)
            assert power==['sleep'] and not island.launcher_active
        island.open_launcher();edit.setText('>wallpaper ');wait(650)
        with patch.object(launcher_module,'apply_wallpaper') as wallpaper:
            island._launcher_accept(next(row for row in island.launcher_view.rows() if row.kind=='wallpaper'));wait(650)
            wallpaper.assert_called_once()
        screenshots=os.environ.get('LAUNCHER_COMMAND_SCREENSHOTS')
        if screenshots:
            out=Path(screenshots);out.mkdir(parents=True,exist_ok=True)
            for name,text in [('commands','>'),('schemes','>scheme '),('wallpapers','>wallpaper ')]:
                island.open_launcher();edit.setText(text);wait(750);island.grab(island._surface_rect().toAlignedRect()).save(str(out/(name+'.png')))
        island.close_launcher(restore=False);wait(650)
        assert island._action_at(island._surface_rect().center())=='open'
        island.wallpapers._image(island.wallpapers.generation-1,'old',QImage());assert 'old' not in island.wallpapers.images
        for i in range(70):island.wallpapers._image(island.wallpapers.generation,str(i),QImage(32,18,QImage.Format.Format_RGB32))
        assert len(island.wallpapers.images)==32
        island.wallpapers.stop();island.catalog.stop();island.volume.stop();island.dashboard.metrics.close();island.glass.close();island.hide();island.deleteLater();app.processEvents()
assert not errors,errors
print('PASS: original command groups, disabled power, fixed native argv, gallery/focus, stale confirmation, mocked actions, presets and collapsed-menu invariant.')
