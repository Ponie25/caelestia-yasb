from base64 import b64encode
import hashlib
from io import BytesIO
import json
import logging
import os
import subprocess
import sys
import uuid
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFontDatabase, QScreen
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication
from qt_css_engine import TransitionEngine, extract_rules

from core.bar import Bar
from core.bar_helper import GlobalState
from core.config import get_config, get_stylesheet
from core.events.service import EventService
from core.utils.controller import reload_application
from core.utils.utilities import get_screen_by_name
from core.utils.widget_builder import WidgetBuilder
from core.utils.win32.hotkeys import (
    HotkeyBinding,
    HotkeyDispatcher,
    HotkeyListener,
    collect_widget_keybindings,
)
from core.validation.bar import BarConfig
from core.validation.config import YasbConfig
from settings import DEFAULT_CONFIG_DIRECTORY


def _island_logo_png(image):
    from PIL import Image

    image.thumbnail((48, 48), Image.Resampling.LANCZOS)
    with BytesIO() as data:
        image.convert("RGBA").save(data, format="PNG")
        return b64encode(data.getvalue()).decode("ascii")


def _island_local_logo(value):
    from PIL import Image

    if not value:
        return ""
    path = Path(value)
    roots = tuple(Path(directory).resolve() for key in ("LOCALAPPDATA", "TEMP", "ProgramFiles")
                  if (directory := os.getenv(key)))
    if (path.drive.startswith(("\\\\", "//")) or
        not any(path.is_relative_to(root) for root in roots)):
        return ""
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return ""
        with Image.open(path) as image:
            if image.width * image.height <= 4_000_000:
                return _island_logo_png(image)
    except (OSError, ValueError, Image.DecompressionBombError):
        pass
    return ""


@lru_cache(maxsize=48)
def _island_app_logo(aumid):
    from comtypes import CoInitialize, CoUninitialize
    from core.utils.icons.sources import AppIcon, load_icon

    try:
        CoInitialize()
        try:
            image = load_icon(AppIcon(aumid), 48).image
            return _island_logo_png(image) if image is not None else ""
        finally:
            CoUninitialize()
    except Exception:
        logging.debug("Could not load Island notification icon", exc_info=True)
        return ""


