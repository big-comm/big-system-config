import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
import html
import logging
import os
import subprocess
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from gi.repository import Adw, Gio, GLib, Gtk
from typing import Any, Optional, Union

from config import _, ICONS_DIR, ngettext

logger = logging.getLogger("biglinux-settings")

UNDO_DELAY_MS = 1200


def _plain_markup(text: str) -> str:
    """Escape plain translated text before sending it to markup-aware widgets."""
    return html.escape(html.unescape(text or ""), quote=False)


class BaseSettingsPage(Adw.Bin):
    def __init__(self, main_window: Adw.ApplicationWindow, **kwargs) -> None:
        super().__init__(**kwargs)
        self.main_window = main_window

        # Dictionaries to map UI widgets to their corresponding shell scripts
        self.switch_scripts = {}
        self.status_indicators = {}
        # Mapping: parent_switch -> list of child row widgets
        self.sub_switches = {}
        # Mapping from script path to timeout value (seconds). If None, default 90.
        self.switch_timeouts: dict[str, Optional[int]] = {}
        # Centralized widget metadata — avoids monkey-patching GObject instances
        self._widget_data: dict = {}
        self._sync_generation = 0
        # Switches whose toggle script is still running
        self._busy_switches: set = set()

    def _set_wd(self, widget: Gtk.Widget, key: str, value: Any) -> None:
        """Set a metadata attribute on a widget via centralized dict."""
        self._widget_data.setdefault(widget, {})[key] = value

    def _get_wd(self, widget: Gtk.Widget, key: str, default: Any = None) -> Any:
        """Get a metadata attribute from a widget via centralized dict."""
        return self._widget_data.get(widget, {}).get(key, default)

    def _get_switch_handler(self, switch: Gtk.Switch):
        """Return the active state-set handler for a switch (dangerous or normal)."""
        dangerous = self._get_wd(switch, "dangerous_handler")
        return dangerous if dangerous else self.on_switch_changed

    def _show_info_dialog(self, title: str, info_text: str) -> None:
        """Show info text in an accessible dialog instead of tooltip."""
        dialog = Adw.AlertDialog(
            heading=title,
            body=info_text,
        )
        dialog.add_response("close", _("Close"))
        dialog.set_default_response("close")
        dialog.present(self.main_window)

    def _confirm_dangerous_action(
        self, switch: Gtk.Switch, state: bool, title: str, warning_message: str
    ) -> bool:
        """Show confirmation dialog before executing a dangerous action.
        If confirmed, proceeds with normal on_switch_changed. If cancelled, reverts switch."""
        self.main_window._cancel_pending_undo(revert=True)
        self.main_window._cancel_banner_timeout()

        if not state:
            # Disabling a dangerous feature is always safe — no confirmation needed
            self._execute_toggle(switch, state)
            return True

        dialog = Adw.AlertDialog(
            heading=_("Warning: {}").format(title),
            body=warning_message,
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("confirm", _("Continue"))
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(dlg, response):
            if response == "confirm":
                self._execute_toggle(switch, state)
            else:
                self._set_switch_active_without_handler(switch, not state)

        dialog.connect("response", on_response)
        dialog.present(self.main_window)
        return True

    def create_dangerous_row(
        self,
        parent_group: Adw.PreferencesGroup,
        title: str,
        subtitle_with_markup: str,
        script_name: str,
        icon_name: str,
        warning_message: str,
        **kwargs: Any,
    ) -> Gtk.Switch:
        """Creates a row that requires confirmation before enabling.
        Uses create_row internally but intercepts the switch signal."""
        switch = self.create_row(
            parent_group, title, subtitle_with_markup, script_name, icon_name, **kwargs
        )

        # Disconnect the normal handler and connect through confirmation
        switch.disconnect_by_func(self.on_switch_changed)

        def _on_dangerous_switch(sw, state):
            return self._confirm_dangerous_action(sw, state, title, warning_message)

        self._set_wd(switch, "dangerous_handler", _on_dangerous_switch)
        switch.connect("state-set", _on_dangerous_switch)
        return switch

    _cached_local_ip = None

    @classmethod
    def get_local_ip(cls) -> str:
        if cls._cached_local_ip is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            try:
                s.connect(("10.255.255.255", 1))
                cls._cached_local_ip = s.getsockname()[0]
            except OSError:
                cls._cached_local_ip = "127.0.0.1"
            finally:
                s.close()
        return cls._cached_local_ip

    def create_scrolled_content(self) -> Gtk.Box:
        """Cria a estrutura básica de scroll e box vertical."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.content_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=20,
            margin_top=20,
            margin_bottom=20,
            margin_start=20,
            margin_end=20,
        )
        scrolled.set_child(self.content_box)
        self.set_child(scrolled)
        return self.content_box

    def set_search_mode(self, _enabled: bool) -> None:
        """Placeholder method for search mode compatibility."""
        pass

    def create_group(
        self, title: str, description: str, script_group: str
    ) -> Adw.PreferencesGroup:
        """Cria um PreferencesGroup com o botão de reload automático."""
        group = Adw.PreferencesGroup()
        group.set_title(_plain_markup(title))
        group.set_description(_plain_markup(description))
        group.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [title],
        )
        self._set_wd(group, "script_group", script_group)
        return group

    def create_expander_row(
        self,
        parent_group: Adw.PreferencesGroup,
        title: str,
        subtitle: str,
        icon_name: str,
    ) -> Adw.ExpanderRow:
        """Creates a collapsible ExpanderRow inside a PreferencesGroup.
        Child rows can be added via create_row/create_sub_row passing the expander as parent."""
        expander = Adw.ExpanderRow(title=_plain_markup(title))
        if subtitle:
            expander.set_subtitle(_plain_markup(subtitle))

        icon_path = os.path.join(ICONS_DIR, f"{icon_name}.svg")
        gfile = Gio.File.new_for_path(icon_path)
        icon = Gio.FileIcon.new(gfile)
        img = Gtk.Image.new_from_gicon(icon)
        img.set_pixel_size(24)
        img.add_css_class("symbolic-icon")
        expander.add_prefix(img)

        expander.update_property([Gtk.AccessibleProperty.LABEL], [title])
        # Inherit script_group from parent group
        script_group = self._get_wd(parent_group, "script_group", "default")
        self._set_wd(expander, "script_group", script_group)
        parent_group.add(expander)
        return expander

    def create_action_row(
        self,
        parent_group: Union[Adw.PreferencesGroup, Adw.ExpanderRow],
        title: str,
        subtitle: str,
        script_name: str,
        icon_name: str,
        action_label: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Adw.ActionRow:
        """Builds an ActionRow with a single action button suffix.
        The button invokes the script with argument 'run' (one-shot, not toggle)."""
        row = Adw.ActionRow(title=_plain_markup(title))
        if subtitle:
            row.set_subtitle(_plain_markup(subtitle))

        icon_path = os.path.join(ICONS_DIR, f"{icon_name}.svg")
        gfile = Gio.File.new_for_path(icon_path)
        icon = Gio.FileIcon.new(gfile)
        img = Gtk.Image.new_from_gicon(icon)
        img.set_pixel_size(24)
        img.add_css_class("symbolic-icon")
        row.add_prefix(img)

        button = Gtk.Button(
            label=action_label or _("Run"),
            valign=Gtk.Align.CENTER,
        )
        button.add_css_class("suggested-action")
        button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("{}: run action").format(title)],
        )
        row.add_suffix(button)
        row.set_activatable_widget(button)

        script_group = self._get_wd(parent_group, "script_group", "default")
        script_path = os.path.join(script_group, f"{script_name}.sh")

        button.connect(
            "clicked",
            lambda btn: self._execute_action(btn, row, script_path, timeout),
        )

        if isinstance(parent_group, Adw.ExpanderRow):
            parent_group.add_row(row)
        else:
            parent_group.add(row)
        return row

    def _execute_action(
        self,
        button: Gtk.Button,
        row: Adw.ActionRow,
        script_path: str,
        timeout: Optional[int],
    ) -> None:
        """Execute a one-shot action script in a background thread."""
        if not os.path.exists(script_path):
            logger.warning(_("Script not found: {}").format(script_path))
            self.main_window.show_toast(
                _("Script not found: {}").format(os.path.basename(script_path))
            )
            return

        original_label = button.get_label()
        original_subtitle = row.get_subtitle() or ""
        spinner = Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER)
        button.set_sensitive(False)
        row.add_suffix(spinner)
        row.set_subtitle(_("Applying…"))

        def _run_in_thread():
            success = False
            try:
                result = subprocess.run(
                    [script_path, "run"],
                    capture_output=True,
                    text=True,
                    timeout=timeout or 600,
                )
                success = result.returncode == 0
                if not success:
                    logger.error(
                        _("Action script {} failed: {}").format(
                            script_path, result.stderr.strip()
                        )
                    )
            except subprocess.TimeoutExpired:
                logger.error(_("Action script timeout: {}").format(script_path))
            except OSError as e:
                logger.error(
                    _("Error running action script {}: {}").format(script_path, e)
                )
            GLib.idle_add(_on_done, success)

        def _on_done(success: bool) -> bool:
            row.remove(spinner)
            button.set_sensitive(True)
            button.set_label(original_label)
            row.set_subtitle(original_subtitle)
            if success:
                self.main_window.show_toast(_("Action completed successfully"))
            else:
                self.main_window.show_toast(
                    _("Action failed: {}").format(os.path.basename(script_path))
                )
            return False

        threading.Thread(target=_run_in_thread, daemon=True).start()

    def create_row(
        self,
        parent_group: Union[Adw.PreferencesGroup, Adw.ExpanderRow],
        title: str,
        subtitle_with_markup: str,
        script_name: str,
        icon_name: str,
        info_text: Optional[str] = None,
        timeout: Optional[int] = None,
        link_url: Optional[str] = None,
        recommended: bool = False,
    ) -> Gtk.Switch:
        """Builds an ActionRow with icon prefix and switch suffix."""
        row = Adw.ActionRow(title=_plain_markup(title))
        if subtitle_with_markup:
            row.set_subtitle(_plain_markup(subtitle_with_markup))

        # Icon prefix
        icon_path = os.path.join(ICONS_DIR, f"{icon_name}.svg")
        gfile = Gio.File.new_for_path(icon_path)
        icon = Gio.FileIcon.new(gfile)
        img = Gtk.Image.new_from_gicon(icon)
        img.set_pixel_size(24)
        img.add_css_class("symbolic-icon")
        row.add_prefix(img)

        if recommended:
            badge = Gtk.Label(label=_("Recommended"), valign=Gtk.Align.CENTER)
            badge.add_css_class("recommended-badge")
            row.add_suffix(badge)

        # Switch suffix
        switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        # Accessible name for Orca screen reader
        switch.update_property([Gtk.AccessibleProperty.LABEL], [title])
        if subtitle_with_markup:
            switch.update_property(
                [Gtk.AccessibleProperty.DESCRIPTION], [subtitle_with_markup]
            )

        if info_text:
            info_btn = Gtk.Button(
                valign=Gtk.Align.CENTER,
                icon_name="dialog-information-symbolic",
            )
            info_btn.add_css_class("flat")
            info_btn.add_css_class("circular")
            info_btn.set_tooltip_text(info_text)
            info_btn.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [_("{}: additional information").format(title)],
            )
            info_btn.set_visible(False)
            info_btn.connect(
                "clicked",
                lambda btn, t=title, txt=info_text: self._show_info_dialog(t, txt),
            )
            self._set_wd(switch, "info_icon", info_btn)
            row.add_suffix(info_btn)

        if link_url:
            link_btn = Gtk.LinkButton(
                uri=link_url,
                label=_("Learn more"),
                valign=Gtk.Align.CENTER,
            )
            link_btn.add_css_class("flat")
            link_btn.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [_("{}: learn more").format(title)],
            )
            row.add_suffix(link_btn)

        row.add_suffix(switch)
        row.set_activatable_widget(switch)

        # Store row reference via centralized dict
        self._set_wd(switch, "row", row)

        # Associate the script with the switch
        script_group = self._get_wd(parent_group, "script_group", "default")
        script_path = os.path.join(script_group, f"{script_name}.sh")
        self.switch_scripts[switch] = script_path
        self.switch_timeouts[script_path] = timeout
        switch.connect("state-set", self.on_switch_changed)

        if isinstance(parent_group, Adw.ExpanderRow):
            parent_group.add_row(row)
        else:
            parent_group.add(row)
        return switch

    def create_sub_row(
        self,
        parent_group: Union[Adw.PreferencesGroup, Adw.ExpanderRow],
        title: str,
        subtitle_with_markup: str,
        script_name: str,
        icon_name: str,
        parent_switch: Gtk.Switch,
        info_text: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Gtk.Switch:
        """Builds an indented ActionRow as a child option of a parent switch."""
        row = Adw.ActionRow(title=_plain_markup(title))
        self._set_wd(row, "is_sub_row", True)
        if subtitle_with_markup:
            row.set_subtitle(_plain_markup(subtitle_with_markup))

        # Icon prefix with extra indentation for sub-row
        icon_path = os.path.join(ICONS_DIR, f"{icon_name}.svg")
        gfile = Gio.File.new_for_path(icon_path)
        icon = Gio.FileIcon.new(gfile)
        img = Gtk.Image.new_from_gicon(icon)
        img.set_pixel_size(24)
        img.set_margin_start(26)
        img.add_css_class("symbolic-icon")
        row.add_prefix(img)

        # Switch suffix
        switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        # Accessible name for Orca screen reader
        switch.update_property([Gtk.AccessibleProperty.LABEL], [title])
        if subtitle_with_markup:
            switch.update_property(
                [Gtk.AccessibleProperty.DESCRIPTION], [subtitle_with_markup]
            )

        if info_text:
            info_btn = Gtk.Button(
                valign=Gtk.Align.CENTER,
                icon_name="dialog-information-symbolic",
            )
            info_btn.add_css_class("flat")
            info_btn.add_css_class("circular")
            info_btn.set_tooltip_text(info_text)
            info_btn.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [_("{}: additional information").format(title)],
            )
            info_btn.set_visible(False)
            info_btn.connect(
                "clicked",
                lambda btn, t=title, txt=info_text: self._show_info_dialog(t, txt),
            )
            self._set_wd(switch, "info_icon", info_btn)
            row.add_suffix(info_btn)

        row.add_suffix(switch)
        row.set_activatable_widget(switch)

        # Store row reference via centralized dict
        self._set_wd(switch, "row", row)

        script_group = self._get_wd(parent_group, "script_group", "default")
        script_path = os.path.join(script_group, f"{script_name}.sh")
        self.switch_scripts[switch] = script_path
        self.switch_timeouts[script_path] = timeout
        switch.connect("state-set", self.on_switch_changed)

        if isinstance(parent_group, Adw.ExpanderRow):
            parent_group.add_row(row)
        else:
            parent_group.add(row)

        # It starts hidden
        row.set_visible(False)

        # Register the sub-switch
        self.sub_switches.setdefault(parent_switch, []).append(row)

        return switch

    def check_script_state(self, script_path: str) -> tuple[Any, str]:
        """Executes a script with the 'check' argument to get its current state.
        Returns True if the script's stdout is 'true', False otherwise."""
        if not os.path.exists(script_path):
            msg = _("Unavailable: script not found.")
            logger.warning(_("Script not found: {}").format(script_path))
            return (None, msg)

        try:
            result = subprocess.run(
                [script_path, "check"],
                capture_output=True,
                text=True,
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=10,
            )
            if result.returncode == 0:
                output = result.stdout.strip().lower()
                if output == "true":
                    return (True, _("Enabled"))
                elif output == "false":
                    return (False, _("Disabled"))
                elif output == "true_disabled":
                    # Returns a special string state and an explanatory message.
                    return (
                        "true_disabled",
                        _(
                            "Enabled by system configuration (e.g., Real-Time Kernel) and cannot be changed here."
                        ),
                    )
                elif output == "unsupported":
                    return (None, _("Unavailable in this desktop environment."))
                else:
                    msg = _("Unavailable: script returned invalid output.")
                    logger.debug(
                        _("output from script {}: {}").format(
                            script_path, result.stdout.strip()
                        )
                    )
                    return (None, msg)
            else:
                msg = _("Unavailable: script returned an error.")
                logger.error(_("Error checking state: {}").format(result.stderr))
                return (None, msg)
        except (subprocess.TimeoutExpired, OSError) as e:
            msg = _("Unavailable: failed to run script.")
            logger.error(_("Error running script {}: {}").format(script_path, e))
            return (None, msg)

    def toggle_script_state(
        self, script_path: str, new_state: bool, timeout: Optional[int] = None
    ) -> bool:
        """Executes a script with the 'toggle' argument to change the system state.
        Returns True on success, False on failure."""
        if not os.path.exists(script_path):
            # Use provided timeout or default to the script's configured timeout
            timeout = timeout if timeout is not None else 90
            error_msg = _("Script not found: {}").format(script_path)
            logger.error(error_msg)
            return False

        try:
            state_str = "true" if new_state else "false"
            result = subprocess.run(
                [script_path, "toggle", state_str],
                capture_output=True,
                text=True,
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=timeout if timeout is not None else 90,
            )

            if result.returncode == 0:
                if result.stdout.strip():
                    logger.debug(_("Script output: {}").format(result.stdout.strip()))
                for _attempt in range(5):
                    verified_state, _message = self.check_script_state(script_path)
                    if verified_state is new_state:
                        logger.info(_("State changed successfully"))
                        return True
                    time.sleep(0.2)
                logger.error(
                    "Script completed but state verification failed: %s", script_path
                )
                return False
            else:
                # Exit code != 0 indicates failure
                error_msg = _("Script failed with exit code: {}").format(
                    result.returncode
                )
                logger.error(error_msg)

                if result.stderr.strip():
                    logger.error("Script stderr: %s", result.stderr.strip())

                if result.stdout.strip():
                    logger.error("Script stdout: %s", result.stdout.strip())

                return False

        except subprocess.TimeoutExpired:
            error_msg = _("Script timeout: {}").format(script_path)
            logger.error(error_msg)
            return False
        except OSError as e:
            error_msg = _("Error running script {}: {}").format(script_path, e)
            logger.error(error_msg)
            return False

    def _toggle_info_icon_visibility(self, switch: Gtk.Switch, state: bool) -> None:
        """Handles the visibility of the info icon based on the switch state.
        The icon is only visible when the switch is active (True)."""
        info_icon = self._get_wd(switch, "info_icon")
        if info_icon:
            row = self._get_wd(switch, "row")
            is_supported = not self._get_wd(row, "hidden_no_support", False)
            info_icon.set_visible(state and is_supported)

    def _update_sub_switches_visibility(
        self, parent_switch: Gtk.Switch, state: bool
    ) -> None:
        """Update child rows visibility and parent accessible description."""
        if parent_switch not in self.sub_switches:
            return
        visible_count = 0
        for child_row in self.sub_switches[parent_switch]:
            is_supported = not self._get_wd(child_row, "hidden_no_support", False)
            child_row.set_visible(state and is_supported)
            if state and is_supported:
                visible_count += 1
        if visible_count > 0:
            parent_switch.update_property(
                [Gtk.AccessibleProperty.DESCRIPTION],
                [
                    ngettext(
                        "{} sub-option available",
                        "{} sub-options available",
                        visible_count,
                    ).format(visible_count)
                ],
            )
        else:
            parent_switch.update_property([Gtk.AccessibleProperty.DESCRIPTION], [""])

    def sync_all_switches_async(self) -> None:
        """Synchronize all switches in a background thread to avoid blocking UI."""
        self._sync_generation += 1
        generation = self._sync_generation
        switches = list(self.switch_scripts.items())
        indicators = list(self.status_indicators.items())
        script_paths = list({path for _, path in switches + indicators})

        def _check_all():
            try:
                _check_all_unsafe()
            except Exception:
                logger.exception("Failed to synchronize switches")

        def _check_all_unsafe():
            worker_count = min(8, max(1, len(script_paths)))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                states = dict(
                    zip(
                        script_paths,
                        executor.map(self.check_script_state, script_paths),
                    )
                )
            switch_results = [(switch, states[path]) for switch, path in switches]
            indicator_results = [
                (indicator, states[path]) for indicator, path in indicators
            ]
            GLib.idle_add(
                self._apply_sync_results,
                generation,
                switch_results,
                indicator_results,
            )

        threading.Thread(target=_check_all, daemon=True).start()

    def _apply_sync_results(
        self, generation: int, switch_results: list, indicator_results: list
    ) -> bool:
        """Apply sync results on the main thread (called via GLib.idle_add)."""
        if generation != self._sync_generation:
            return False
        for switch, (status, message) in switch_results:
            # A toggle is still running on this switch: its own completion
            # handler owns the row (spinner, sensitivity, final state).
            if switch in self._busy_switches:
                continue
            row = self._get_wd(switch, "row")

            handler = self._get_switch_handler(switch)
            switch.handler_block_by_func(handler)

            if status == "true_disabled" or status is None:
                row.set_visible(False)
                self._set_wd(row, "hidden_no_support", True)
                self._toggle_info_icon_visibility(switch, False)
            else:
                row.set_sensitive(True)
                if not self._get_wd(row, "is_sub_row", False):
                    row.set_visible(True)
                row.set_tooltip_text(None)
                self._set_wd(row, "hidden_no_support", False)
                self._set_switch_active_without_handler(switch, status)
                self._toggle_info_icon_visibility(switch, status)

            switch.handler_unblock_by_func(handler)

        for indicator, (status, message) in indicator_results:
            row = self._get_wd(indicator, "row")
            indicator.remove_css_class("status-on")
            indicator.remove_css_class("status-off")
            indicator.remove_css_class("status-unavailable")

            if status is None:
                row.set_visible(False)
                self._set_wd(row, "hidden_no_support", True)
            else:
                row.set_sensitive(True)
                row.set_visible(True)
                row.set_tooltip_text(None)
                self._set_wd(row, "hidden_no_support", False)
                if status:
                    indicator.add_css_class("status-on")
                else:
                    indicator.add_css_class("status-off")

        for parent_switch, child_rows in self.sub_switches.items():
            parent_state = parent_switch.get_active()
            self._update_sub_switches_visibility(parent_switch, parent_state)

        return False

    def sync_all_switches(self) -> None:
        """Alias for async version. Kept for backward compatibility."""
        self.sync_all_switches_async()

    def on_switch_changed(self, switch: Gtk.Switch, state: bool) -> bool:
        """Callback executed when a user manually toggles a switch.
        For non-dangerous switches, provides a 3-second undo window before executing."""
        script_path = self.switch_scripts.get(switch)
        if not script_path:
            return True

        self.main_window._cancel_pending_undo(revert=True)
        self.main_window._cancel_banner_timeout()

        # Dangerous switches already have confirmation — execute immediately
        if self._get_wd(switch, "dangerous_handler"):
            self._execute_toggle(switch, state)
            return True

        script_name = os.path.basename(script_path)
        action = _("on") if state else _("off")

        # Show undo banner
        self.main_window.banner.set_title(
            _("Changing {} to {}…").format(script_name.replace(".sh", ""), action)
        )
        self.main_window.banner.set_button_label(_("Undo"))
        self.main_window._banner_callback = lambda: self._undo_toggle(switch, state)
        self.main_window.banner.set_revealed(True)

        # Short undo window before applying the setting.
        timer_id = GLib.timeout_add(UNDO_DELAY_MS, self._on_undo_timeout, switch, state)
        self.main_window._pending_undo = {
            "timer_id": timer_id,
            "page": self,
            "switch": switch,
            "state": state,
        }

        return True

    def _cancel_pending_undo(self, revert: bool = False) -> None:
        """Cancel any pending undo timer."""
        self.main_window._cancel_pending_undo(revert=revert)

    def _set_switch_active_without_handler(
        self, switch: Gtk.Switch, state: bool
    ) -> None:
        handler = self._get_switch_handler(switch)
        switch.handler_block_by_func(handler)
        switch.set_active(state)
        switch.set_state(state)
        switch.handler_unblock_by_func(handler)

    def _undo_toggle(self, switch: Gtk.Switch, state: bool) -> None:
        """Undo a pending toggle — revert the switch and cancel execution."""
        self._cancel_pending_undo(revert=True)
        logger.info(_("Undo: reverted toggle"))

    def _on_undo_timeout(self, switch: Gtk.Switch, state: bool) -> bool:
        """Called after the 3-second undo window expires — execute the toggle."""
        pending = self.main_window._pending_undo
        if (
            not pending
            or pending.get("page") is not self
            or pending.get("switch") is not switch
            or pending.get("state") != state
        ):
            return False

        self.main_window._pending_undo = None
        self.main_window.banner.set_revealed(False)
        self.main_window._banner_callback = None
        self._execute_toggle(switch, state)
        return False  # Don't repeat

    def _execute_toggle(self, switch: Gtk.Switch, state: bool) -> None:
        """Execute the actual toggle in a background thread with spinner feedback."""
        script_path = self.switch_scripts.get(switch)
        if not script_path:
            logger.error("No script registered for switch")
            return

        timeout = self.switch_timeouts.get(script_path)
        self._sync_generation += 1
        script_name = os.path.basename(script_path)
        logger.info(
            _("Changing {} to {}").format(script_name, "on" if state else "off")
        )

        row = self._get_wd(switch, "row")
        # Show spinner and disable switch during execution
        spinner = Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER)
        switch.set_visible(False)
        row.add_suffix(spinner)
        row.set_sensitive(False)
        original_subtitle = row.get_subtitle()
        row.set_subtitle(_("Applying…"))

        self._busy_switches.add(switch)

        def _toggle_in_thread():
            try:
                success = self.toggle_script_state(script_path, state, timeout=timeout)
            except Exception:
                logger.exception("Unexpected error toggling %s", script_path)
                success = False
            GLib.idle_add(_on_toggle_done, success)

        def _on_toggle_done(success):
            self._busy_switches.discard(switch)
            # Remove spinner and restore switch visibility
            row.remove(spinner)
            switch.set_visible(True)
            row.set_sensitive(True)
            row.set_subtitle(original_subtitle or "")

            if not success:
                self._set_switch_active_without_handler(switch, not state)

                logger.error(
                    _("ERROR: Failed to change {} to {}").format(
                        script_name, "on" if state else "off"
                    )
                )
                self.main_window.show_toast(
                    _("Failed to change setting: {}").format(script_name)
                )
                # The script may have applied part of the change, or a first
                # sync may have been discarded meanwhile: read the real state.
                self.sync_all_switches_async()
            else:
                # Confirm the backend state (active was already set by user click)
                self._set_switch_active_without_handler(switch, state)
                self._toggle_info_icon_visibility(switch, state)

                # If this switch is a parent, adjust visibility of its sub-switches
                self._update_sub_switches_visibility(switch, state)

                # Refresh all switches asynchronously
                self.sync_all_switches_async()

            return False

        threading.Thread(target=_toggle_in_thread, daemon=True).start()

    def filter_rows(self, search_text: str, hide_group_headers: bool = False) -> bool:
        """Filter rows based on search text. Returns True if any rows are visible."""
        if not hasattr(self, "content_box"):
            return True

        total_visible = 0
        for child in self._get_all_children(self.content_box):
            if isinstance(child, Adw.PreferencesGroup):
                visible = self._filter_group(child, search_text, hide_group_headers)
                total_visible += visible

        return total_visible > 0

    def get_matching_rows(
        self, search_text: str
    ) -> list[tuple[Adw.PreferencesRow, Adw.PreferencesGroup]]:
        """Get list of rows that match search text with their parent groups."""
        if not hasattr(self, "content_box"):
            return []

        matching = []
        for child in self._get_all_children(self.content_box):
            if isinstance(child, Adw.PreferencesGroup):
                listbox = self._find_listbox_in_widget(child)
                if not listbox:
                    continue

                row = listbox.get_first_child()
                while row:
                    if isinstance(row, Adw.ExpanderRow):
                        matching.extend(
                            (sub_row, child)
                            for sub_row in self._matching_expander_rows(
                                row, search_text
                            )
                        )
                    elif isinstance(row, (Adw.PreferencesRow, Gtk.ListBoxRow)):
                        # Skip rows hidden due to lack of support
                        if self._get_wd(row, "hidden_no_support", False):
                            row = row.get_next_sibling()
                            continue

                        text = self._get_row_text(row).lower()
                        if search_text in text:
                            matching.append((row, child))
                    row = row.get_next_sibling()

        return matching

    def _expander_child_rows(self, expander: Adw.ExpanderRow) -> list[Gtk.Widget]:
        """Rows added to an ExpanderRow (they live in its Revealer's ListBox)."""
        rows = []
        stack = [expander]
        while stack:
            widget = stack.pop()
            if isinstance(widget, Gtk.Revealer):
                listbox = self._find_listbox_in_widget(widget)
                if listbox:
                    rows.extend(self._get_all_children(listbox))
                continue
            stack.extend(self._get_all_children(widget))
        return [
            row
            for row in rows
            if isinstance(row, Adw.ActionRow)
            and not self._get_wd(row, "hidden_no_support", False)
        ]

    def _matching_expander_rows(
        self, expander: Adw.ExpanderRow, search_text: str
    ) -> list[Gtk.Widget]:
        """Child rows matching the search; all of them if only the header matches."""
        children = self._expander_child_rows(expander)
        matches = [
            row for row in children if search_text in self._get_row_text(row).lower()
        ]
        if matches:
            return matches
        header = f"{expander.get_title() or ''} {expander.get_subtitle() or ''}"
        if search_text in html.unescape(header).lower():
            return children
        return []

    def _get_sub_row_visibility(self, row: Adw.ActionRow) -> bool:
        """Determine if a sub-row should be visible based on its parent switch state."""
        for p_switch, children in self.sub_switches.items():
            if row in children:
                return p_switch.get_active()
        return False

    def _apply_row_visibility(self, row: Adw.ActionRow, search_text: str) -> int:
        """Apply visibility logic to a single row. Returns 1 if visible, 0 otherwise."""
        if not search_text:
            if self._get_wd(row, "is_sub_row", False):
                row.set_visible(self._get_sub_row_visibility(row))
            else:
                row.set_visible(True)
            return 1

        text = self._get_row_text(row).lower()
        visible = search_text in text
        row.set_visible(visible)
        return 1 if visible else 0

    def _update_group_header(
        self, group: Adw.PreferencesGroup, search_text: str, hide_group_headers: bool
    ) -> None:
        """Save/restore group description and header suffix based on search state."""
        if self._get_wd(group, "orig_desc") is None:
            self._set_wd(group, "orig_desc", group.get_description() or "")

        if hide_group_headers and search_text:
            group.set_description("")
            suffix = group.get_header_suffix()
            if suffix:
                suffix.set_visible(False)
        else:
            group.set_description(self._get_wd(group, "orig_desc", ""))
            suffix = group.get_header_suffix()
            if suffix:
                suffix.set_visible(True)

    def _filter_group(
        self,
        group: Adw.PreferencesGroup,
        search_text: str,
        hide_group_headers: bool = False,
    ) -> int:
        """Filter rows within a PreferencesGroup. Returns count of visible rows."""
        self._update_group_header(group, search_text, hide_group_headers)

        listbox = self._find_listbox_in_widget(group)
        if not listbox:
            return 0

        visible_count = 0
        row = listbox.get_first_child()
        while row:
            if isinstance(row, (Adw.PreferencesRow, Gtk.ListBoxRow)):
                if not self._get_wd(row, "hidden_no_support", False):
                    visible_count += self._apply_row_visibility(row, search_text)
            row = row.get_next_sibling()

        group.set_visible(visible_count > 0 or not search_text)
        return visible_count

    def _find_listbox_in_widget(self, widget: Gtk.Widget) -> Optional[Gtk.ListBox]:
        """Recursively find GtkListBox inside a widget."""
        if isinstance(widget, Gtk.ListBox):
            return widget
        child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
        while child:
            result = self._find_listbox_in_widget(child)
            if result:
                return result
            child = child.get_next_sibling()
        return None

    def _get_row_text(self, row: Gtk.Widget) -> str:
        """Extract searchable text from a row widget."""
        texts = []
        self._collect_label_texts(row, texts)
        return " ".join(texts)

    def _collect_label_texts(self, widget: Gtk.Widget, texts: list[str]) -> None:
        """Recursively collect text from all labels in a widget."""
        if isinstance(widget, Gtk.Label):
            text = widget.get_text() or widget.get_label() or ""
            if text:
                texts.append(text)
        child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
        while child:
            self._collect_label_texts(child, texts)
            child = child.get_next_sibling()

    def _get_all_children(self, widget: Gtk.Widget) -> list[Gtk.Widget]:
        """Get all direct children of a widget."""
        children = []
        child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
        while child:
            children.append(child)
            child = child.get_next_sibling()
        return children
