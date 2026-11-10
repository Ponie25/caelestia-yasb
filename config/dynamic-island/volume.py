import logging
from _ctypes import COMError

from PySide6.QtCore import QObject, Signal
from pycaw.callbacks import MMNotificationClient
from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
from pycaw.pycaw import AudioUtilities


class DefaultOutputListener(MMNotificationClient):
    def __init__(self, changed):
        super().__init__()
        self.changed = changed

    def on_default_device_changed(self, flow, flow_id, role, role_id, default_device_id):
        if flow_id == EDataFlow.eRender.value and role_id == ERole.eMultimedia.value:
            self.changed()

    def on_device_state_changed(self, device_id, state, state_id):
        self.changed()

    def on_device_added(self, device_id):
        self.changed()

    def on_device_removed(self, device_id):
        self.changed()


class OutputVolume(QObject):
    device_changed = Signal()

    def __init__(self):
        super().__init__()
        self.enumerator = None
        self.listener = None
        self.device = None
        self.endpoint = None
        self.level = None
        self.muted = False

    def refresh(self):
        try:
            if self.enumerator is None:
                self.enumerator = AudioUtilities.GetDeviceEnumerator()
            native = self.enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eMultimedia.value)
            if self.device is None or self.device.id != native.GetId():
                self.device = AudioUtilities.CreateDevice(native)
            self.endpoint = self.device.EndpointVolume
            self.level = round(self.endpoint.GetMasterVolumeLevelScalar() * 100)
            self.muted = bool(self.endpoint.GetMute())
        except (COMError, OSError, AttributeError):
            self.device = None
            self.endpoint = None
            self.level = None
            self.muted = False

    def watch(self):
        self.refresh()
        if self.enumerator is not None and self.listener is None:
            listener = DefaultOutputListener(self.device_changed.emit)
            try:
                self.enumerator.RegisterEndpointNotificationCallback(listener)
                self.listener = listener
            except (COMError, OSError):
                logging.debug('Could not subscribe to Windows audio output changes', exc_info=True)

    def stop(self):
        if self.listener is not None:
            try:
                self.enumerator.UnregisterEndpointNotificationCallback(self.listener)
            except (COMError, OSError):
                logging.debug('Could not unregister the Windows audio listener', exc_info=True)
            self.listener = None

    def outputs(self):
        try:
            return tuple((device.id, device.FriendlyName) for device in AudioUtilities.GetAllDevices(
                data_flow=EDataFlow.eRender.value, device_state=DEVICE_STATE.ACTIVE.value))
        except (COMError, OSError, AttributeError):
            return ()

    def select_output(self, device_id):
        try:
            AudioUtilities.SetDefaultDevice(device_id, roles=[ERole.eMultimedia, ERole.eConsole])
            return True
        except (COMError, OSError):
            logging.debug('Could not switch the default Windows audio output', exc_info=True)
            return False

    def set_level(self, value):
        if self.endpoint is not None:
            try:
                if value != self.level:
                    self.endpoint.SetMasterVolumeLevelScalar(value / 100, None)
                    self.level = value
                if value > 0 and self.muted:
                    self.endpoint.SetMute(False, None)
                    self.muted = False
            except (COMError, OSError):
                logging.debug('Windows audio output changed during volume adjustment', exc_info=True)
                self.refresh()

    def toggle_mute(self):
        self.refresh()
        if self.endpoint is not None:
            try:
                self.endpoint.SetMute(not self.muted, None)
                self.muted = not self.muted
            except (COMError, OSError):
                self.refresh()
