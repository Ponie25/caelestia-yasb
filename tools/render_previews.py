"""Capture the installed Island widgets with demo data and no desktop content."""

from datetime import date, timedelta
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import math
import sys
import time
from types import SimpleNamespace


install = Path(sys.argv[1]).resolve()
island_dir = install / "config" / "dynamic-island"
sys.path[:0] = [str(island_dir), str(island_dir / "runtime")]

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from audio_mixer import AppVolume, MUTE, VOLUME
from dashboard import TAB_RECTS
from media import RepeatMode
from resources import Sample
from weather import Forecast, ForecastDay


def album_art():
    image = QImage(420, 420, QImage.Format.Format_RGB32)
    paint = QPainter(image)
    paint.setRenderHint(QPainter.RenderHint.Antialiasing)
    sky = QLinearGradient(0, 0, 410, 430)
    sky.setColorAt(0, QColor("#15182d"))
    sky.setColorAt(0.62, QColor("#3b3054"))
    sky.setColorAt(1, QColor("#6c435f"))
    paint.fillRect(image.rect(), sky)
    for i in range(54):
        x, y = (i * 1297 + 31) % 420, (i * 983 + 17) % 420
        paint.setPen(QColor(203, 190, 245, 55 + i % 6 * 21))
        paint.drawPoint(x, y)
    paint.translate(210, 215)
    paint.rotate(-29)
    paint.setBrush(Qt.BrushStyle.NoBrush)
    for i in range(9):
        paint.setPen(QPen(QColor(225, 175, 230, 165 - i * 12), 1.15))
        paint.drawEllipse(QRectF(-169 - 3 * i, -52 - 4 * i, 338 + 6 * i, 104 + 8 * i))
    paint.setPen(Qt.PenStyle.NoPen)
    paint.setBrush(QColor("#f5c2e7"))
    paint.drawEllipse(QPointF(118, -35), 9, 9)
    paint.end()
    return image


class DemoOutput:
    level = 64
    muted = False
    device = SimpleNamespace(FriendlyName="Hệ thống · Loa")

    def refresh(self):
        pass

    def set_level(self, value):
        self.level = value

    def toggle_mute(self):
        self.muted = not self.muted


class DemoSession:
    level = 0.72
    muted = False

    def SetMasterVolume(self, value, _):
        self.level = value

    def SetMute(self, value, _):
        self.muted = value


def capture(widget, output, crop_width=None):
    pixmap = widget.grab()
    if crop_width is not None:
        width = round(crop_width * pixmap.devicePixelRatio())
        pixmap = pixmap.copy((pixmap.width() - width) // 2, 0, width, pixmap.height())
    logical = pixmap.deviceIndependentSize()
    scale = 1.5
    image = QImage(round((logical.width() + 32) * scale), round((logical.height() + 32) * scale),
                   QImage.Format.Format_RGB32)
    image.setDevicePixelRatio(scale)
    paint = QPainter(image)
    backdrop = QLinearGradient(0, 0, logical.width(), logical.height())
    backdrop.setColorAt(0, QColor("#212237"))
    backdrop.setColorAt(1, QColor("#2a2032"))
    paint.fillRect(QRectF(0, 0, logical.width() + 32, logical.height() + 32), backdrop)
    paint.drawPixmap(QPointF(16, 16), pixmap)
    paint.end()
    if not image.save(str(output)):
        raise RuntimeError(f"Could not save {output}")


def main():
    out = Path(sys.argv[2]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    loader = SourceFileLoader("island", str(island_dir / "island.pyw"))
    spec = spec_from_loader(loader.name, loader)
    island = module_from_spec(spec)
    loader.exec_module(island)

    app = QApplication([])
    commands = []
    widget = island.Island(lambda *args: commands.append(args), lambda: None)
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    widget.setFixedHeight(widget.HEIGHT)
    widget.expanded = True
    widget.motion = (712.0, float(widget.HEIGHT), 0.0, 1.0, 0.0)
    widget.target = widget.motion
    widget.state = island.MediaState(
        4, "A Quiet Orbit", "Studio Meridian", playing=True, previous=True, toggle=True, next=True,
        duration=220, position=89, captured_at=time.monotonic(), source="Media Player", seek=True,
        shuffle=False, repeat=RepeatMode.NONE,
    )
    widget.art = album_art()
    widget.volume = DemoOutput()
    dashboard = widget.dashboard
    metrics = dashboard.metrics
    metrics.boot = time.time() - (4 * 3600 + 32 * 60)
    metrics.desktop, metrics.cpu_name, metrics.cores = "Windows Desktop", "AMD Ryzen 7", 16
    metrics.gpu = SimpleNamespace(name="GeForce RTX", close=lambda: None)
    metrics.data = Sample(24, 51, "16.3 / 32.0 GiB", 37, "368 / 1000 GiB", 18, 48,
                          2_458_624, 291_840, 1_095_761_920)
    metrics.network_history.extend(
        (int(1600 + 1500 * math.sin(i / 3.9) ** 2 + 137 * (i % 7)),
         int(180 + 160 * math.sin(i / 2.3) ** 2 + 34 * (i % 3)))
        for i in range(42)
    )
    conditions = ((2, 29, 23), (3, 28, 22), (61, 27, 21), (80, 26, 20),
                  (2, 27, 20), (1, 29, 21), (0, 30, 22))
    dashboard.weather.forecast = Forecast(29, 32, 73, 11.8, 2, tuple(
        ForecastDay(date.today() + timedelta(days=i), code, high, low, 30)
        for i, (code, high, low) in enumerate(conditions)
    ), "06:02", "17:20")
    sessions = [DemoSession(), DemoSession()]
    dashboard.audio.apps = {
        "player": AppVolume("Media Player", "", 72, False, sessions),
        "browser": AppVolume("Browser", "", 39, False, []),
        "system": AppVolume("Âm thanh hệ thống", "", 18, True, []),
    }

    widget.show()
    app.processEvents()
    widget.meter.stop()
    for tab in TAB_RECTS:
        dashboard.tab = tab
        widget.update()
        app.processEvents()
        capture(widget, out / (tab.lower() + ".png"))

    dashboard.tab = "Media"
    left = Qt.MouseButton.LeftButton
    _, _, mute, slider = next(dashboard.audio._rows())
    QTest.mouseClick(widget, left, pos=mute.center().toPoint())
    assert all(session.muted for session in sessions)
    QTest.mousePress(widget, left, pos=slider.center().toPoint())
    QTest.mouseRelease(widget, left, pos=QPointF(slider.right() + 15, slider.center().y()).toPoint())
    assert all(session.level == 1 for session in sessions) and widget.volume.level == 64
    QTest.mouseClick(widget, left, pos=MUTE.center().toPoint())
    assert widget.volume.muted
    QTest.mouseClick(widget, left, pos=VOLUME.center().toPoint())
    assert abs(widget.volume.level - 50) <= 1
    QTest.mouseClick(widget, left, pos=island.tab_views.MEDIA_BUTTONS["toggle"].center().toPoint())
    assert commands[-1][:2] == (4, "toggle")
    widget.expanded = False
    widget.motion = widget.target = (116.0, 28.0, 0.0, 0.0, 0.0)
    widget.setFixedHeight(widget.PILL_HEIGHT)
    capture(widget, out / "closed-island.png", crop_width=142)
    widget.hide()
    metrics.close()
    print("Captured all four tabs and checked playback, output volume and per-app mixer clicks.")


if __name__ == "__main__":
    main()
