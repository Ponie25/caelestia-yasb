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
        socket._settings_buffer.extend(bytes(socket.readAll()))
        if len(socket._settings_buffer)>1024:socket.disconnectFromServer();return
        if b'\n' not in socket._settings_buffer:return
        try:
            message=json.loads(bytes(socket._settings_buffer).split(b'\n',1)[0])
            if isinstance(message,dict) and message.get('action')=='open':
                self.controller.request_settings()
                socket.write(b'{"ok":true}\n')
        except (ValueError,TypeError):pass
        socket.disconnectFromServer()
