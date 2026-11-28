r"""Smoke-test an isolated prepared Windows install without changing saved settings.

Usage: <install>\python\python.exe tools\check_install.py <install>
"""
from importlib.machinery import EXTENSION_SUFFIXES, PathFinder
from importlib.util import spec_from_file_location
from pathlib import Path
import importlib,json,os,shutil,sys,tempfile,traceback
from unittest.mock import patch

install=Path(sys.argv[1]).resolve();lib=install/'yasb/lib'
os.environ['YASB_SETTINGS_NO_EXTERNAL']='1'
os.environ['QT_QPA_PLATFORM']='windows:fontengine=gdi'
temporary=tempfile.TemporaryDirectory(prefix='caelestia-settings-check-')
root=Path(temporary.name)/'config';shutil.copytree(install/'config',root,ignore=shutil.ignore_patterns('runtime','__pycache__','*.log','*.lock','settings-backups'))
os.environ['YASB_CONFIG_HOME']=str(root)
sys.path[:0]=[str(lib/'library.zip'),str(lib)]
libraries=[os.add_dll_directory(str(path)) for path in (lib,lib.parent,lib/'PyQt6/Qt6/bin')]

class FrozenExtensions:
    @staticmethod
    def find_spec(fullname,path=None,target=None):
        for suffix in EXTENSION_SUFFIXES:
            candidate=lib/(fullname+suffix)
            if candidate.is_file():return spec_from_file_location(fullname,candidate)

sys.meta_path.insert(sys.meta_path.index(PathFinder),FrozenExtensions())
import yaml
from PyQt6.QtCore import QObject,QTimer,QEventLoop,Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QApplication
from core.utils.bar_preferences import validate_config,load_preferences,compose_styles
from core.utils.bar_theme import BarThemeController
from core.utils.bar_settings import BarSettingsDialog
from qt_css_engine import extract_rules,TransitionEngine
from core.utils.ui_motion import install_menu_motion

errors=[]
def error(kind,value,tb):
    detail=''.join(traceback.format_exception(kind,value,tb));errors.append(detail);print(detail,flush=True)
sys.excepthook=error
app=QApplication([]);app.setQuitOnLastWindowClosed(False);install_menu_motion(app)
for font in (root/'fonts').glob('*.ttf'):assert QFontDatabase.addApplicationFont(str(font))!=-1,font.name
assert 'JetBrainsMono NFP Light' in QFontDatabase.families(),'Missing configured bar font'
config=validate_config(yaml.safe_load((root/'config.yaml').read_bytes()))
for item in config.widgets.values():
    path,cls=item['type'].rsplit('.',1)
    getattr(importlib.import_module('core.widgets.'+path),cls).validation_schema.model_validate(item['options'])

class Manager(QObject):
    def __init__(self):
        super().__init__();self.config=config
        self.stylesheet,rules=extract_rules((root/'styles.css').read_text(encoding='utf-8'));self.engine=TransitionEngine(rules)
    def on_styles_modified(self):pass
    def on_config_modified(self):pass

def wait(ms=400):
    loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec()

controller=BarThemeController(Manager(),root);dialog=BarSettingsDialog(controller);controller.settings_dialog=dialog
dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen);dialog.show();wait()
saved=(root/'bar-settings.json').read_bytes()
preferences=load_preferences(root)
assert dialog._collect_preferences()==preferences
assert dialog.pages.count()==8
dialog.settings_search.setText('font');app.processEvents();assert dialog.search_results.count()>0
dialog.search_controller.activate();wait()
assert dialog.nav.currentRow()==0 and not dialog.settings_search.text()
assert (root/'bar-settings.json').read_bytes()==saved

# Launcher IPC modifies only the disposable config and respects Settings drafts.
entry=controller.settings_entry
def local_request(message):
    socket=QLocalSocket();socket.connectToServer(entry.name);wait(50)
    assert socket.state()==QLocalSocket.LocalSocketState.ConnectedState
    packet=(json.dumps(message,ensure_ascii=False)+'\n').encode('utf-8')
    socket.write(packet[:5]);wait(25);assert not socket.bytesAvailable(),'Do not dispatch an incomplete message'
    socket.write(packet[5:]);wait(100)
    response=json.loads(bytes(socket.readAll()));socket.abort();return response['ok']
with patch.object(controller,'request_settings') as open_settings:
    assert local_request({'action':'open','page':4});open_settings.assert_called_once_with(4)
    for page in (True,-1,8,'4'):assert not entry._dispatch({'action':'open','page':page})
