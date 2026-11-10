import logging
from _ctypes import COMError

from pycaw.constants import EDataFlow, ERole
from pycaw.pycaw import AudioUtilities


class OutputVolume:
    def __init__(self):
        self.enumerator = None
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
