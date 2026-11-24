"""Event-driven draft state and explicit dismissal for native Bar Settings.

The mixin deliberately does not own persistence. ``apply_changes`` remains the
existing validated, backed-up transaction; call ``_mark_saved`` after it succeeds.
"""
from copy import deepcopy
import json
import logging

import yaml
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox


class SettingsDraftMixin:
    def _install_draft_tracking(self):
        """Call once after the complete form and footer have been constructed."""
        self._draft_tracking_ready = False
        self._draft_error_reedited = False
        self._draft_config_signatures = {}
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(100)
        self._draft_timer.timeout.connect(self._refresh_draft_state)

        def connect(signal):
            if signal is not None:
                signal.connect(self._queue_draft_check)

        for control, kind in self.controls.values():
            if kind == 'bool':
                connect(control.toggled)
            elif kind == 'choice':
                connect(control.currentIndexChanged)
            elif kind == 'font':
                connect(control.currentFontChanged)
                if control.lineEdit() is not None:
                    connect(control.lineEdit().textEdited)
            elif kind == 'color':
                connect(control.changed)
            elif kind == 'text':
                connect(control.textChanged)
            else:
                connect(control.valueChanged)

        for name, signal_name in (
            ('custom_accent', 'toggled'), ('accent', 'changed'),
            ('position', 'currentIndexChanged'), ('bar_height', 'valueChanged'),
            ('bar_width', 'textChanged'), ('always_top', 'toggled'),
            ('reserve', 'toggled'), ('autohide', 'toggled'),
            ('fullscreen', 'toggled'), ('widget_type', 'textChanged'),
            ('bar_selector', 'currentIndexChanged'),
            ('widget_selector', 'currentIndexChanged'),
        ):
            control = getattr(self, name, None)
            if control is not None:
                connect(getattr(control, signal_name, None))
        for control in self.outer_padding.values():
            connect(control.valueChanged)
        for button in self.theme_buttons.values():
            connect(button.toggled)
        connect(self.options_tree.itemChanged)
        for items in self.region_lists.values():
            model = items.model()
            for name in ('rowsInserted', 'rowsRemoved', 'rowsMoved',
                         'modelReset', 'layoutChanged', 'dataChanged'):
                connect(getattr(model, name, None))
        for name in ('raw_yaml', 'raw_preferences', 'custom_css'):
            editor = getattr(self, name)
            connect(editor.textChanged)
            connect(editor.document().modificationChanged)

        self._draft_saved_signature = self._draft_signature()
        self._draft_dirty = False
        self._draft_tracking_ready = True
        self._refresh_draft_state()

    def _queue_draft_check(self, *_):
        if not getattr(self, '_draft_tracking_ready', False):
            return
        if self.status.text().startswith('Chưa lưu:'):
            self._draft_error_reedited = True
        self._draft_timer.start()

    def _queue_dirty(self, *_):
        """Preview code can request a check even before tracking is installed."""
        self._queue_draft_check()

    @staticmethod
    def _draft_json(value):
        try:
            return json.dumps(value, sort_keys=True, ensure_ascii=False,
                              separators=(',', ':'), default=repr)
        except (TypeError, ValueError, RecursionError):
            # An invalid raw YAML document can contain mixed key types or a
            # recursive alias. It is still an unsaved draft, not a timer error.
            return repr(value)

    def _draft_widget_editor(self):
        """Retain malformed option text when committing a tree would fail."""
        def walk(item):
            return (item.text(0), item.text(1), item.checkState(1).value,
                    tuple(walk(item.child(i)) for i in range(item.childCount())))
        return (self.widget_name, self.widget_type.text(),
                walk(self.options_tree.invisibleRootItem()))

    def _draft_layout_editor(self):
        return {
            'bar': self.bar_name, 'position': self.position.currentData(),
            'height': self.bar_height.value(), 'width': self.bar_width.text(),
            'flags': [control.isChecked() for control in
                      (self.always_top, self.reserve, self.autohide, self.fullscreen)],
            'padding': {key: control.value() for key, control in self.outer_padding.items()},
            'regions': {key: items.names() for key, items in self.region_lists.items()},
        }

    def _draft_signature(self):
        """Compare effective edits without modifying the dialog's real draft.

        Valid raw documents are canonicalized so visiting Advanced or changing
        indentation alone does not create a false unsaved state. Invalid editor
        text stays in the signature and therefore cannot silently look saved.
        """
        original = self.draft
        try:
            self.draft = deepcopy(original)
            self._save_bar_fields()
            self._commit_widget()
            config = self.draft
        except (ValueError, TypeError, KeyError, AttributeError):
            config = {'uncommitted': deepcopy(original),
                      'layout_editor': self._draft_layout_editor(),
                      'widget_editor': self._draft_widget_editor()}
        finally:
            self.draft = original

        if self.raw_yaml.document().isModified():
            try:
                config = yaml.safe_load(self.raw_yaml.toPlainText())
            except (ValueError, yaml.YAMLError):
                config = {'invalid_yaml': self.raw_yaml.toPlainText()}
        key = self._draft_json(config)
        cache = self._draft_config_signatures
        if key in cache:
            config = cache[key]
        else:
            try:
                from core.validation.config import YasbConfig
                config = YasbConfig.model_validate(deepcopy(config)).model_dump(
                    mode='json', exclude={'watch_config', 'watch_stylesheet'})
            except (ValueError, TypeError, KeyError, AttributeError):
                pass
            # Most edits affect preferences, not YAML. Avoid repeatedly parsing
            # the same config or repeating its old deprecation warnings.
            if len(cache) >= 8:
                cache.pop(next(iter(cache)))
            cache[key] = config

        preferences = self._collect_preferences()
        if self.raw_preferences.document().isModified():
            try:
                preferences = json.loads(self.raw_preferences.toPlainText())
            except (ValueError, TypeError):
                preferences = {'invalid_json': self.raw_preferences.toPlainText()}
        try:
            from core.utils.bar_preferences import validate_preferences
            preferences = validate_preferences(preferences)
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
        return self._draft_json((self.selected_theme, preferences, config,
                                 self.custom_css.toPlainText()))

    def _refresh_draft_state(self, preserve_status=False):
        if not getattr(self, '_draft_tracking_ready', False):
            return
        self._draft_timer.stop()
        self._draft_dirty = self._draft_signature() != self._draft_saved_signature
        committing = bool(getattr(self, '_committing', False))
        self.apply_button.setEnabled(self._draft_dirty and not committing)
        self.revert_button.setEnabled(self._draft_dirty and not committing)
        self.cancel_button.setText('Hủy thay đổi' if self._draft_dirty else 'Đóng')
        badge = getattr(self, 'unsaved_badge', None)
        if badge is not None:
            badge.setVisible(self._draft_dirty)
        if not preserve_status:
            text = self.status.text()
            keep_error = text.startswith('Chưa lưu:') and not self._draft_error_reedited
            keep_saved = text.startswith('Đã lưu') and not self._draft_dirty
            if not committing and not keep_error and not keep_saved:
                self.status.setToolTip('')
                self.status.setText('Có thay đổi chưa lưu.' if self._draft_dirty
                                    else 'Không có thay đổi chưa lưu.')
        self._draft_error_reedited = False

    def _mark_saved(self):
        if not getattr(self, '_draft_tracking_ready', False):
            return
        self._draft_timer.stop()
        self._draft_saved_signature = self._draft_signature()
        self._draft_error_reedited = False
        self.status.setToolTip('')
        self._refresh_draft_state(preserve_status=True)

    def _confirm_unsaved_close(self):
        box = QMessageBox(self)
        box.setWindowTitle('Thay đổi chưa lưu')
        box.setIcon(QMessageBox.Icon.Question)
        box.setText('Lưu thay đổi trước khi đóng Settings?')
        box.setInformativeText('Chọn Bỏ thay đổi để giữ cấu hình đang được áp dụng.')
        save = box.addButton('Lưu và đóng', QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton('Bỏ thay đổi', QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton('Quay lại', QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.setEscapeButton(cancel)
        palette = getattr(self, '_surface_palette', {})
        if palette:
            box.setStyleSheet(
                'QMessageBox{background:%s;color:%s;}'
                'QMessageBox QLabel{color:%s;}'
                'QMessageBox QPushButton{background:%s;color:%s;padding:8px 14px;'
                'border:1px solid %s;border-radius:6px;}'
                'QMessageBox QPushButton:focus{border-color:%s;}' %
                (palette.get('MANTLE', palette['BASE']), palette['TEXT'],
                 palette['TEXT'], palette['SURFACE'], palette['TEXT'],
                 palette['SURFACE2'], palette['MAUVE']))
        box.exec()
        clicked = box.clickedButton()
        return 'save' if clicked is save else 'discard' if clicked is discard else 'cancel'

    def _request_close(self):
        self._refresh_draft_state(preserve_status=True)
        if not getattr(self, '_draft_dirty', False):
            self.reject()
            return True
        choice = self._confirm_unsaved_close()
        if choice == 'cancel':
            return False
        if choice == 'save':
            self.apply_changes()
            self._refresh_draft_state(preserve_status=True)
            if self._draft_dirty:
                return False
            # A structural save may already have queued a native bar reload.
            # The user explicitly chose to close, so suppress only its reopen
            # marker; the actual queued reload still runs normally.
            if getattr(self, '_committing', False):
                try:
                    (self.root / 'reopen-bar-settings.json').unlink(missing_ok=True)
                except OSError:
                    logging.debug('Could not remove closed Settings reopen marker', exc_info=True)
        self.reject()
        return True

    def revert_changes(self):
        """Discard this draft and reopen the latest disk state in place."""
        geometry = self.geometry()
        page = self.nav.currentRow()
        controller = self.controller
        managed = getattr(controller, 'settings_dialog', None)
        if managed is not None and managed is not self:
            managed.reject()
        controller.settings_dialog = None
        fresh = controller.show_settings(page=page)
        fresh.setGeometry(geometry)
        self.reject()
        return fresh
