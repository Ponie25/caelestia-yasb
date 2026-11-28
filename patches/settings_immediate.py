"""Apply ordinary Settings immediately, leaving config/editor drafts manual.

Use before SettingsDraftMixin in the dialog's MRO. Install after draft tracking.
Wrap programmatic loads with _immediate_begin_loading/_immediate_end_loading;
pass imported_preferences=True when a valid raw JSON draft is consumed. Call
_immediate_saved(snapshot) after the existing manual transaction succeeds.
"""
from copy import deepcopy
import json
import logging

from PyQt6.QtCore import QTimer
from core.utils.bar_preferences import atomic_write, create_snapshot, validate_preferences


class ImmediateSettingsMixin:
    def _install_immediate_settings(self):
        self._immediate_ready = False
        self._immediate_busy = False
        self._immediate_loading = 0
        self._advanced_preferences_pending = False
        self._immediate_pending = False
        self._immediate_session_snapshot = None
        self._immediate_own_error = None
        self._immediate_timer = QTimer(self)
        self._immediate_timer.setSingleShot(True)
        self._immediate_timer.setInterval(250)
        self._immediate_timer.timeout.connect(self._flush_immediate_preferences)
        self._immediate_theme_baseline = self._immediate_read('theme.json')
        saved = json.loads(self._draft_saved_signature)
        self._immediate_saved_preferences = deepcopy(saved[1])
        self._immediate_saved_theme = saved[0]

        def connect(signal):
            if signal is not None:
                signal.connect(self._queue_immediate_preferences)

        for control, kind in self.controls.values():
            if kind == 'bool':connect(control.toggled)
            elif kind == 'choice':connect(control.currentIndexChanged)
            elif kind == 'color':connect(control.changed)
            elif kind == 'text':connect(control.editingFinished)
            elif kind == 'font':
                connect(control.activated)
                if control.lineEdit() is not None:
                    connect(control.lineEdit().editingFinished)
            else:connect(control.valueChanged)
            slider = getattr(control, 'slider', None)
            if slider is not None:
                slider.sliderReleased.connect(self._flush_immediate_preferences)
        self.custom_accent.toggled.connect(self._queue_immediate_preferences)
        self.accent.changed.connect(self._queue_immediate_preferences)
        for button in getattr(self, 'theme_buttons', {}).values():
            button.clicked.connect(self._queue_immediate_preferences)
        self.nav.currentRowChanged.connect(self._immediate_navigation)
        self._immediate_ready = True
        self._refresh_draft_state()
        from core.utils.settings_experience import install_settings_experience

        install_settings_experience(self)

    def _refresh_draft_state(self,preserve_status=False):
        super()._refresh_draft_state(preserve_status=preserve_status)
        if not hasattr(self,'manual_actions') or not getattr(self,'_draft_tracking_ready',False):return
        try:
            current=json.loads(self._draft_signature());saved=json.loads(self._draft_saved_signature)
            manual=current[2:]!=saved[2:] or (self.raw_preferences.document().isModified() or getattr(self,'_advanced_preferences_pending',False)) and current[1]!=saved[1]
        except (ValueError,TypeError):manual=True
        self.manual_actions.setVisible(manual)
        self.apply_button.setEnabled(manual and not self._committing)
        self.revert_button.setEnabled(manual and not self._committing)
        self.cancel_button.setText('Đóng')
        error=self.status.text().startswith('Chưa lưu:')
        if hasattr(self,'command_bar'):
            self.command_bar.setVisible(manual or error)
            self.cancel_button.hide()
            self.manual_actions.setVisible(manual or error)
            self.revert_button.setText('Tải lại' if error and not manual else 'Hoàn tác')
            self.revert_button.setEnabled((manual or error) and not self._committing)
            self.apply_button.setVisible(manual)
        if not preserve_status and not self.status.text().startswith(('Chưa lưu:','Đã')):
            self.status.setText('Các thay đổi nâng cao cần bấm Áp dụng.' if manual else 'Đang áp dụng…' if getattr(self,'_immediate_pending',False) else 'Các cài đặt được lưu và áp dụng tự động.')

    def _immediate_read(self, name):
        path = self.root / name
        return path.read_bytes() if path.exists() else None

    def _queue_dirty(self, *_):
        super()._queue_dirty()
        self._queue_immediate_preferences()

    def _queue_immediate_preferences(self, *_):
        if not getattr(self, '_immediate_ready', False):return
        if self._immediate_busy or self._immediate_loading or self._committing:return
        if getattr(self, '_active_page', self.nav.currentRow()) == 7:return
        self._immediate_pending = True
        self._immediate_timer.start()

    def _immediate_begin_loading(self):
        if not getattr(self, '_immediate_ready', False):return
        self._immediate_loading += 1
        self._immediate_timer.stop()

    def _immediate_end_loading(self, imported_preferences=False):
        if not getattr(self, '_immediate_ready', False):return
        self._immediate_loading = max(0, self._immediate_loading - 1)
        if imported_preferences:
            self._advanced_preferences_pending = self._collect_preferences()!=self._immediate_saved_preferences
            self._immediate_pending = False
            self._immediate_timer.stop()

    def _immediate_navigation(self, index):
        if index == 7 and self._immediate_pending:
            # A user can enter Advanced before the 250 ms edit debounce expires.
            # Persist only the pre-existing ordinary controls, never raw text.
            self._flush_immediate_preferences(allow_advanced=True)

    def _immediate_rebase_preferences(self, preferences, theme):
        saved = json.loads(self._draft_saved_signature)
        if not isinstance(saved, list) or len(saved) != 4:
            raise ValueError('Không đọc được trạng thái thay đổi của Settings.')
        saved[0] = theme
        saved[1] = deepcopy(preferences)
        self._draft_saved_signature = self._draft_json(saved)
        # Config and CSS entries deliberately keep their original baselines.
        self._disk_baseline['bar-settings.json'] = self._immediate_read('bar-settings.json')
        self._immediate_theme_baseline = self._immediate_read('theme.json')

        self._immediate_saved_preferences = deepcopy(preferences)
        self._immediate_saved_theme = theme

    def _immediate_report_error(self, error):
        self._error(str(error))
        self._immediate_own_error = self.status.text()
        self._refresh_draft_state(preserve_status=True)

    def _immediate_rollback(self, previous, previous_theme, desired_theme):
        def restore_files():
            for name, data in previous.items():
                path = self.root / name
                if data is None:path.unlink(missing_ok=True)
                else:atomic_write(path, data)
        restore_files()
        try:
            self.controller.select(previous_theme)
        except Exception:
            logging.warning('Could not fully reapply the previous Settings theme', exc_info=True)
        # select() can recompose CSS. Preserve exact pre-transaction file bytes,
        # then refresh native appearance from those restored files.
        restore_files()
        self.controller.current = previous_theme
        self.selected_theme = desired_theme
        buttons = getattr(self, 'theme_buttons', {})
        if desired_theme in buttons:buttons[desired_theme].setChecked(True)
        for callback in (
            getattr(self.controller.manager, 'on_styles_modified', None),
            getattr(self.controller, '_apply_integrations', None),
            lambda: self.controller._send_island(previous_theme),
            self.controller.reload_preferences,
        ):
            if callback is not None:
                try:callback()
                except Exception:logging.warning('Settings rollback refresh failed', exc_info=True)

    def _flush_immediate_preferences(self, *_, allow_advanced=False):
        if not getattr(self, '_immediate_ready', False):return True
        self._immediate_timer.stop()
        if self._immediate_busy or self._immediate_loading or self._committing:return False
        if self.nav.currentRow() == 7 and not allow_advanced:return False
        if any(getattr(control, 'slider', None) is not None and control.slider.isSliderDown()
               for control, _kind in self.controls.values()):
            # Release commits the final slider value. Do not poll during a drag.
            return False
        try:
            preferences = validate_preferences(self._collect_preferences())
            theme = self.selected_theme
            if preferences == self._immediate_saved_preferences and theme == self._immediate_saved_theme:
                self._immediate_pending = False
                return True
            if self._disk_state() != self._disk_baseline or self._immediate_read('theme.json') != self._immediate_theme_baseline:
                raise ValueError('Cấu hình đã được thay đổi bên ngoài Settings. Mở lại cửa sổ để tải bản mới; thay đổi bên ngoài chưa bị ghi đè.')
            # Check that preference-only rebasing is possible before touching files.
            saved = json.loads(self._draft_saved_signature)
            if not isinstance(saved, list) or len(saved) != 4:
                raise ValueError('Không đọc được trạng thái thay đổi của Settings.')
            previous = {name:self._immediate_read(name) for name in
                        ('bar-settings.json', 'styles.css', 'theme.json')}
            previous_theme = self.controller.current
            prior_status = self.status.text()
            self._immediate_busy = True
            if self._immediate_session_snapshot is None:
                self._immediate_session_snapshot = create_snapshot(self.root, 'Trước phiên tùy chỉnh Settings')
            try:
                atomic_write(self.root/'bar-settings.json', json.dumps(preferences, ensure_ascii=False, indent=2)+'\n')
                if not self.controller.select(theme):raise RuntimeError('Không áp dụng được tùy chọn. Cấu hình cũ đã được khôi phục.')
                self.controller.reload_preferences()
            except Exception as original:
                failed = self._immediate_rollback(previous, previous_theme, theme)
                if failed:
                    raise RuntimeError('Không khôi phục hoàn toàn cấu hình cũ (' + ', '.join(failed) + ').') from original
                raise
            self.preferences = deepcopy(preferences)
            try:
                self._immediate_rebase_preferences(preferences, theme)
            except Exception:
                logging.error('Settings baseline refresh after a committed save failed', exc_info=True)
                self.status.setText('Đã lưu. Mở lại Settings để tải trạng thái vừa lưu.')
                return True
            self._immediate_pending = False
            try:
                if not self.raw_preferences.document().isModified():
                    self.raw_preferences.setPlainText(json.dumps(preferences, ensure_ascii=False, indent=2))
                    self.raw_preferences.document().setModified(False)
                self._refresh_draft_state(preserve_status=True)
                code_error = prior_status.removeprefix('Đã lưu tùy chọn. Mã còn lỗi. ')
                if self._draft_dirty and code_error.startswith('Chưa lưu: Nội dung chưa hợp lệ'):
                    self.status.setText('Đã lưu tùy chọn. Mã còn lỗi. ' + code_error)
                elif not prior_status.startswith('Chưa lưu:') or prior_status == self._immediate_own_error:
                    self.status.setToolTip('')
                    self.status.setText('Đã lưu. Phần chỉnh bằng mã vẫn đang chờ.' if self._draft_dirty
                                        else 'Đã lưu và áp dụng.')
                self._immediate_own_error = None
                self._refresh_material_status()
                self._refresh_backups()
                self._refresh_draft_state(preserve_status=True)
            except Exception:
                logging.warning('Settings feedback after a committed save failed', exc_info=True)
            return True
        except Exception as error:
            self._immediate_report_error(error)
            return False
        finally:
            self._immediate_busy = False

    def _immediate_saved(self, snapshot=None):
        """Call after a successful existing manual Apply transaction."""
        if not getattr(self, '_immediate_ready', False):return
        self._immediate_timer.stop()
        self._advanced_preferences_pending = False
        self._immediate_pending = False
        self._immediate_own_error = None
        if snapshot is not None and self._immediate_session_snapshot is None:
            self._immediate_session_snapshot = snapshot
        self._immediate_saved_preferences = validate_preferences(json.loads(
            (self.root/'bar-settings.json').read_text(encoding='utf-8')))
        self._immediate_saved_theme = self.controller.current
        self._immediate_theme_baseline = self._immediate_read('theme.json')
        self._refresh_draft_state(preserve_status=True)

    def _request_close(self):
        self._flush_immediate_preferences()
        experience = getattr(self, '_settings_experience', None)
        if experience is not None:
            experience.flush_draft()
            if self._committing:
                # The structural update is already scheduled. Close without reopening Settings.
                for name in ('reopen-bar-settings.json', 'settings-window-reopen.json'):
                    try:
                        (self.root / name).unlink(missing_ok=True)
                    except OSError:
                        logging.debug('Could not remove Settings reopen state', exc_info=True)
        return super()._request_close()

    def reject(self):
        self._flush_immediate_preferences()
        super().reject()

    def revert_changes(self):
        self._flush_immediate_preferences()
        return super().revert_changes()
