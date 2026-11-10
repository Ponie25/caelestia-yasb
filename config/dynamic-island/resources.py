from collections import deque
from concurrent.futures import ThreadPoolExecutor
import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import time
import winreg

import psutil
from PySide6.QtCore import QObject, Signal, Slot


class Gpu:
    def __init__(self):
        self.lib = None
        self.device = ctypes.c_void_p()
        self.name = 'GPU'
        paths = (Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/nvml.dll',
                 Path(os.environ.get('ProgramW6432', r'C:\Program Files')) / 'NVIDIA Corporation/NVSMI/nvml.dll')
        for path in paths:
            if path.is_file():
                try:
                    lib = ctypes.CDLL(str(path))
                    if lib.nvmlInit_v2() == 0:
                        if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.device)) == 0:
                            self.lib = lib
                            break
                        lib.nvmlShutdown()
                except (OSError, AttributeError):
                    pass
        if self.lib:
            name = ctypes.create_string_buffer(96)
            if self.lib.nvmlDeviceGetName(self.device, name, len(name)) == 0:
                self.name = name.value.decode('utf-8', errors='replace').removeprefix('NVIDIA ')

    def sample(self):
        if not self.lib:
            return None, None
        levels = (ctypes.c_uint * 2)()
        temp = ctypes.c_uint()
        usage = levels[0] if self.lib.nvmlDeviceGetUtilizationRates(self.device, ctypes.byref(levels)) == 0 else None
        temperature = temp.value if self.lib.nvmlDeviceGetTemperature(self.device, 0, ctypes.byref(temp)) == 0 else None
        return usage, temperature

    def close(self):
        if self.lib:
            self.lib.nvmlShutdown()
            self.lib = None


def _cpu_name():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            return ' '.join(winreg.QueryValueEx(key, 'ProcessorNameString')[0].split())
    except OSError:
        return 'Bộ xử lý Windows'


@dataclass(frozen=True)
class Sample:
    cpu: float = 0
    ram: float = 0
    ram_text: str = '—'
    disk: float | None = None
    disk_text: str = '—'
    gpu: float | None = None
    gpu_temp: int | None = None
    rx: float = 0
    tx: float = 0
    total: int = 0


class Metrics(QObject):
    changed = Signal()
    received = Signal(object)

    def __init__(self):
        super().__init__()
        self.boot = psutil.boot_time()
        self.desktop = 'Windows Desktop'
        self.windows = 'Windows 11' if sys.getwindowsversion().build >= 22000 else 'Windows 10'
        self.cpu_name = _cpu_name()
        self.cores = psutil.cpu_count(logical=True) or 1
        self.drives = (os.environ.get('SystemDrive', 'C:') + '\\',)
        self.drive_index = 0
        self.data = Sample()
        self.network_history = deque(maxlen=42)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='Dashboard metrics')
        self.pending = False
        self.stopping = False
        self.gpu = None
        self.net_last = None
        self.received.connect(self._apply)

    @property
    def percent(self):
        return self.data.cpu, self.data.ram, self.data.disk

    @property
    def drive(self):
        return self.drives[self.drive_index]

    def cycle_drive(self):
        self.drive_index = (self.drive_index + 1) % len(self.drives)
        self.sample()

    def sample(self, details=False):
        if not self.pending and not self.stopping:
            self.pending = True
            self.executor.submit(self._collect, self.drive, details, self.net_last is None)

    def _collect(self, drive, details, first):
        info = None
        try:
            if first:
                paths = tuple(p.mountpoint for p in psutil.disk_partitions() if 'fixed' in p.opts)
                desktop = any((p.info['name'] or '').casefold() == 'komorebi.exe' for p in psutil.process_iter(['name']))
                info = paths, desktop
            if details and self.gpu is None:
                self.gpu = Gpu()
            gpu, temp = self.gpu.sample() if self.gpu and details else (None, None)
            cpu = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            try:
                disk = psutil.disk_usage(drive)
            except OSError:
                disk = None
            rx = tx = total = 0
            counters = psutil.net_io_counters()
            now = time.monotonic()
            if counters is not None:
                total = counters.bytes_recv + counters.bytes_sent
                if self.net_last:
                    last_time, last_recv, last_sent = self.net_last
                    dt = max(0.05, now - last_time)
                    rx = max(0, counters.bytes_recv - last_recv) / dt
                    tx = max(0, counters.bytes_sent - last_sent) / dt
                self.net_last = now, counters.bytes_recv, counters.bytes_sent
            result = Sample(cpu, memory.percent, f'{memory.used / 2**30:.1f} / {memory.total / 2**30:.1f} GiB',
                            disk.percent if disk else None,
                            f'{disk.used / 2**30:.0f} / {disk.total / 2**30:.0f} GiB' if disk else '—',
                            gpu, temp, rx, tx, total)
            self.received.emit((drive, result, info))
        except (OSError, RuntimeError, psutil.Error):
            self.received.emit(None)

    @Slot(object)
    def _apply(self, packet):
        self.pending = False
        if packet is None or self.stopping:
            return
        drive, data, info = packet
        if info is not None:
            paths, desktop = info
            self.drives = tuple(dict.fromkeys((self.drives[0], *paths)))
            self.desktop = 'Komorebi' if desktop else 'Windows Desktop'
        if drive != self.drive:
            self.sample(details=True)
            return
        self.data = data
        self.network_history.append((data.rx, data.tx))
        self.changed.emit()

    def close(self):
        self.stopping = True
        self.executor.submit(self._close_gpu)
        self.executor.shutdown(wait=False)

    def _close_gpu(self):
        if self.gpu:
            self.gpu.close()