class BarManager(QObject):
    styles_modified = pyqtSignal()
    config_modified = pyqtSignal()
    island_notifications = pyqtSignal(object)

    def __init__(self, config: YasbConfig, stylesheet: str):
        super().__init__()
        self.config = config
        self.stylesheet, self.rules = extract_rules(stylesheet)
        self.animation_engine = TransitionEngine(self.rules)
        GlobalState.set_stylesheet(self.stylesheet)
        GlobalState.set_tooltip_options(self.config.tooltip)
        self.event_service = EventService()
        self.widget_event_listeners: set[type[QThread]] = set()
        self.bars: list[Bar] = []
        self.config.bars = {n: bar for n, bar in self.config.bars.items() if bar.enabled}
        self._threads: dict[type[QThread], QThread] = {}
        self._active_listeners = {}
        self._widget_builder = WidgetBuilder(self.config.widgets)
        self._prev_listeners: set[type[QThread]] = set()
        self._hotkey_listener: HotkeyListener | None = None
        self._hotkey_dispatcher: HotkeyDispatcher | None = None
        self._collected_keybindings: list[HotkeyBinding] = []
        self._registered_hotkey_widgets: set[tuple[str, str]] = set()  # (widget_name, screen_name)

        self.styles_modified.connect(self.on_styles_modified)
        self.config_modified.connect(self.on_config_modified)
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("BarManager requires a running QApplication")
        self._app = app
        self._island = None
        self._island_seen_toasts = None
        self._island_notification_bridge = False
        self.island_notifications.connect(self._forward_island_notifications, Qt.ConnectionType.QueuedConnection)
        for font in (Path(DEFAULT_CONFIG_DIRECTORY) / "fonts").glob("*.ttf"):
            if QFontDatabase.addApplicationFont(str(font)) == -1:
                logging.warning("Could not load bundled font %s", font.name)
        self._app.installEventFilter(self.animation_engine)
        self._app.aboutToQuit.connect(self._stop_island)
        self._app.aboutToQuit.connect(self.stop_listener_threads)
        self._app.screenAdded.connect(self.on_screens_update)
        self._app.screenRemoved.connect(self.on_screens_update)

    def _disconnect_reload_signals(self):
        with suppress(TypeError):
            self._app.screenAdded.disconnect(self.on_screens_update)
            self._app.screenRemoved.disconnect(self.on_screens_update)
            self.config_modified.disconnect(self.on_config_modified)

    @pyqtSlot()
    def on_styles_modified(self):
        stylesheet = get_stylesheet(show_error_dialog=True)
        if stylesheet and (stylesheet != self.stylesheet):
            self.stylesheet, new_rules = extract_rules(stylesheet)
            GlobalState.set_stylesheet(self.stylesheet)
            self.animation_engine.reload_rules(new_rules)
            for bar in self.bars:
                bar.setStyleSheet(self.stylesheet)

    @pyqtSlot()
    def on_config_modified(self):
        try:
            config = get_config(show_error_dialog=True)
        except Exception as e:
            logging.error("Error loading config: %s", e)
            return
        if config and (config != self.config):
            # Fields that don't trigger a full application reload
            exclude = {"watch_config", "watch_stylesheet"}

            if config.model_dump(exclude=exclude) != self.config.model_dump(exclude=exclude):
                self.config = config
                self._disconnect_reload_signals()
                reload_application("Reloading Application because of config change.")
            else:
                self.config = config
                logging.info("Configuration updated (no reload required).")
            logging.info("Successfully loaded updated config and re-initialised all bars.")

    @pyqtSlot(QScreen)
    def on_screens_update(self, _screen: QScreen) -> None:
        logging.info("Screens updated. Re-initialising all bars.")
        self._disconnect_reload_signals()
        reload_application("Reloading Application because of screen update.")

    def run_listeners_in_threads(self):
        for listener in self.widget_event_listeners:
            logging.info("Starting %s...", listener.__name__)
            thread = listener()
            thread.start()
            self._threads[listener] = thread

    def stop_listener_threads(self):
        if self._island_notification_bridge:
            self.event_service.unregister_event("WindowsNotificationsChanged", self.island_notifications)
            self._island_notification_bridge = False
            self._island_commands.close()
        # Stop hotkey listener first
        if self._hotkey_listener is not None:
            logging.info("Stopping HotkeyListener...")
            with suppress(Exception):
                self._hotkey_listener.stop()
                self._hotkey_listener.wait(1000)
            self._hotkey_listener = None
            self._hotkey_dispatcher = None

        for listener in self.widget_event_listeners:
            logging.info("Stopping %s...", listener.__name__)
            with suppress(KeyError):
                thread = self._threads[listener]
                stop = getattr(thread, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception as e:
                        logging.debug("Thread stop() raised for %s: %s", listener.__name__, e)
                try:
                    thread.quit()
                except Exception:
                    pass
                thread.wait(1000)
        self._threads.clear()
        self.widget_event_listeners.clear()

    def initialize_bars(self, init: bool = False) -> None:
        self._widget_builder = WidgetBuilder(self.config.widgets)
        primary_screen = QApplication.primaryScreen()
        primary_screen_name = primary_screen.name() if primary_screen else None

        available_screens = QApplication.screens()
        available_screen_names = [screen.name() for screen in available_screens]

        # Collect explicitly assigned screens
        assigned_screens: set[str] = set()
        for bar_config in self.config.bars.values():
            if bar_config.screens != ["*"] and bar_config.screens != ["**"]:
                for screen in bar_config.screens:
                    resolved_name = primary_screen_name if screen == "primary" else screen
                    if resolved_name not in available_screen_names:
                        logging.warning("Screen '%s' from config not found among connected screens.", resolved_name)
                        continue
                    assigned_screens.add(resolved_name)

        # Create bars
        initialized_screens: set[str] = set()
        for bar_name, bar_config in self.config.bars.items():
            if bar_config.screens == ["*"]:
                for screen in available_screens:
                    if screen.name() in assigned_screens:
                        continue
                    self.create_bar(bar_config, bar_name, screen, init)
                    initialized_screens.add(screen.name())
            elif bar_config.screens == ["**"]:
                for screen in available_screens:
                    self.create_bar(bar_config, bar_name, screen, init)
                    initialized_screens.add(screen.name())
            else:
                for screen_name in bar_config.screens:
                    resolved_name = primary_screen_name if screen_name == "primary" else screen_name
                    if resolved_name not in available_screen_names:
                        logging.warning("Screen '%s' from config not found among connected screens.", resolved_name)
                        continue
                    screen = get_screen_by_name(resolved_name)
                    if screen:
                        self.create_bar(bar_config, bar_name, screen, init)
                        initialized_screens.add(screen.name())

        self._initialized_screens = initialized_screens
        self._collect_keybindings()
        self._start_hotkey_listener()
        if init and self.bars:
            self._connect_island_notifications()
        self.run_listeners_in_threads()
        self._widget_builder.raise_alerts_if_errors_present()
        if init and self.bars:
            self._start_island()

    def _connect_island_notifications(self):
        root = Path(DEFAULT_CONFIG_DIRECTORY) / "dynamic-island"
        if not (root / "activities.py").is_file():
            return
        try:
            from core.widgets.services.notifications.windows_notification import (
                WindowsNotificationEventListener, _find_image, _get_app_info, _get_image_path,
                _get_texts, _pop_toast, _read_toast_xml,
            )
            from winrt.windows.ui.notifications import NotificationKinds
            from winrt.windows.ui.notifications.management import UserNotificationListenerAccessStatus
        except ImportError:
            logging.warning("The Windows notification listener is unavailable")
            return
        if WindowsNotificationEventListener not in self.widget_event_listeners:
            class IslandToastListener(WindowsNotificationEventListener):
                async def _read_notifications(self):
                    listener = self._listener
                    if listener is None:
                        return None
                    try:
                        if listener.get_access_status() != UserNotificationListenerAccessStatus.ALLOWED:
                            return None
                        toasts = await listener.get_notifications_async(NotificationKinds.TOAST)
                    except OSError:
                        return None
                    self._app_info = {toast.id: self._app_info.get(toast.id) or _get_app_info(toast)
                                      for toast in toasts}
                    known = {item.id for item in self._items}
                    items = []
                    made_icon = False
                    for toast in sorted(toasts, key=lambda item: item.creation_time, reverse=True):
                        texts = _get_texts(toast)
                        title, *body = texts or [""]
                        aumid, app_name, family = self._app_info[toast.id]
                        logo = ""
                        if not made_icon and toast.id not in known and aumid:
                            made_icon = True
                            xml = _pop_toast(_read_toast_xml(aumid, 20), texts)
                            if xml is not None:
                                path = _get_image_path(_find_image(xml, "appLogoOverride"), aumid, family)
                                logo = _island_local_logo(path)
                            logo = logo or _island_app_logo(aumid)
                        items.append(SimpleNamespace(id=toast.id, aumid=aumid, app_name=app_name, icon=logo,
                                                     title=title, body="\n".join(body),
                                                     created_at=toast.creation_time))
                    return items

            self.widget_event_listeners.add(IslandToastListener)
        self.event_service.register_event("WindowsNotificationsChanged", self.island_notifications)
        self._island_notification_bridge = True
        key = hashlib.sha256(os.fsencode(os.path.normcase(str(root.resolve())))).hexdigest()[:20]
        self._island_pipe = "caelestia-yasb-" + key
        self._island_commands = QLocalServer(self)
        self._island_commands.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._island_commands.newConnection.connect(self._accept_island_commands)
        if not self._island_commands.listen(self._island_pipe + "-commands"):
            logging.warning("Could not listen for Island notification commands")
        QTimer.singleShot(800, lambda: self.event_service.emit_event("WindowsNotificationRefresh", "island"))

    def _accept_island_commands(self):
        while self._island_commands.hasPendingConnections():
            socket = self._island_commands.nextPendingConnection()
            socket.setReadBufferSize(256)
            socket.readyRead.connect(lambda sock=socket: self._read_island_command(sock))
            socket.disconnected.connect(socket.deleteLater)
            timer = QTimer(socket, interval=1500, singleShot=True)
            timer.timeout.connect(socket.abort)
            timer.start()
            self._read_island_command(socket)

    def _read_island_command(self, socket):
        if not socket.canReadLine():
            if socket.bytesAvailable() >= 256:
                socket.abort()
            return
        try:
            message = json.loads(bytes(socket.readLine(256)))
            if message.get("refresh") is True:
                self.event_service.emit_event("WindowsNotificationRefresh", "island")
            elif message.get("clear") is True and self._island_seen_toasts:
                self.event_service.emit_event("WindowsNotificationClear", "island")
            elif type(message.get("dismiss")) is int and message["dismiss"] in (self._island_seen_toasts or ()):
                self.event_service.emit_event("WindowsNotificationRemove", message["dismiss"])
        except (AttributeError, UnicodeError, ValueError):
            pass
        socket.disconnectFromServer()

    @pyqtSlot(object)
    def _forward_island_notifications(self, items):
        if not self._island_notification_bridge:
            return
        previous = self._island_seen_toasts
        self._island_seen_toasts = None if items is None else {item.id for item in items}
        rows = None if items is None else [
            {"id": item.id, "app": item.app_name[:80], "title": item.title[:220],
             "body": item.body[:900], "at": int(item.created_at.timestamp())}
            for item in items
        ]
        self._send_island_notification({"kind": "snapshot", "items": rows})
        if previous is None or items is None:
            return
        new = [item for item in items if item.id not in previous]
        if not new:
            return

        from core.widgets.services.dnd.dnd_api import DndService

        if DndService.get_status() in ("priority", "alarms"):
            return
        latest = new[0]
        self._send_island_notification({"app": latest.app_name[:64], "count": min(999, len(new)),
                                        "icon": getattr(latest, "icon", "")})

    def _send_island_notification(self, message):
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        socket = QLocalSocket(self)

        def send():
            socket.write(payload)
            socket.disconnectFromServer()

        socket.connected.connect(send)
        socket.disconnected.connect(socket.deleteLater)
        socket.errorOccurred.connect(socket.deleteLater)
        socket.connectToServer(self._island_pipe)

    def _start_island(self):
        island = Path(DEFAULT_CONFIG_DIRECTORY) / "dynamic-island" / "island.pyw"
        interpreter = Path(sys.executable).resolve().parent.parent / "python" / "pythonw.exe"
        if not (island.is_file() and interpreter.is_file()):
            return

        # The helper uses PySide6 and its own Qt plugins.
        env = os.environ.copy()
        for name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONHOME"):
            env.pop(name, None)
        try:
            self._island = subprocess.Popen([str(interpreter), str(island)], cwd=island.parent, env=env)
        except OSError:
            logging.exception("Could not start Dynamic Island")

    def _stop_island(self):
        if self._island is not None and self._island.poll() is None:
            with suppress(OSError, subprocess.TimeoutExpired):
                self._island.terminate()
                self._island.wait(timeout=1)

    def _collect_keybindings(self) -> None:
        """Collect keybindings from widget configurations used in enabled bars."""
        self._collected_keybindings.clear()
        seen_hotkeys: dict[str, str] = {}

        active_widget_names: set[str] = set()
        for bar_config in self.config.bars.values():
            if bar_config.enabled:
                widgets = bar_config.widgets
                active_widget_names.update(widgets.left + widgets.center + widgets.right)

        pending = list(active_widget_names)
        while pending:
            widget_config = self.config.widgets.get(pending.pop(), {})
            if not isinstance(widget_config, dict):
                continue
            if widget_config.get("type", "").endswith("grouper.GrouperWidget"):
                for child in widget_config.get("options", {}).get("widgets", []):
                    if child not in active_widget_names:
                        active_widget_names.add(child)
                        pending.append(child)

        for widget_name, widget_config in self.config.widgets.items():
            if widget_name not in active_widget_names or not isinstance(widget_config, dict):
                continue

            options = widget_config.get("options", {})
            keybindings = options.get("keybindings", [])

            if not keybindings:
                continue

            bindings = collect_widget_keybindings(widget_name, keybindings)

            for binding in bindings:
                # Check for conflicts
                hotkey_lower = binding.hotkey.lower()
                if hotkey_lower in seen_hotkeys:
                    existing_widget = seen_hotkeys[hotkey_lower]
                    logging.warning(
                        "Hotkey conflict: '%s' is already assigned to '%s', overriding with '%s'",
                        binding.hotkey,
                        existing_widget,
                        widget_name,
                    )
                    # Remove the old binding so the new one actually takes effect
                    self._collected_keybindings = [
                        b for b in self._collected_keybindings if b.hotkey.lower() != hotkey_lower
                    ]
                seen_hotkeys[hotkey_lower] = widget_name
                self._collected_keybindings.append(binding)

    def _start_hotkey_listener(self) -> None:
        """Start the hotkey listener if keybindings are configured."""
        if not self._collected_keybindings:
            return

        self._hotkey_dispatcher = HotkeyDispatcher()
        self._hotkey_listener = HotkeyListener(
            self._collected_keybindings,
            self._hotkey_dispatcher,
            self._initialized_screens,
        )
        self._hotkey_listener.start()
        logging.info("Starting HotkeyListener...")

    def create_bar(self, config: BarConfig, name: str, screen: QScreen, init: bool = False) -> None:
        screen_name = screen.name().replace("\\", "").replace(".", "")
        bar_id = f"{name}_{screen_name}_{str(uuid.uuid4())[:8]}"
        bar_widgets, widget_event_listeners = self._widget_builder.build_widgets(config.widgets.model_dump())

        # Set screen_name on all widgets and disable duplicate hotkey handlers
        widgets_with_keybindings = {
            name
            for name, cfg in self.config.widgets.items()
            if isinstance(cfg, dict) and cfg.get("options", {}).get("keybindings")
        }
        for widget_list in bar_widgets.values():
            for widget in widget_list:
                widget.screen_name = screen.name()
                if widget.widget_name in widgets_with_keybindings:
                    key = (widget.widget_name, screen.name())
                    if key in self._registered_hotkey_widgets:
                        widget.hotkey_enabled = False
                        logging.info(
                            "%s on screen %s already has hotkey handler registered from another bar.",
                            widget.widget_name,
                            screen.name(),
                        )
                    else:
                        self._registered_hotkey_widgets.add(key)

        self.widget_event_listeners = self.widget_event_listeners.union(widget_event_listeners)
        self.bars.append(
            Bar(
                bar_id=bar_id,
                bar_name=name,
                bar_screen=screen,
                stylesheet=self.stylesheet,
                widgets=bar_widgets,
                config=config,
                init=init,
            )
        )
