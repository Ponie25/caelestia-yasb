"""Smoke-test an isolated prepared Windows install without changing saved settings.

Usage: <install>\python\python.exe tools\check_install.py <install>
"""
from importlib.machinery import EXTENSION_SUFFIXES, PathFinder
from importlib.util import spec_from_file_location
from pathlib import Path
import importlib,json,os,shutil,sys,tempfile,traceback

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
from PyQt6.QtWidgets import QApplication
from core.utils.bar_preferences import validate_config,load_preferences
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
dialog._motion_preset(165);wait()
assert load_preferences(root)['animations']['popup_ms']==165 and load_preferences(root)['island']['speed']==1.
dialog._motion_preset(220);wait()
assert dialog.motion_presets[220].isChecked()
dialog.resize(680,620);wait();assert dialog.nav.property('compact')
for name in controller.theme_labels:
    dialog._choose_theme(name);wait()
    assert controller.current==name and dialog.theme_buttons[name].isChecked()
dialog.reject();app.processEvents()
assert not errors,errors
controller.border_bridge.close()
print('PASS: configured font, every widget schema, native Settings, preference round-trip, search, shared motion, compact navigation and all six themes.')
temporary.cleanup()
