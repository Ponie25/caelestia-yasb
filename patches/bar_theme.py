"""Local bar themes, independent of the Windows app theme."""
import hashlib
import json
import logging
import os
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QSaveFile, QIODevice, QTimer, Qt
from PyQt6.QtGui import QActionGroup
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QApplication, QMenu

from core.utils.win32.utils import apply_qmenu_style

THEMES = {'light': 'Sáng', 'dark': 'Tối', 'catppuccin': 'Tím hồng', 'everforest': 'Xanh lá', 'red-white': 'Đỏ trắng', 'red-black': 'Đỏ đen','wallpaper':'Tự chọn preset'}


class BarThemeController(QObject):
    def __init__(self, manager, root=None):
        super().__init__(manager)
        from settings import DEFAULT_CONFIG_DIRECTORY
        self.manager = manager
        self.root = Path(root or DEFAULT_CONFIG_DIRECTORY)
        self.current = 'catppuccin'
        self.menu = None
        self.settings_dialog = None
        self._settings_serial = 0
        self.theme_labels = dict(THEMES)
        try:
            selected = json.loads((self.root / 'theme.json').read_text(encoding='utf-8'))['name']
            if selected in THEMES:
                self.current = selected
        except (OSError, ValueError, KeyError, TypeError):
            pass
        QApplication.instance()._bar_theme_controller = self
        from core.utils.komorebi_theme import KomorebiThemeBridge
        self.border_bridge=KomorebiThemeBridge(self)
        QTimer.singleShot(750,self._apply_integrations)
        QTimer.singleShot(0, self._sync_calendar_colors)
        QTimer.singleShot(350, self._reopen_settings)
        from core.utils.settings_entry import SettingsEntry
        self.settings_entry=SettingsEntry(self)
        self._wallpaper_signature=None
        from core.utils.wallpaper_theme import WallpaperTheme
        self.wallpaper_theme=WallpaperTheme(self)
        self.wallpaper_poll=QTimer(self);self.wallpaper_poll.setInterval(3000)
        self.wallpaper_poll.timeout.connect(self._refresh_wallpaper_contrast);self.wallpaper_poll.start()
        QTimer.singleShot(0,self._refresh_wallpaper_contrast)

    def _refresh_wallpaper_contrast(self):
        self.wallpaper_theme.refresh()
        from core.utils.bar_preferences import load_preferences
        from core.utils.bar_surface import wallpaper_signature
        if load_preferences(self.root)['appearance']['foreground']=='custom':return
        signature=wallpaper_signature()
        if signature is not None and signature!=self._wallpaper_signature:
            self._wallpaper_signature=signature
            self.select(self.current)

    @staticmethod
    def instance():
        return getattr(QApplication.instance(), '_bar_theme_controller', None)

    @staticmethod
    def _atomic_write(path, data):
        file = QSaveFile(str(path))
        if not file.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(file.errorString())
        if file.write(data) != len(data) or not file.commit():
            raise OSError(file.errorString())

    def show_menu(self, button):
        menu = QMenu(button)
        menu.setProperty('class', 'bar-theme-menu')
        menu.setStyleSheet(self.manager.stylesheet)
        apply_qmenu_style(menu)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for name, label in THEMES.items():
            action = menu.addAction(label)
            action.setData(name)
            action.setCheckable(True)
            action.setChecked(name == self.current)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, name=name: self.select_preset(name))
        menu.addSeparator()
        menu.addAction('Cài đặt thanh bar…').triggered.connect(lambda: self.request_settings())
        self.menu = menu
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(button.mapToGlobal(QPoint(0, button.height() + 4)))
        return menu

    def select_preset(self,name):
        """Explicit user preset selection discards visual overrides, not layout."""
        if name not in THEMES:return False
        dialog=self.settings_dialog
        if dialog is not None and dialog.isVisible():
            dialog._choose_theme(name)
            return dialog._flush_immediate_preferences()
        from core.utils.bar_preferences import atomic_write,create_snapshot,load_preferences,theme_preset
        path=self.root/'bar-settings.json';previous=path.read_bytes() if path.exists() else None
        palette=json.loads((self.root/'theme-profiles'/name/'palette.json').read_text(encoding='utf-8'))
        fresh=theme_preset(load_preferences(self.root),palette)
        fresh['launcher']['wallpaper_auto_theme']=name=='wallpaper'
        create_snapshot(self.root,'Trước khi dùng lại preset '+THEMES[name])
        atomic_write(path,json.dumps(fresh,ensure_ascii=False,indent=2)+'\n')
        if self.select(name):self.reload_preferences();return True
        if previous is not None:atomic_write(path,previous)
        else:path.unlink(missing_ok=True)
        return False

    def select(self, name):
        if name not in THEMES:
            return False
        profile = self.root / 'theme-profiles' / name
        try:
            from core.utils.bar_preferences import compose_styles
            css = compose_styles(self.root, name).encode('utf-8')
            palette = json.loads((profile / 'palette.json').read_text(encoding='utf-8'))
            if not css or not all(key in palette for key in ('TEXT', 'BASE', 'MAUVE', 'PINK')):
                raise ValueError('Incomplete theme profile')
            previous_css = (self.root / 'styles.css').read_bytes()
            previous_state = (self.root / 'theme.json').read_bytes() if (self.root / 'theme.json').exists() else None
            try:
                self._atomic_write(self.root / 'styles.css', css)
                self._atomic_write(self.root / 'theme.json', (json.dumps({'name': name}) + '\n').encode('utf-8'))
                self.manager.on_styles_modified()
            except Exception:
                self._atomic_write(self.root / 'styles.css', previous_css)
                if previous_state is not None:
                    self._atomic_write(self.root / 'theme.json', previous_state)
                raise
            self.current = name
            for widget in QApplication.topLevelWidgets():
                # Menus cache a stylesheet when they are first constructed.
                if isinstance(widget, QMenu):
                    widget.setStyleSheet(self.manager.stylesheet)
            self._sync_calendar_colors()
            self._apply_integrations()
            self._send_island(name)
            if self.settings_dialog is not None and self.settings_dialog.isVisible():
                self.settings_dialog.selected_theme = name
                self.settings_dialog.theme_buttons[name].setChecked(True)
                self.settings_dialog.refresh_style()
            logging.info('Bar theme selected: %s', name)
            return True
        except (OSError, ValueError, RuntimeError):
            logging.exception('Could not apply bar theme %s', name)
            return False

    def _sync_calendar_colors(self):
        try:
            from core.utils.theme_tokens import effective_palette
            palette = effective_palette(self.root, self.current)
            for widget in QApplication.allWidgets():
                options = getattr(getattr(widget, 'config', None), 'calendar', None)
                if options is not None and hasattr(options, 'holiday_color'):
                    options.holiday_color = palette['PINK']
                    calendar = getattr(widget, 'calendar', None)
                    if calendar is not None:
                        calendar.holiday_color = palette['PINK']
                        calendar.updateCells()
        except (OSError, ValueError, RuntimeError):
            logging.debug('Could not update calendar theme', exc_info=True)

    def _apply_integrations(self):
        from core.utils.bar_preferences import load_preferences
        from core.utils.theme_tokens import effective_palette
        from core.utils.bar_surface import apply_backdrops
        try:
            apply_backdrops(self.manager,load_preferences(self.root),effective_palette(self.root,self.current))
            self.border_bridge.request()
        except (OSError,ValueError,RuntimeError):logging.warning('Could not apply bar integration settings',exc_info=True)

    def show_settings(self, page=None):
        """Open a persistent window and re-present after popup input unwinds."""
        from core.utils.bar_settings import BarSettingsDialog
        from core.utils.qobject import is_valid_qobject
        try:
            logging.info('Bar settings open requested; page=%s',page)
            if self.settings_dialog is None or not is_valid_qobject(self.settings_dialog):
                self.settings_dialog = BarSettingsDialog(self)
                self.settings_dialog.finished.connect(self._settings_closed)
            dialog = self.settings_dialog
            if page is not None:
                dialog.nav.setCurrentRow(max(0, min(dialog.pages.count()-1, int(page))))
            self._settings_serial+=1;serial=self._settings_serial
            self._present_settings(dialog,serial)
            # A popup's mouse grab/focus teardown may occur after clicked or
            # QAction.triggered. The request must survive that event turn.
            QTimer.singleShot(0,lambda:self._present_settings(dialog,serial))
            QTimer.singleShot(120,lambda:self._present_settings(dialog,serial))
            return dialog
        except Exception:
            logging.exception('Could not open bar settings')
            self.settings_dialog=None
            return None

    def _present_settings(self,dialog,serial):
        from core.utils.qobject import is_valid_qobject
        if serial!=self._settings_serial or self.settings_dialog is not dialog or not is_valid_qobject(dialog):return
        if dialog.isMinimized():dialog.showNormal()
        else:dialog.show()
        # GUI programs may be started with STARTF_USESHOWWINDOW/SW_HIDE by a
        # tray launcher. Windows can then hide the first normal window while
        # Qt still reports it as visible. Re-enter Qt's show path once; another
        # QWidget.show() alone would be a no-op in that inconsistent state.
        if os.name=='nt' and dialog.isVisible():
            import ctypes
            if not ctypes.windll.user32.IsWindowVisible(ctypes.c_void_p(int(dialog.winId()))):
                logging.info('Recovering natively hidden Settings window')
                dialog.hide();dialog.show()
        screens=QApplication.screens()
        title=dialog.frameGeometry().topLeft()+QPoint(32,16)
        if screens and not any(screen.availableGeometry().contains(title) for screen in screens):
            area=screens[0].availableGeometry();dialog.move(area.center()-dialog.rect().center())
        dialog.raise_();dialog.activateWindow()
        handle=dialog.windowHandle()
        if handle is not None:handle.requestActivate()
        logging.info('Bar settings presented; visible=%s minimized=%s',dialog.isVisible(),dialog.isMinimized())

    def request_settings(self,page=None):
        """Safe entry point for popups and the normal Windows app shortcut."""
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget,QMenu) or hasattr(widget,'_popup_content'):
                if widget.isVisible():widget.hide()
        QTimer.singleShot(0,lambda:self.show_settings(page))

    def _settings_closed(self, result):
        logging.info('Bar settings closed')
        dialog = self.sender()
        if self.settings_dialog is dialog:
            self._settings_serial+=1
            self.settings_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _reopen_settings(self):
        marker = self.root / 'reopen-bar-settings.json'
        try:
            data = json.loads(marker.read_text(encoding='utf-8'))
            marker.unlink()
            self.show_settings(data.get('page', 0))
        except (OSError, ValueError, TypeError):
            pass

    def reload_preferences(self):
        self._send_message({'kind': 'settings'})
        if hasattr(self,'wallpaper_theme'):QTimer.singleShot(0,self.wallpaper_theme.refresh)

    def _send_island(self, name):
        self._send_message({'kind': 'theme', 'name': name})

    def _send_message(self, message):
        root = self.root / 'dynamic-island'
        key = hashlib.sha256(os.fsencode(os.path.normcase(str(root.resolve())))).hexdigest()[:20]
        socket = QLocalSocket(self)
        def send():
            socket.write((json.dumps(message) + '\n').encode('utf-8'))
            socket.disconnectFromServer()
        socket.connected.connect(send)
        socket.disconnected.connect(socket.deleteLater)
        socket.errorOccurred.connect(socket.deleteLater)
        socket.connectToServer('caelestia-yasb-' + key)
