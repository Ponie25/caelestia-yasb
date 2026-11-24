"""Event-driven border color synchronization; never reload Komorebi config."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess

from PyQt6.QtCore import QObject,QTimer,pyqtSignal,Qt,QFileSystemWatcher
from core.utils.theme_tokens import channels,effective_palette
from core.utils.bar_preferences import atomic_write,load_preferences

KINDS=('single','stack','monocle','floating','unfocused','unfocused-locked')
ROLES={'single':'MAUVE','stack':'PINK','monocle':'MAUVE','floating':'PINK','unfocused':'SURFACE2','unfocused-locked':'LAVENDER'}


def colors_for(preferences,palette):
    options=preferences['komorebi'];mode=options['mode']
    if mode in ('off','original'):return None
    return {kind:options[kind.replace('-','_')+'_color'] if mode=='custom' else palette[ROLES[kind]] for kind in KINDS}


class KomorebiThemeBridge(QObject):
    finished=pyqtSignal(object)
    connected=pyqtSignal(dict)
    updated=pyqtSignal(dict,dict)
    status_changed=pyqtSignal(str)

    def __init__(self,controller):
        super().__init__(controller)
        self.controller=controller;self.root=controller.root
        self.status='Chưa đồng bộ.';self.generation=0;self.busy=False;self.closed=False;self.last_colors=None
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='bar-border-theme')
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(160);self.timer.timeout.connect(self._submit)
        self.finished.connect(self._completed,Qt.ConnectionType.QueuedConnection)
        self.external=os.environ.get('YASB_SETTINGS_NO_EXTERNAL')!='1'
        if self.external:
            from core.events.service import EventService
            from core.events.komorebi import KomorebiEvent
            self.events=EventService();self.connect_event=KomorebiEvent.KomorebiConnect;self.update_event=KomorebiEvent.KomorebiUpdate
            self.events.register_event(self.connect_event,self.connected);self.events.register_event(self.update_event,self.updated)
            self.connected.connect(lambda state:self.request(650))
            self.updated.connect(self._on_update)
            config=Path.home()/'komorebi.json'
            self.watcher=QFileSystemWatcher(self);self.watcher.addPath(str(config.parent))
            if config.exists():self.watcher.addPath(str(config))
            self.config_path=config;self.config_stamp=None
            self.watcher.fileChanged.connect(self._configuration_changed)
            self.watcher.directoryChanged.connect(self._configuration_changed)
            from PyQt6.QtWidgets import QApplication
            QApplication.instance().aboutToQuit.connect(self.close)

    def _configuration_changed(self,*_):
        try:stamp=(self.config_path.stat().st_mtime_ns,self.config_path.stat().st_size)
        except OSError:return
        if str(self.config_path) not in self.watcher.files():self.watcher.addPath(str(self.config_path))
        if stamp!=self.config_stamp:self.config_stamp=stamp;self.request(650)

    def _on_update(self,event,state):
        if event.get('type') in ('Theme','ReplaceConfiguration','ReloadConfiguration','ReloadStaticConfiguration'):self.request(650)

    def request(self,delay=160):
        self.generation+=1
        if not self.external or self.closed:return
        self.timer.start(delay)

    def _set_status(self,text):self.status=text;self.status_changed.emit(text)

    def _cli(self):
        try:
            directory=Path(json.loads((self.root/'komorebi-runtime.json').read_text(encoding='utf-8'))['directory'])
            candidate=directory/'komorebic.exe'
            if candidate.is_file():return str(candidate)
        except (OSError,ValueError,KeyError,TypeError):pass
        return shutil.which('komorebic.exe') or 'komorebic.exe'

    def _submit(self):
        if self.closed:return
        if self.busy:self.timer.start(100);return
        options=load_preferences(self.root)
        if options['komorebi']['mode']=='off':self._set_status('Không đồng bộ; giữ màu Komorebi hiện tại.');return
        palette=effective_palette(self.root,self.controller.current)
        wanted=colors_for(options,palette)
        mode=options['komorebi']['mode'];generation=self.generation
        self.busy=True;self._set_status('Đang cập nhật màu viền…')
        future=self.pool.submit(self._apply,self._cli(),mode,wanted,generation)
        def completed(result):
            try:value=result.result()
            except Exception as error:value={'generation':generation,'error':str(error)}
            if not self.closed:self.finished.emit(value)
        future.add_done_callback(completed)

    def _apply(self,cli,mode,wanted,generation):
        def command(args):
            result=subprocess.run([cli,*args],capture_output=True,timeout=2,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise OSError(result.stderr.decode('utf-8',errors='replace')[:250] or 'Komorebi chưa sẵn sàng.')
            return result.stdout
        state=json.loads(command(['global-state']))
        actual={}
        for kind in KINDS:
            rgb=state['border_colours'][kind.replace('-','_')]
            actual[kind]='#'+''.join(f'{rgb[c]:02x}' for c in ('r','g','b'))
        original=self.root/'komorebi-original-colors.json'
        if not original.exists():atomic_write(original,json.dumps(actual,indent=2)+'\n')
        if mode=='original':
            wanted=json.loads(original.read_text(encoding='utf-8'))
            if set(wanted)!=set(KINDS) or any(not isinstance(v,str) or len(v)!=7 for v in wanted.values()):raise ValueError('Bản màu Komorebi ban đầu không hợp lệ.')
        for kind,color in wanted.items():
            if generation!=self.generation or self.closed:return {'generation':generation,'superseded':True}
            if actual.get(kind)!=color.lower():command(['border-colour','--window-kind',kind,*map(str,channels(color))])
        return {'generation':generation,'colors':wanted,'mode':mode}

    def _completed(self,result):
        self.busy=False
        if self.closed:return
        if result['generation']!=self.generation:self.timer.start(0);return
        if 'error' in result:
            self._set_status('Chưa đồng bộ: '+result['error'][:200]);logging.warning('Border synchronization: %s',result['error']);return
        self.last_colors=result.get('colors')
        self._set_status('Đã khôi phục màu ban đầu.' if result.get('mode')=='original' else 'Đã đồng bộ màu viền với cấu hình đã lưu.')

    def close(self):
        if self.closed:return
        self.closed=True;self.generation+=1;self.timer.stop()
        if hasattr(self,'events'):
            self.events.unregister_event(self.connect_event,self.connected);self.events.unregister_event(self.update_event,self.updated)
        self.pool.shutdown(wait=False,cancel_futures=True)