assert not entry._dispatch({'action':'theme','name':'not-a-theme'})
assert not entry._dispatch({'action':'exec','command':'anything'})
assert not local_request({'action':'wallpaper_directory','path':'relative/path'})
assert not local_request({'action':'wallpaper_options','options':{'anything':True}})
assert not local_request({'action':'wallpaper_options','options':{'wallpaper_favorites_only':'yes'}})
assert local_request({'action':'wallpaper_options','options':{'wallpaper_favorites_only':True,'wallpaper_theme_mode':'current'}})
wallpaper_directory=str(root.parent/'Pictures')
assert entry._dispatch({'action':'wallpaper_directory','path':wallpaper_directory})
updated=load_preferences(root);assert updated['launcher']['wallpaper_directory']==wallpaper_directory
assert updated['launcher']['dangerous_actions'] is False
draft='{"appearance":'
dialog.raw_preferences.setPlainText(draft)
dialog.raw_preferences.document().setModified(True)
other_directory=str(root.parent/'Other')
assert entry._dispatch({'action':'wallpaper_directory','path':other_directory})
assert load_preferences(root)['launcher']['wallpaper_directory']==other_directory
assert dialog.raw_preferences.toPlainText()==draft
assert dialog.raw_preferences.document().isModified()
dialog.raw_preferences.setPlainText(json.dumps(load_preferences(root),ensure_ascii=False,indent=2))
dialog.raw_preferences.document().setModified(False)
assert entry._dispatch({'action':'wallpaper_directory','path':wallpaper_directory})
for value in ('relative/path',42,'bad\npath'):
    try:entry._dispatch({'action':'wallpaper_directory','path':value})
    except (ValueError,TypeError):pass
    else:raise AssertionError('Invalid wallpaper directory accepted')

dialog._motion_preset(165);wait()
assert load_preferences(root)['animations']['popup_ms']==165 and load_preferences(root)['island']['speed']==1.
dialog._motion_preset(220);wait()
assert dialog.motion_presets[220].isChecked()
dialog.resize(680,620);wait();assert dialog.nav.property('compact')
assert len(controller.theme_labels)==35 and 'wallpaper' not in controller.theme_labels
for name in controller.theme_labels:
    assert entry._dispatch({'action':'theme','name':name});wait()
    assert controller.current==name and dialog.theme_buttons[name].isChecked()
    assert load_preferences(root)['launcher']['wallpaper_directory']==wallpaper_directory
    assert load_preferences(root)['launcher']['wallpaper_auto_theme'] is False

# Automatic matching selects a catalog member and keeps glass/layout preferences.
service=controller.wallpaper_theme
with patch.object(service,'refresh'):
    assert entry._dispatch({'action':'theme_auto'});wait()
    before=load_preferences(root)
    assert before['launcher']['wallpaper_auto_theme']
    mode=before['launcher']['wallpaper_theme_mode']

    def matched(name,key):
        source={'key':(key,), 'path':key}
        result={'mode':mode,'revision':service.revision,'key':source['key']+(service._tone(mode),),
                'source':source,'preset':name}
        with patch.object(service,'_source',return_value=source):
            service._ready(result)
        return result

    rose='caelestia-rosepine-moon-dark'
    result=matched(rose,'fixture-rose')
    assert controller.current==rose and service.signature==result['key']
    assert (root/'styles.css').read_text(encoding='utf-8')==compose_styles(root,rose)
    assert dialog._immediate_theme_baseline==(root/'theme.json').read_bytes()
    assert dialog._collect_preferences()==before and not dialog._draft_dirty
    custom=dialog.custom_css.toPlainText()
    dialog.custom_css.setPlainText(custom+'\n/* own pending change */');app.processEvents()
    forest='caelestia-everforest-medium-dark'
    pending=matched(forest,'fixture-forest')
    assert controller.current==rose and service.pending==pending
    assert 'own pending change' in dialog.custom_css.toPlainText()
    dialog.custom_css.setPlainText(custom)
    dialog.custom_css.document().setModified(False)
    dialog._refresh_draft_state()
    wait(400)
    assert not service._blocked()
    matched(forest,'fixture-forest')
    assert controller.current==forest
    assert load_preferences(root)==before,'Automatic colors must preserve opacity, motion, widgets and glass'

dialog.hide();assert entry._dispatch({'action':'wallpaper_directory','path':''})
assert load_preferences(root)['launcher']['wallpaper_directory']==''
dialog.reject();app.processEvents()
assert not errors,errors
controller.border_bridge.close()
print('PASS: fonts/schemas/Settings, 35 presets, wallpaper IPC, automatic matching, preserved glass/preferences and advanced-draft protection.')
temporary.cleanup()
