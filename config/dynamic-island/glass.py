import ctypes
from ctypes import wintypes
import logging
import math
import winreg


class GlassLayer:
    """A rounded DWM backdrop under the existing transparent Qt window."""

    def __init__(self):
        self.hwnd = None
        self.visible = False
        self.enabled = False
        self.failed = False
        self.placement = None
        self.shape = None

    def prepare(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                self.enabled = bool(winreg.QueryValueEx(key, 'EnableTransparency')[0])
        except OSError:
            self.enabled = True
        if self.enabled and not self.failed and not self.hwnd:
            try:
                self._create()
            except (ImportError, OSError):
                self._fallback('Windows backdrop unavailable')

    def _create(self):
        # Register the types used by the WinRT desktop interop projection.
        import winrt.windows.foundation.numerics
        import winrt.windows.ui.composition.desktop
        from winrt.windows.system import DispatcherQueue
        from winrt.windows.system.interop import create_dispatcher_queue_controller
        from winrt.windows.ui.composition import CompositionBorderMode, Compositor
        from winrt.windows.ui.composition.interop import create_desktop_window_target

        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        dwm = ctypes.WinDLL('dwmapi')
        self.user.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
        ]
        self.user.CreateWindowExW.restype = wintypes.HWND
        self.user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, *([ctypes.c_int] * 4), wintypes.UINT]
        self.user.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        self.user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.DestroyWindow.argtypes = [wintypes.HWND]
        self.gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        self.gdi.CreateRoundRectRgn.restype = wintypes.HRGN
        self.gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

        self.controller = create_dispatcher_queue_controller() if DispatcherQueue.get_for_current_thread() is None else None
        self.compositor = Compositor()
        no_redirection, no_activate = 0x00200000, 0x08000000
        tool_window, topmost, transparent = 0x00000080, 0x00000008, 0x00000020
        self.hwnd = self.user.CreateWindowExW(
            no_redirection | no_activate | tool_window | topmost | transparent,
            'Static', 'YASB Island Backdrop', 0x80000000, 0, 0, 1, 1, None, None, None, None,
        )
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        use_host_backdrop = wintypes.BOOL(1)
        status = dwm.DwmSetWindowAttribute(self.hwnd, 17, ctypes.byref(use_host_backdrop), ctypes.sizeof(use_host_backdrop))
        if status != 0:
            raise OSError(f'DWMWA_USE_HOSTBACKDROPBRUSH returned {status:#x}')
        self.target = create_desktop_window_target(self.compositor, self.hwnd)
        self.visual = self.compositor.create_sprite_visual()
        self.visual.brush = self.compositor.create_host_backdrop_brush()
        self.visual.border_mode = CompositionBorderMode.SOFT
        self.geometry = self.compositor.create_rounded_rectangle_geometry()
        self.visual.clip = self.compositor.create_geometric_clip_with_geometry(self.geometry)
        self.target.root = self.visual

    def sync(self, front, bounds, rect, radius, scale):
        if not self.enabled or self.failed or not self.hwnd or bounds is None:
            self.hide()
            return
        shape = (math.floor(rect.left() * scale), math.floor(rect.top() * scale),
                 math.ceil(rect.right() * scale), math.ceil(rect.bottom() * scale), round(radius * scale))
        placement = (front, bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top)
        try:
            if shape != self.shape:
                self._shape(*shape)
                self.shape = shape
            if not self.visible or placement != self.placement:
                show_without_activation = 0x40 | 0x10
                if not self.user.SetWindowPos(self.hwnd, *placement, show_without_activation):
                    raise ctypes.WinError(ctypes.get_last_error())
                self.visible = True
                self.placement = placement
        except OSError:
            self._fallback('Could not position the Windows backdrop')

    def _shape(self, left, top, right, bottom, radius):
        size = (right - left, bottom - top)
        self.visual.offset = (left, top, 0)
        self.visual.size = size
        self.geometry.size = size
        self.geometry.corner_radius = (radius, radius)
        # The composition clip supplies the soft edge. The HWND region keeps
        # the transparent margin out of Win32 hit testing.
        diameter = 2 * radius
        region = self.gdi.CreateRoundRectRgn(left, top, right, bottom, diameter, diameter)
        if not region:
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.user.SetWindowRgn(self.hwnd, region, True):
            self.gdi.DeleteObject(region)
            raise ctypes.WinError(ctypes.get_last_error())

    def _fallback(self, message):
        logging.warning(message, exc_info=True)
        self.failed = True
        self.close()

    def hide(self):
        if self.visible:
            self.user.ShowWindow(self.hwnd, 0)
            self.visible = False

    def close(self):
        self.hide()
        if self.hwnd:
            if hasattr(self, 'target'):
                self.target.root = None
            self.user.DestroyWindow(self.hwnd)
            self.hwnd = None
