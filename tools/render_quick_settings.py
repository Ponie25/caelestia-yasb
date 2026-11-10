"""Capture the packaged YASB Control Center without real account/device data."""

from importlib.machinery import EXTENSION_SUFFIXES, PathFinder
from importlib.util import spec_from_file_location
from pathlib import Path
import os
import sys
from unittest.mock import patch


install = Path(sys.argv[1]).resolve()
config = install / "config"
lib = install / "yasb" / "lib"
os.environ["YASB_CONFIG_HOME"] = str(config)
sys.path[:0] = [str(lib), str(lib / "library.zip")]
dll_paths = [os.add_dll_directory(str(path)) for path in (lib, lib / "PyQt6/Qt6/bin", lib.parent)]


class FrozenExtensions:
    """Resolve cx_Freeze's flattened extension files in the embedded interpreter."""

    @staticmethod
    def find_spec(fullname, path=None, target=None):
        for suffix in EXTENSION_SUFFIXES:
            file = lib / (fullname + suffix)
            if file.is_file():
                return spec_from_file_location(fullname, file)


sys.meta_path.insert(sys.meta_path.index(PathFinder), FrozenExtensions())

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontDatabase, QImage, QLinearGradient, QPainter
from PyQt6.QtWidgets import QApplication
from qt_css_engine import extract_rules
import yaml

from core.bar_helper import GlobalState
from core.validation.widgets.yasb.control_center import ControlCenterConfig
from core.widgets.services.control_center.sections import quick_actions
from core.widgets.yasb import control_center


class DemoAudio:
    def register_widget(self, _):
        pass

    def unregister_widget(self, _):
        pass

    def get_volume_interface(self):
        return self

    def get_microphone_interface(self):
        return self

    def GetMasterVolumeLevelScalar(self):
        return 0.64

    def GetMute(self):
        return False


class PreviewPopup(control_center.PopupWidget):
    def __init__(self, **options):
        super().__init__(**options)
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)


def main():
    app = QApplication([])
    for font in (config / "fonts").glob("*.ttf"):
        assert QFontDatabase.addApplicationFont(str(font)) >= 0
    qss, _ = extract_rules((config / "styles.css").read_text(encoding="utf-8"))
    app.setStyleSheet(qss)
    GlobalState.set_stylesheet(qss)
    settings = yaml.safe_load((config / "config.yaml").read_bytes())
    options = ControlCenterConfig.model_validate(settings["widgets"]["control_center"]["options"])

    with patch.object(control_center, "PopupWidget", PreviewPopup), \
         patch.object(control_center, "AudioOutputService", DemoAudio), \
         patch.object(control_center, "AudioInputService", DemoAudio), \
         patch.object(quick_actions.DndService, "get_status", return_value="priority"):
        widget = control_center.ControlCenterWidget(options)
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        widget.show()
        widget._show_menu()
        app.processEvents()
        dialog = widget.dialog
        section = widget._section_widgets["quick_actions"]
        buttons = list(section._action_buttons.values())
        assert len(buttons) == 6 and len({button.y() for button in buttons}) == 2

        preview = dialog.grab()
        size = preview.deviceIndependentSize()
        scale = preview.devicePixelRatio()
        image = QImage(round((size.width() + 36) * scale), round((size.height() + 36) * scale),
                       QImage.Format.Format_RGB32)
        image.setDevicePixelRatio(scale)
        painter = QPainter(image)
        background = QLinearGradient(0, 0, size.width(), size.height())
        background.setColorAt(0, QColor("#212237"))
        background.setColorAt(1, QColor("#2a2032"))
        painter.fillRect(QRectF(0, 0, size.width() + 36, size.height() + 36), background)
        painter.drawPixmap(QPointF(18, 18), preview)
        painter.end()
        assert image.save(sys.argv[2])

        def check_closed(*args):
            assert not dialog.isVisible()

        screenshot = section._action_buttons["screenshot"]
        with patch.object(quick_actions, "_flameshot_executable", return_value=None), \
             patch.object(quick_actions.ScreenshotService, "start", side_effect=check_closed) as capture:
            screenshot.clicked.emit()
            capture.assert_called_once()
        widget._show_menu()
        executable = r"C:\Program Files\Flameshot\bin\flameshot.exe"
        with patch.object(quick_actions, "_flameshot_executable", return_value=executable), \
             patch.object(quick_actions.subprocess, "Popen", side_effect=check_closed) as launch:
            screenshot.clicked.emit()
            launch.assert_called_once_with([executable, "gui"])
        widget.close()
    print("Captured Quick Settings and checked both screenshot actions.")


if __name__ == "__main__":
    main()
