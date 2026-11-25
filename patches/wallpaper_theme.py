"""Pick and copy a curated preset; never generate a palette from wallpaper pixels."""
import ctypes,importlib.util,json,logging,os,threading,time
from pathlib import Path
from PyQt6.QtCore import QObject,QSize,Qt,pyqtSignal
from PyQt6.QtGui import QImageReader
from core.utils.bar_preferences import atomic_write,create_snapshot,load_preferences
from core.utils.theme_tokens import is_light,normalize_palette,effective_palette

class WallpaperTheme(QObject):
    ready=pyqtSignal(object)
    def __init__(self,controller):
        super().__init__(controller);self.controller=controller;self.root=controller.root;self.busy=False;self.signature=None;self.pending=None;self.snapshot=False
        self.engine=None;self.engine_checked=0;self.force_pending=False
        spec=importlib.util.spec_from_file_location('caelestia_wallpaper_data',self.root/'dynamic-island/wallpaper_data.py')
        self.data=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.data);self.ready.connect(self._ready)
        self.catalog=self.data.load_presets(self.root);self.presets={entry['id']:entry for entry in self.catalog};self.selected_preset=None
        try:self.selected_preset=json.loads((self.root/'dynamic-island/wallpaper-theme-state.json').read_text(encoding='utf-8')).get('preset')
        except (OSError,ValueError,AttributeError):pass
    def refresh(self,force=False):
        if os.environ.get('YASB_SETTINGS_NO_EXTERNAL')=='1':return
        options=load_preferences(self.root)['launcher']
        if not options['wallpaper_auto_theme']:self.pending=None;return
        if self.pending is not None and not self._blocked():
            if self.pending.get('mode')==options['wallpaper_theme_mode']:self._apply(self.pending)
            self.pending=None
        if self.busy:self.force_pending|=force;return
        self.busy=True;mode=options['wallpaper_theme_mode'];dark=not is_light(effective_palette(self.root,self.controller.current)) if mode=='current' else mode=='dark'
        def work():
            try:
                source=self._source();path=Path(source) if source else None
                signature=(str(path),path.stat().st_mtime_ns,dark) if path and path.is_file() else None
                result={'mode':mode,'signature':signature}
                if signature and (force or signature!=self.signature):
                    reader=QImageReader(str(path));reader.setAutoTransform(True);size=reader.size()
                    if not size.isValid() or size.width()*size.height()>24_000_000:raise ValueError('Không đọc được ảnh xem trước của hình nền.')
                    reader.setScaledSize(size.scaled(QSize(64,64),Qt.AspectRatioMode.KeepAspectRatio));image=reader.read();del reader
                    if image.isNull():raise ValueError('Không đọc được màu hình nền.')
                    pixels=[image.pixelColor(x,y).getRgb()[:3] for y in range(image.height()) for x in range(image.width()) if image.pixelColor(x,y).alpha()>127]
                    seed=self.data.dominant(pixels);result.update(preset=self.data.choose_preset(seed,dark,self.catalog)['id'],seed=seed)
                self._emit(result)
            except Exception:
                logging.debug('Wallpaper color update unavailable',exc_info=True);self._emit({})
        threading.Thread(target=work,daemon=True,name='wallpaper-theme').start()
    def _emit(self,result):
        try:self.ready.emit(result)
        except RuntimeError:pass
    def _source(self):
        import psutil
        if self.engine is not None:
            try:
                if not self.engine.is_running():self.engine=None;self.engine_checked=0
            except psutil.Error:self.engine=None;self.engine_checked=0
        if self.engine is None and time.monotonic()-self.engine_checked>30:
            self.engine_checked=time.monotonic()
            for process in psutil.process_iter(['name','exe']):
                if (process.info.get('name') or '').lower() in ('wallpaper64.exe','wallpaper32.exe'):
                    self.engine=process;break
        metadata={}
        if self.engine is not None:
            try:metadata=self.data.engine_metadata(self.engine.exe())
            except (OSError,psutil.Error):pass
        try:state=json.loads((self.root/'dynamic-island/wallpaper-state.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):state={}
        if isinstance(state,dict) and state.get('preview'):
            updated=state.get('updated',0);recent=type(updated) in (int,float) and 0<=time.time()-updated<15
            static=not state.get('engine') and state.get('previous_engine_project')==metadata.get('current')
            if (recent or static) and Path(state['preview']).is_file():return state['preview']
        if metadata.get('preview'):return metadata['preview']
        buffer=ctypes.create_unicode_buffer(32768)
        return buffer.value if ctypes.windll.user32.SystemParametersInfoW(0x73,len(buffer),buffer,0) else ''
    def _ready(self,result):
        self.busy=False
        options=load_preferences(self.root)['launcher']
        if result.get('preset') in self.presets and options['wallpaper_auto_theme'] and result.get('mode')==options['wallpaper_theme_mode']:
            if self._blocked():self.pending=result
            else:self.pending=None;self._apply(result)
        if self.force_pending:self.force_pending=False;self.refresh(force=True)
    def _blocked(self):
        dialog=self.controller.settings_dialog
        try:return dialog is not None and dialog.isVisible() and (dialog._immediate_pending or dialog._immediate_busy or dialog._committing or dialog._advanced_preferences_pending or dialog._draft_signature()!=dialog._draft_saved_signature or dialog._disk_state()!=dialog._disk_baseline)
        except (ValueError,RuntimeError,TypeError):return True
    def _apply(self,result):
        profile=self.root/'theme-profiles/wallpaper';previous={};previous_theme=self.controller.current;state=self.root/'dynamic-island/wallpaper-theme-state.json';previous_state=state.read_bytes() if state.exists() else None
        try:
            previous={name:(profile/name).read_bytes() if (profile/name).exists() else None for name in ('palette.json','styles.css')}
            entry=self.presets[result['preset']];source=self.root/'wallpaper-presets'/entry['id'];palette_bytes=(source/'palette.json').read_bytes();style_bytes=(source/'styles.css').read_bytes();palette=json.loads(palette_bytes)
            if normalize_palette(palette)!=palette or not style_bytes:raise ValueError('Preset chưa qua kiểm tra độ tương phản.')
            if not self.snapshot:create_snapshot(self.root,'Trước khi tự chọn preset cho wallpaper');self.snapshot=True
            atomic_write(profile/'palette.json',palette_bytes);atomic_write(profile/'styles.css',style_bytes)
            atomic_write(state,json.dumps({'path':result['signature'][0],'seed':result['seed'],'preset':entry['id'],'name':entry['name']},ensure_ascii=False)+'\n')
            if not self.controller.select('wallpaper'):raise RuntimeError('Không áp dụng được preset đã chọn.')
            self.signature=result['signature'];self.selected_preset=entry['id']
            dialog=self.controller.settings_dialog
            if dialog is not None and dialog.isVisible():
                button=dialog.theme_buttons['wallpaper'];button._palette=palette;button.update()
                dialog._immediate_rebase_preferences(load_preferences(self.root),'wallpaper');dialog._mark_saved();dialog._refresh_preview();dialog._refresh_curated_status()
            logging.info('Wallpaper preset selected: %s (seed=%s)',entry['id'],result['seed'])
        except Exception:
            for name,value in previous.items():
                if value is not None:atomic_write(profile/name,value)
            if previous_state is not None:atomic_write(state,previous_state)
            else:state.unlink(missing_ok=True)
            if self.controller.current!=previous_theme:self.controller.select(previous_theme)
            logging.warning('Could not select wallpaper preset',exc_info=True)
