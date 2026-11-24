"""Deliver keys to actual Qt focus while the Island is still opening."""
from pathlib import Path
import ctypes,importlib.machinery,importlib.util,json,os,sys,traceback
from unittest.mock import patch
stage=Path(sys.argv[1]).resolve();root=stage/'config/dynamic-island'
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path[:0]=[str(root),str(root/'runtime')]
from PySide6.QtCore import QEventLoop,QTimer,Qt
from PySide6.QtGui import QInputMethodEvent,QKeyEvent
from PySide6.QtWidgets import QApplication,QWidget
from launcher_windows import Catalog,Shortcut
loader=importlib.machinery.SourceFileLoader('island',str(root/'island.pyw'));spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);sys.modules['island']=module;loader.exec_module(module)
errors=[]
def error(kind,value,tb):
    detail=''.join(traceback.format_exception(kind,value,tb));errors.append(detail);print(detail,flush=True)
sys.excepthook=error
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
host=QWidget();host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen);host.resize(320,100);host.show()
class Glass:
    hwnd=None;failed=True;wants_compact=False;wants_optical=False;visible=False;mix=0;enabled=False
    def __init__(self,*_):pass
    def configure(self,*_):pass
    def prepare(self):pass
    def sync(self,*_):pass
    def hide(self):pass
    def close(self):pass
def wait(ms):
    loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec()
with patch.object(module,'MaterialLayer',Glass),patch.object(module.Island,'_warm_up'),patch.object(Catalog,'start'),patch.object(Shortcut,'start'):
    island=module.Island(lambda *_:None,lambda:None)
    island.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    # This fixture intentionally has no native foreground window. Isolate
    # logical input timing from the real desktop's unrelated foreground.
    island._launcher_focus_lost=lambda:None
    island.dock.pressed_buttons=lambda:set()
    island.dock.anchor=lambda *_,**__: (app.primaryScreen().availableGeometry().center().x(),60)
    island.catalog.apps=[dict(id=str(i),name=name,target=str(root/'island.pyw')) for i,name in enumerate(('Notepad','File Explorer','Windows Terminal','Settings','Visual Studio Code','Firefox','Calculator'))]
    island.follow_bar();wait(50)
    rows=[]
    # The first letter can arrive before the Alt from Alt+Space is released.
    # Match the modifier/text that Windows delivers, rather than assuming an
    # unmodified character as the previous test did.
    island.launcher_shortcut_alt=True
    island.open_launcher();edit=island.launcher_view.search.edit
    assert edit.width()>400,('Search must be laid out before the first paint/key',edit.width())
    app.sendEvent(app.focusWidget(),QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_N,Qt.KeyboardModifier.AltModifier,'n'))
    assert edit.text()=='n',('Initial shortcut Alt must not eat the first letter',edit.text())
    island.close_launcher(restore=False);wait(500)
    # A first key aimed at the window during a child-focus gap still belongs
    # to search. Esc must work outside the editor at every opening phase.
    island.open_launcher();edit=island.launcher_view.search.edit;edit.clearFocus()
    app.sendEvent(island,QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_N,Qt.KeyboardModifier.NoModifier,'n'))
    assert edit.text()=='n' and edit.hasFocus()
    edit.clearFocus()
    composition=QInputMethodEvent();composition.setCommitString('ệ')
    app.sendEvent(island,composition);assert edit.text()=='nệ'
    island.close_launcher(restore=False);wait(500)
    island.open_launcher();edit=island.launcher_view.search.edit
    app.sendEvent(edit,QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_N,Qt.KeyboardModifier.NoModifier,'n'))
    edit.clearFocus();island._launcher_focus(True)
    assert not edit.hasSelectedText(),'Focus recovery must not select/overwrite the first letter'
    app.sendEvent(edit,QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_O,Qt.KeyboardModifier.NoModifier,'o'))
    assert edit.text()=='no'
    island.close_launcher(restore=False);wait(500)
    for delay in (0,35,130,650):
        island.open_launcher()
        if delay:wait(delay)
        edit.clearFocus()
        app.sendEvent(host,QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_Escape,Qt.KeyboardModifier.NoModifier))
        assert island.launcher_active,'An Esc in another window must not close Island'
        app.sendEvent(island,QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_Escape,Qt.KeyboardModifier.NoModifier))
        assert not island.launcher_active and not island.launcher_hotkey.active
        wait(500);assert not island.launcher_mode
    for attempt in range(3):
        host.activateWindow();wait(10);island.open_launcher()
        for delay,character in [(0,'n'),(1,'o'),(5,'t'),(15,'e'),(30,'p'),(60,'a'),(100,'d')]:
            if delay:wait(delay)
            focused=app.focusWidget()
            before=island.launcher_view.search.edit.text()
            if focused:
                for kind in (QKeyEvent.Type.KeyPress,QKeyEvent.Type.KeyRelease):
                    app.sendEvent(focused,QKeyEvent(kind,ord(character.upper()),Qt.KeyboardModifier.NoModifier,character))
            rows.append(dict(attempt=attempt,delay=delay,animation=island.animation.isActive(),focus=focused.metaObject().className() if focused else None,expected=character,text=island.launcher_view.search.edit.text()))
        wait(650)
        actual=island.launcher_view.search.edit.text()
        print(json.dumps({'attempt':attempt,'actual':actual,'rows':rows[-7:]}),flush=True)
        assert actual=='notepad',actual
        island.close_launcher(restore=False);wait(500)
    # Input methods, editing and dismissal work before the first paint too.
    island.open_launcher();edit=island.launcher_view.search.edit
    assert app.focusWidget() is edit and island.animation.isActive()
    composition=QInputMethodEvent('Ha',[]);app.sendEvent(app.focusWidget(),composition)
    commit=QInputMethodEvent();commit.setCommitString('Hà Nội');app.sendEvent(app.focusWidget(),commit)
    assert edit.text()=='Hà Nội'
    app.sendEvent(app.focusWidget(),QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_Backspace,Qt.KeyboardModifier.NoModifier))
    assert edit.text()=='Hà Nộ'
    app.sendEvent(app.focusWidget(),QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_Escape,Qt.KeyboardModifier.NoModifier))
    wait(500);assert not island.launcher_mode
    # Immediate reopen must not replay old keystrokes or clear newly typed ones
    # when the queued focus retry and animation completion execute.
    island.open_launcher();edit=island.launcher_view.search.edit
    assert edit.text()=='' and app.focusWidget() is edit
    app.sendEvent(app.focusWidget(),QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_2,Qt.KeyboardModifier.NoModifier,'2'))
    wait(700);assert edit.text()=='2' and app.focusWidget() is edit,(edit.text(),str(app.focusWidget()),island.launcher_active,island.launcher_mode,edit.isVisible(),island.isVisible())
    island.close_launcher(restore=False);wait(500)
    island.hide();island.deleteLater();app.processEvents()
assert not errors,errors

print('Search geometry before first paint, root/IME input routing, Esc at four phases and ownership boundaries, typing from 0ms, Vietnamese IME and reopen passed.')
