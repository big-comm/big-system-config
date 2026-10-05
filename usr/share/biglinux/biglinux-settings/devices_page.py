import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from base_page import BaseSettingsPage, _, _plain_markup  # noqa: E402
from network_manager import NetworkError, NetworkManager  # noqa: E402

logger = logging.getLogger("biglinux-settings")

# Map nmcli type names to user-friendly labels and icons
_IFACE_ICONS = {
    "wifi": "wifi-symbolic",
    "ethernet": "network-wired-symbolic",
    "gsm": "network-cellular-symbolic",
    "cdma": "network-cellular-symbolic",
    "bluetooth": "bluetooth-symbolic",
}


class DevicesPage(BaseSettingsPage):
    def __init__(self, main_window, **kwargs):
        super().__init__(main_window, **kwargs)

        # Create the container (base method)
        content = self.create_scrolled_content()

        # Create the group (base method)
        group = self.create_group(
            _("Devices"), _("Manage physical devices."), "devices"
        )
        content.append(group)

        # Wifi
        self.create_row(group, _("Wifi"), _("Enable the Wi-Fi adapter."), "wifi", "wifi-symbolic")

        # Bluetooth
        self.create_row(
            group, _("Bluetooth"), _("Enable the Bluetooth adapter."), "bluetooth", "bluetooth-symbolic"
        )

        # JamesDSP
        self.create_row(
            group,
            _("JamesDSP"),
            _("Advanced audio effects processor that improves sound quality."),
            "jamesdsp",
            "jamesdsp-symbolic",
        )

        # Reverse mouse scrolling
        self.create_row(
            group,
            _("Reverse mouse scrolling"),
            _("Reverse mouse scrolling without restarting the session."),
            "reverse-mouse_scroll",
            "reverse-mouse_scroll-symbolic",
        )

        # Network Interfaces (dynamic, discovered via nmcli)
        self._net_group = self.create_group(
            _("Network Interfaces"),
            _("Connect or disconnect network devices."),
            "devices",
        )
        content.append(self._net_group)
        self._net_switches = {}  # device_name -> Gtk.Switch
        self._load_network_interfaces()

    def _load_network_interfaces(self):
        """Load network interfaces in a background thread."""

        def _discover():
            try:
                interfaces = NetworkManager.get_interfaces()
            except NetworkError:
                interfaces = []
            GLib.idle_add(self._populate_network_rows, interfaces)

        threading.Thread(target=_discover, daemon=True).start()

    def _populate_network_rows(self, interfaces):
        """Populate the network group with discovered interfaces (on main thread)."""
        if not interfaces:
            self._net_group.set_visible(False)
            return

        for iface in interfaces:
            device = iface["device"]
            type_ = iface["type"]
            connection = iface["connection"] or device
            active = iface["active"]

            icon_name = _IFACE_ICONS.get(type_, "network-wired-symbolic")
            subtitle = _("{} — {}").format(type_, iface["state"])

            # Connection names (e.g. SSIDs) are user data: escape for Pango
            row = Adw.ActionRow(
                title=_plain_markup(connection), subtitle=_plain_markup(subtitle)
            )

            # Icon prefix
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(24)
            img.add_css_class("symbolic-icon")
            row.add_prefix(img)

            # Switch suffix
            switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=active)
            switch.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [_("{}: toggle connection").format(connection)],
            )
            switch.connect("state-set", self._on_net_switch_changed)
            row.add_suffix(switch)
            row.set_activatable_widget(switch)

            self._set_wd(switch, "row", row)
            self._set_wd(switch, "device", device)
            self._set_wd(switch, "type", type_)
            self._net_switches[device] = switch
            self._net_group.add(row)

        return False

    def _on_net_switch_changed(self, switch, state):
        """Connect or disconnect a network device."""
        device = self._get_wd(switch, "device")
        row = self._get_wd(switch, "row")
        if not device:
            return True

        row.set_sensitive(False)
        original_subtitle = row.get_subtitle()
        row.set_subtitle(_("Applying…"))

        def _toggle():
            try:
                if state:
                    NetworkManager.connect_device(device)
                else:
                    NetworkManager.disconnect_device(device)
                success = True
            except NetworkError:
                success = False
            GLib.idle_add(
                self._on_net_toggle_done,
                switch,
                row,
                device,
                state,
                success,
                original_subtitle,
            )

        threading.Thread(target=_toggle, daemon=True).start()
        return True

    def _set_net_switch_without_handler(self, switch, state):
        switch.handler_block_by_func(self._on_net_switch_changed)
        switch.set_active(state)
        switch.set_state(state)
        switch.handler_unblock_by_func(self._on_net_switch_changed)

    def _on_net_toggle_done(
        self, switch, row, device, state, success, original_subtitle
    ):
        """Main-thread completion of a network device connect/disconnect."""
        row.set_sensitive(True)
        if success:
            self._set_net_switch_without_handler(switch, state)
            iface_state = _("connected") if state else _("disconnected")
            type_ = self._get_wd(switch, "type") or ""
            row.set_subtitle(_("{} — {}").format(type_, iface_state) if type_ else iface_state)
        else:
            row.set_subtitle(original_subtitle or "")
            self._set_net_switch_without_handler(switch, not state)
            self.main_window.show_toast(
                _("Failed to change network device: {}").format(device)
            )
        return False
