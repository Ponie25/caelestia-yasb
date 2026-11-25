"""Local, same-machine Settings launcher; no executable or arbitrary commands."""
import hashlib,json,logging,os
from PyQt6.QtCore import QObject
from PyQt6.QtNetwork import QLocalServer

class SettingsEntry(QObject):
    def __init__(self,controller):
        super().__init__(controller);self.controller=controller
        key=hashlib.sha256(os.fsencode(os.path.normcase(str(controller.root.resolve())))).hexdigest()[:20]
        self.name='yasb-settings-'+key;self.server=QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._connected)
        if not self.server.listen(self.name):logging.warning('Settings launcher unavailable: %s',self.server.errorString())
    def _connected(self):
        while self.server.hasPendingConnections():
            socket=self.server.nextPendingConnection();socket._settings_buffer=bytearray()
            socket.readyRead.connect(lambda socket=socket:self._read(socket))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():self._read(socket)
    def _read(self,socket):
        if getattr(socket,'_settings_handled',False):return
        socket._settings_buffer.extend(bytes(socket.readAll()))
        if len(socket._settings_buffer)>32768:socket.disconnectFromServer();return
        if b'\n' not in socket._settings_buffer:return
        socket._settings_handled=True
        try:
            message=json.loads(bytes(socket._settings_buffer).split(b'\n',1)[0])
            ok=self._dispatch(message)
            socket.write((json.dumps({'ok':ok})+'\n').encode('utf-8'))
        except (OSError,ValueError,TypeError,KeyError):socket.write(b'{"ok":false}\n')
        socket.disconnectFromServer()

    def _dispatch(self,message):
        if not isinstance(message,dict):return False
        action=message.get('action')
        if action=='open':
            page=message.get('page')
            if page is not None and (type(page) is not int or not 0<=page<=7):return False
            self.controller.request_settings(page);return True
        if action=='theme':
            name=message.get('name')
            return bool(self.controller.select_preset(name)) if isinstance(name,str) and name in self.controller.theme_labels else False
        if action=='wallpaper_changed':
            self.controller.wallpaper_theme.refresh(force=True);return True
        if action in ('wallpaper_directory','wallpaper_options'):
            from core.utils.bar_preferences import load_preferences,validate_preferences,create_snapshot,atomic_write
            values={'wallpaper_directory':message.get('path')} if action=='wallpaper_directory' else message.get('options')
            if not isinstance(values,dict) or not values or any(key not in ('wallpaper_directory','wallpaper_favorites_only','wallpaper_auto_theme','wallpaper_theme_mode') for key in values):return False
            preferences=load_preferences(self.controller.root);preferences['launcher'].update(values);validate_preferences(preferences)
            dialog=self.controller.settings_dialog
            if dialog is not None and dialog.isVisible():
                previous=dialog._collect_preferences()['launcher']
                for key,value in values.items():dialog._set_field('launcher',key,value)
                if dialog._flush_immediate_preferences():return True
                for key in values:dialog._set_field('launcher',key,previous[key])
                return False
            create_snapshot(self.controller.root,'Hình nền và màu giao diện')
            atomic_write(self.controller.root/'bar-settings.json',json.dumps(preferences,ensure_ascii=False,indent=2)+'\n')
            self.controller.reload_preferences();return True
        return False
