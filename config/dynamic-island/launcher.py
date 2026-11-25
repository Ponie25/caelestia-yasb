"""Launcher state in the existing Island window; collapsed clicks stay menus."""
import ctypes
import json
import hashlib
import logging
import os
from pathlib import Path
import subprocess
import time

from PySide6.QtCore import QPointF,QTimer,Qt,QUrl
from PySide6.QtGui import QColor,QDesktopServices,QPainterPath,QPen
from PySide6.QtWidgets import QApplication,QFileDialog
from launcher_core import Result,query,DANGEROUS
from launcher_actions import BackgroundAction,ControlRequest,power_action
from launcher_wallpapers import Wallpapers,apply_wallpaper
from launcher_view import LauncherView,WIDTH,curve
from launcher_windows import Catalog,Shortcut
import launcher_focus
import palette


class LauncherMixin:
    def _launcher_init(self,root):
        self.launcher_active=False;self.launcher_mode=False;self.launcher_jolt=False;self.launcher_previous=None;self.launcher_after_close=None
        self.launcher_phase=(0.,0.);self.launcher_phase_origin=(1.,1.);self.launcher_origin_image=None
        self.wallpapers=Wallpapers(root);self.wallpapers.changed.connect(self._launcher_wallpapers_changed)
        self.launcher_confirmation=None;self.launcher_sequence=0;self.launcher_last_error='';self.launcher_palettes={};self.launcher_busy=False
        for name in ('light','dark','catppuccin','everforest','red-white','red-black','wallpaper'):
            try:
                data=json.loads((Path(root).parent/'theme-profiles'/name/'palette.json').read_text(encoding='utf-8'))
                self.launcher_palettes[name]=(data['BASE'],data['MAUVE'])
            except (OSError,ValueError,KeyError):pass
        self.catalog=Catalog(root);self.launcher_view=LauncherView(self,self.catalog)
        self.catalog.changed.connect(self._launcher_catalog)
        self.launcher_view.query_changed.connect(self._launcher_query)
        self.launcher_view.accepted.connect(self._launcher_accept)
        self.launcher_view.dismissed.connect(self.close_launcher)
        self.launcher_view.favorite_filter_changed.connect(self._launcher_filter_wallpapers)
        self.launcher_view.wallpaper_refresh_requested.connect(self._launcher_refresh_wallpapers)
        self.launcher_view.height_changed.connect(self._launcher_height)
        self.launcher_hotkey=Shortcut(int(self.winId()))
        self.launcher_hotkey.status.connect(lambda message:logging.warning(message))
        QApplication.instance().aboutToQuit.connect(self.catalog.stop)
        QApplication.instance().aboutToQuit.connect(self.wallpapers.stop)
        QApplication.instance().aboutToQuit.connect(self.launcher_hotkey.stop)
        self.catalog.start()
        self._launcher_apply(getattr(self,'launcher_options',{}))
    def _launcher_apply(self,options):
        self.launcher_options={'enabled':True,'hotkey':True,'max_results':7,'dangerous_actions':False,'wallpaper_directory':'','wallpaper_favorites_only':True,'wallpaper_auto_theme':True,'wallpaper_theme_mode':'current'}
        if isinstance(options,dict):self.launcher_options.update(options)
        self.wallpapers.configure(self.launcher_options.get('wallpaper_directory',''))
        from motion_spec import profile,milliseconds
        self.launcher_view.results.motion_ms=milliseconds(profile(self.catalog.root.parent),'menu')
        if not hasattr(self,'launcher_hotkey'):return
        if self.launcher_options.get('enabled',True) and self.launcher_options.get('hotkey',True):self.launcher_hotkey.start()
        else:self.launcher_hotkey.stop()
        if not self.launcher_options.get('enabled',True) and self.launcher_active:self.close_launcher()
        if self.launcher_active:
            self.launcher_view.max_rows=self._launcher_max_rows();self._launcher_height();self.launcher_view.layout_contents();self._retarget()
    def _launcher_max_rows(self):
        screen=self.screen() or QApplication.primaryScreen()
        count=self.launcher_options.get('max_results',7)
        count=count if type(count) is int and 3<=count<=7 else 7
        return max(2,min(count,(screen.availableGeometry().height()-120)//65))
    def _launcher_catalog(self,apps):
        self.catalog.accept(apps)
        if self.launcher_active:self._launcher_query(self.launcher_view.search.edit.text(),preserve=True)
    def _launcher_query(self,text,preserve=False):
        if palette.THEME=='wallpaper':self.launcher_palettes['wallpaper']=(palette.BASE,palette.MAUVE)
        self.launcher_sequence+=1;self.launcher_confirmation=None
        command=text.strip().split(' ',1)[0].casefold()
        if command in ('>wallpaper','>wallpapers','>background','>random'):self.wallpapers.ensure()
        favorite=self.launcher_options.get('wallpaper_favorites_only',True)
        self.launcher_view.set_wallpaper_mode(command in ('>wallpaper','>wallpapers','>background'),favorite,self.wallpapers.favorite_error)
        context=dict(theme=palette.THEME,palettes=self.launcher_palettes,wallpapers=self.wallpapers.visible_items(favorite),wallpaper_favorites_only=favorite,wallpaper_error=self.wallpapers.favorite_error,
                     wallpaper_loading=self.wallpapers.loading,wallpaper=self.wallpapers.current,
                     dangerous_actions=self.launcher_options.get('dangerous_actions') is True)
        rows=query(text,self.catalog.apps,self.catalog.history,context)
        if self.launcher_last_error and not text:rows=[Result('last-error',self.launcher_last_error,'Lệnh trước chưa hoàn tất · gõ để tiếp tục','hint')]+rows[:6]
        elif text:self.launcher_last_error=''
        if not rows:rows=[Result('index','Đang lập danh sách ứng dụng…' if not self.catalog.apps else 'Không có kết quả','Gõ > để xem các lệnh nhanh','hint')]
        self.launcher_view.set_results(rows,preserve)
    def _launcher_wallpapers_changed(self):
        if self.launcher_active and self.launcher_view.search.edit.text().strip().split(' ',1)[0].casefold() in ('>wallpaper','>wallpapers','>background','>random'):
            self._launcher_query(self.launcher_view.search.edit.text(),preserve=True)
    def _launcher_filter_wallpapers(self,favorite):
        self.launcher_options['wallpaper_favorites_only']=favorite
        self._launcher_query(self.launcher_view.search.edit.text(),preserve=True)
        self._launcher_control(dict(action='wallpaper_options',options={'wallpaper_favorites_only':favorite}),after=lambda:None)
    def _launcher_refresh_wallpapers(self):
        self.wallpapers.ensure(force=True);edit=self.launcher_view.search.edit
        if edit.text()=='>wallpaper ':self._launcher_query(edit.text(),preserve=True)
        else:edit.setText('>wallpaper ')
    def _launcher_height(self):
        if self.launcher_active:
            required=max(self.HEIGHT,self.launcher_view.preferred_height()+48)
            if self.height()<required:self.setFixedHeight(required);self.follow_bar()
            if abs(self.target[1]-self.launcher_view.preferred_height())<.01:return
            self.launcher_phase_origin=self.launcher_phase
            self.launcher_jolt=False
            self._retarget()
    def toggle_launcher(self):
        if self.launcher_active:self.close_launcher()
        else:self.open_launcher()
    def open_launcher(self):
        if not self.launcher_options.get('enabled',True):return
        if self.launcher_active:
            self._launcher_focus(True);return
        self.launcher_origin_image=self._launcher_snapshot()
        self.launcher_after_close=None
        user=ctypes.windll.user32;user.GetForegroundWindow.restype=ctypes.c_void_p
        previous=user.GetForegroundWindow();self.launcher_previous=previous if previous!=int(self.winId()) else None
        if self.expanded:self._set_expanded(False)
        self.hovered=False;self.launcher_mode=True
        self.launcher_view.max_rows=self._launcher_max_rows()
        self.launcher_view.search.edit.clear()
        self._launcher_query('')
        self.launcher_active=True;self.launcher_jolt=True;self.launcher_phase=(0.,0.)
        self.launcher_hotkey.active=True
        self.setFixedHeight(max(self.HEIGHT,self.launcher_view.preferred_height()+48))
        # Input geometry must exist before focus, not wait for paintEvent.
        self._launcher_layout()
        self.launcher_view.effects(True,0);self.launcher_view.show()
        self.buttons=self.dock.pressed_buttons();self.outside_click.start()
        self.follow_bar();focused=self._launcher_focus(True);self._retarget()
        if not focused:QTimer.singleShot(0,self._launcher_retry_focus)
        if os.environ.get('YASB_SETTINGS_NO_EXTERNAL')!='1':QTimer.singleShot(0,self.wallpapers.ensure)
        logging.info('Island launcher opened')
    def _launcher_retry_focus(self):
        if (self.launcher_active and launcher_focus.foreground()==int(self.winId())
                and not self.launcher_view.search.edit.hasFocus()):self._launcher_focus(True)
    def _launcher_focus(self,enabled):
        # Update QWidget's flags too: changing QWindow alone leaves Qt's native
        # WS_EX_NOACTIVATE flag behind. Windows reuses the same HWND here.
        visible=self.isVisible();position=self.pos();self.launcher_switching_focus=True
        try:
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus,not enabled)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating,not enabled)
            if visible:self.show();self.move(position)
        finally:self.launcher_switching_focus=False
        handle=self.windowHandle()
        if enabled:
            self.raise_();self.activateWindow()
            if handle is not None:handle.requestActivate()
            hwnd=int(self.winId())
            confirmed=launcher_focus.activate(hwnd)
            # Native activation and Qt's activation notification are separate.
            # Establish Qt's requested input target synchronously, including
            # when Windows has not acknowledged activation yet. The ordinary
            # deactivation handler still closes on a real external focus loss.
            QApplication.setActiveWindow(self)
            # Recovery must preserve a query already typed during the morph.
            self.launcher_view.search.edit.setFocus(Qt.FocusReason.OtherFocusReason)
            return confirmed and self.launcher_view.search.edit.hasFocus()
    def _launcher_focus_lost(self):
        if not self.launcher_active or QApplication.activePopupWidget() is not None:return
        user=ctypes.windll.user32;user.GetForegroundWindow.restype=ctypes.c_void_p
        foreground=user.GetForegroundWindow()
        if not foreground or foreground==int(self.winId()):return
        process=ctypes.c_uint32();user.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
        user.GetWindowThreadProcessId(foreground,ctypes.byref(process))
        if process.value!=os.getpid():self.close_launcher(restore=False)
    def close_launcher(self,restore=True,after=None):
        if not self.launcher_active:return
        self.launcher_active=False;self.launcher_jolt=False;self.launcher_after_close=after
        self.launcher_confirmation=None
        self.launcher_hotkey.active=False
        self.launcher_view.effects(True,1)
        self.launcher_view.search.edit.clearFocus()
        self.outside_click.stop();self.buttons.clear()
        self._launcher_focus(False)
        if restore and self.launcher_previous:
            user=ctypes.windll.user32;user.IsWindow.argtypes=[ctypes.c_void_p];user.SetForegroundWindow.argtypes=[ctypes.c_void_p]
            if user.IsWindow(self.launcher_previous):user.SetForegroundWindow(self.launcher_previous)
        self.launcher_previous=None;self._retarget();logging.info('Island launcher closed')
    def _launcher_finished(self):
        if self.launcher_active:
            # Drop the intermediate opacity backing store after the morph.
            # Native text editing must repaint the whole search surface cleanly.
            self.launcher_phase=(1.,1.);self.launcher_view.effects(False,1);self.launcher_view.clearMask()
            self.launcher_view.search.update();self.launcher_view.results.viewport().update()
        if not self.launcher_active and self.launcher_mode:
            self.launcher_mode=False;self.launcher_view.hide();self.launcher_view.clearMask()
            self.launcher_origin_image=None
            after,self.launcher_after_close=self.launcher_after_close,None
            if after:QTimer.singleShot(0,after)
        self.launcher_jolt=False
    def _launcher_step(self,elapsed):
        clamp=lambda x:max(0.,min(1.,x))
        spatial=curve('spatial')
        if self.launcher_jolt or not self.launcher_active:
            closed,opened=(self.origin,self.target) if self.launcher_active else (self.target,self.origin)
            t=elapsed if self.launcher_active else 1-elapsed
            if self.launcher_active and t<.08:
                import math
                amount=math.sin(t/.08*math.pi/2)
                self.launcher_phase=(0.,0.)
                return (closed[0]*(1-.02*amount),max(26,closed[1]-.7*amount),closed[2],closed[3],0.)
            width_t=clamp((t-.08)/.62);body_t=clamp((t-.34)/.66)
            header=spatial.valueForProgress(width_t*width_t)
            body=spatial.valueForProgress(body_t*body_t)
            self.launcher_phase=(clamp(header),clamp(body))
            # One continuous surface: first a search capsule, then its body.
            start_width=closed[0]*(.98 if self.launcher_active else 1.)
            width=start_width+(opened[0]-start_width)*header
            start_height=closed[1]-(.7 if self.launcher_active else 0.)
            if closed[1]<80:height=start_height+(56-start_height)*clamp(header)+(opened[1]-56)*body
            else:height=start_height+(opened[1]-start_height)*spatial.valueForProgress(clamp((t-.08)/.92)**2)
            progress=clamp(.4*header+.6*body)
            return (width,height,closed[2]*(1-clamp(header)),progress,0.)
        easing=spatial.valueForProgress(clamp(elapsed))
        self.launcher_phase=tuple(clamp(a+(1-a)*easing) for a in self.launcher_phase_origin)
        return tuple(a+(b-a)*easing for a,b in zip(self.origin,self.target))
    def _launcher_radius(self,height):
        return min(28-9*self.launcher_phase[1],height/2)
    def _launcher_layout(self):
        _,body=self.launcher_phase
        # The original puts search next to its bar. Mirror only for a top bar.
        height=self.launcher_view.preferred_height()
        top=self.height()-height-4 if self.dock.bottom else 0
        self.launcher_view.bottom=self.dock.bottom
        self.launcher_view.morph_margin=16*body
        self.launcher_view.setGeometry((self.WIDTH-WIDTH)//2,top,WIDTH,height)
        self.launcher_view.layout_contents()
    def _launcher_paint(self,painter,surface):
        header,body=self.launcher_phase
        self._launcher_layout()
        search_alpha=max(0.,min(1.,(header-.6)/.4))
        body_alpha=max(0.,min(1.,(body-.08)/.72))
        self.launcher_view.reveal(search_alpha,body_alpha,surface)
        if search_alpha<1 and self.launcher_origin_image is not None:
            painter.save();painter.setClipPath(surface);painter.setOpacity(1-search_alpha)
            image=self.launcher_origin_image
            y=self.height()-image.height()/image.devicePixelRatio() if self.dock.bottom else 0
            painter.drawImage(QPointF(0,y),image);painter.restore()
    def _launcher_error(self,message):
        self.launcher_view.set_results([Result('error',message,'Hãy thử tìm lại hoặc chọn một mục khác','hint','', 'search')])
    def _launcher_accept(self,result):
        try:
            if self.launcher_busy and result.kind in ('theme','power','power_confirm','wallpaper','random','wallpaper_folder'):return
            if self._launcher_command_result(result):return
            if result.kind=='complete':
                self.launcher_view.search.edit.setText(result.value);self.launcher_view.search.edit.setFocus();return
            if result.kind=='hint':return
            if result.kind=='copy':QApplication.clipboard().setText(result.value)
            elif result.kind=='app':
                if result.value.startswith('shell:AppsFolder\\'):
                    subprocess.Popen([str(Path(os.environ.get('WINDIR',r'C:\Windows'))/'explorer.exe'),result.value])
                else:
                    if not Path(result.value).is_file():raise OSError('Ứng dụng không còn ở vị trí cũ')
                    os.startfile(result.value)
                self.catalog.remember(result)
            elif result.kind=='url':
                if not QDesktopServices.openUrl(QUrl(result.value)):raise OSError('Không mở được trình duyệt')
            elif result.kind=='action':
                if result.value in ('island','timer'):
                    tab='Live Activity' if result.value=='timer' else 'Dashboard'
                    def menu():
                        self._set_expanded(True);self.dashboard.tab=tab;self.drawer_frame=None;self.update()
                    self.close_launcher(restore=False,after=menu);return
                if result.value in ('bar','launcher-settings'):
                    self._launcher_control(dict(action='open',page=4 if result.value=='launcher-settings' else None));return
                elif result.value=='settings':os.startfile('ms-settings:')
                elif result.value in ('downloads','documents'):
                    # Resolve redirected Known Folders rather than assuming C:\Users.
                    from launcher_windows import known_folder
                    os.startfile(str(known_folder(result.value)))
                else:return
            else:return
            self.close_launcher(restore=False)
        except (OSError,ValueError,RuntimeError):
            logging.warning('Launcher action failed',exc_info=True)
            self._launcher_error('Chưa mở được mục này')

    def _launcher_control(self,payload,after=None):
        root=self.catalog.root.parent;key=hashlib.sha256(os.fsencode(os.path.normcase(str(root.resolve())))).hexdigest()[:20]
        sequence=self.launcher_sequence;request=ControlRequest(self);self.launcher_busy=True
        def finished(ok,message):
            self.launcher_busy=False
            if ok:
                if after:after()
                elif self.launcher_active and sequence==self.launcher_sequence:self.close_launcher(restore=False)
            elif self.launcher_active and sequence==self.launcher_sequence:self._launcher_error(message)
            else:self.launcher_last_error=message
        request.finished.connect(finished);request.start('yasb-settings-'+key,payload)

    def _launcher_background(self,function,after=None,session=False):
        sequence=self.launcher_sequence;job=BackgroundAction(self,function);self.launcher_busy=True
        def finished(ok,message):
            self.launcher_busy=False
            if ok:
                if after:after()
                if not session and self.launcher_active and sequence==self.launcher_sequence:self.close_launcher(restore=False)
            elif self.launcher_active and sequence==self.launcher_sequence:self._launcher_error(message)
            else:self.launcher_last_error=message
            job.deleteLater()
        job.finished.connect(finished);job.start()

    def _launcher_command_result(self,result):
        if result.kind=='theme':
            if result.value not in self.launcher_palettes:raise ValueError('Bảng màu không hợp lệ.')
            self._launcher_control(dict(action='theme',name=result.value));return True
        if result.kind in ('power','power_confirm','power_cancel'):
            if result.kind=='power_cancel':self._launcher_query(self.launcher_view.search.edit.text());return True
            action=result.value
            if action not in ('lock','sleep',*DANGEROUS):raise ValueError('Lệnh nguồn không hợp lệ.')
            if action in DANGEROUS and self.launcher_options.get('dangerous_actions') is not True:
                self._launcher_query('>'+action);return True
            if action=='lock':
                self.close_launcher(restore=False,after=lambda:self._launcher_background(lambda:power_action(action),session=True));return True
            if result.kind=='power_confirm':
                if self.launcher_confirmation!=action:return True
                self.close_launcher(restore=False,after=lambda:self._launcher_background(lambda:power_action(action),session=True));return True
            self.launcher_confirmation=action
            labels={'sleep':'Ngủ','shutdown':'Tắt máy','reboot':'Khởi động lại','logout':'Đăng xuất'}
            self.launcher_view.set_results([Result('power-cancel','Hủy','Quay lại danh sách lệnh · Esc đóng launcher','power_cancel','','x'),
                Result('power-confirm',labels[action]+' ngay','Lưu công việc đang mở trước khi tiếp tục','power_confirm',action,result.glyph)])
            return True
        if result.kind=='wallpaper_folder':
            self.close_launcher(restore=False,after=self._launcher_choose_wallpaper_folder);return True
        if result.kind=='wallpaper_refresh':
            self._launcher_refresh_wallpapers();return True
        if result.kind=='wallpaper_filter':
            self.launcher_view.search.edit.setText('>wallpaper ');self._launcher_filter_wallpapers(result.value=='favorites');return True
        if result.kind in ('wallpaper','random'):
            item=self.wallpapers.random(self.launcher_options.get('wallpaper_favorites_only',True)) if result.kind=='random' else self.wallpapers.get(result.value)
            if item is None:raise OSError('Chưa có hình nền để chọn.')
            def applied():
                self.wallpapers.remember(item['path'],item)
                if self.launcher_options.get('wallpaper_auto_theme',True):self._launcher_control(dict(action='wallpaper_changed'),after=lambda:None)
            self._launcher_background(lambda:apply_wallpaper(item,self.wallpapers.engine),after=applied);return True
        return False

    def _launcher_choose_wallpaper_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Chọn thư mục hình nền',str(self.wallpapers.directory))
        def reopen():
            self.open_launcher();self.launcher_view.search.edit.setText('>wallpaper ')
        if not folder:reopen();return
        def selected():
            self.wallpapers.configure(folder);self.wallpapers.ensure(force=True);reopen()
        self._launcher_control(dict(action='wallpaper_directory',path=folder),after=selected)
