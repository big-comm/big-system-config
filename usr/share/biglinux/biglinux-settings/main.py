#!/usr/bin/env python3
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
import html
import logging
import os

from ai_page import AIPage
from config import _, APP_ID, APP_VERSION, BASE_DIR, ICONS_DIR
from developer_page import DeveloperPage
from devices_page import DevicesPage
from docker_page import DockerPage
from gi.repository import Adw, Gdk, Gio, GLib, Gtk
from performance_page import PerformancePage
from preload_page import PreloadPage
from sleep_page import SleepPage
from system_page import SystemPage
from usability_page import UsabilityPage

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("biglinux-settings")
TOAST_TIMEOUT_MS = 3500
WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 700
INSTALLED_MAIN = "/usr/share/biglinux/biglinux-settings/main.py"


def _is_source_run(main_file=__file__):
    """Return whether the app is running outside the installed path."""
    return os.path.realpath(main_file) != os.path.realpath(INSTALLED_MAIN)


def _highlight_text(text, search_text):
    """Wrap matching substring with bold Pango markup, escaping existing markup.

    Row titles are stored already escaped (see base_page._plain_markup), so the
    text is unescaped first: matching runs on what the user sees and each piece
    is escaped exactly once.
    """
    plain = html.unescape(text)
    idx = plain.lower().find(search_text) if search_text else -1
    if idx == -1:
        return html.escape(plain, quote=False)
    end = idx + len(search_text)
    return (
        html.escape(plain[:idx], quote=False)
        + "<b>"
        + html.escape(plain[idx:end], quote=False)
        + "</b>"
        + html.escape(plain[end:], quote=False)
    )


class BiglinuxSettingsApp(Adw.Application):
    def __init__(self):
        kwargs = {"application_id": APP_ID}
        if _is_source_run():
            # Do not forward source runs to an older installed process.
            kwargs["flags"] = Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(**kwargs)
        GLib.set_prgname(APP_ID)
        self.connect("activate", self.on_activate)

        # About action for hamburger menu
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

    def on_activate(self, app):
        self.window = BiglinuxSettingsWindow(application=app)
        self.window.present()

    def _on_about(self, _action, _param):
        about = Adw.AboutDialog(
            application_name=_("BigLinux Settings"),
            application_icon="biglinux-settings",
            version=APP_VERSION,
            developer_name="BigLinux Community",
            website="https://www.biglinux.com.br",
            issue_url="https://github.com/biglinux/biglinux-settings/issues",
            license_type=Gtk.License.GPL_3_0,
            developers=[_("BigLinux Community")],
        )
        about.present(self.window)


class BiglinuxSettingsWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_css_class("biglinux-settings")
        self.set_title(_("BigLinux Settings"))
        # Fixed geometry: the default size is both minimum and maximum.
        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.set_resizable(False)

        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_theme.add_search_path(ICONS_DIR)

        self.pages_config = []
        self.is_searching = False
        self.current_page_id = None
        self._synced_pages = set()
        # Pages whose first sync was started by a search and is still running
        self._syncing_pages = set()
        self._banner_timeout_id = None
        self._pending_undo = None
        self.load_css()
        self.setup_ui()

    def load_css(self):
        self.css_provider = Gtk.CssProvider()
        css_path = os.path.join(BASE_DIR, "styles.css")
        try:
            self.css_provider.load_from_path(css_path)
        except GLib.Error as e:
            logger.error("Failed to load CSS: %s", e)
            return
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            self.css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def setup_ui(self):
        # Root layout with banner for accessible feedback
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root_box)

        # Banner for persistent, accessible feedback messages
        self.banner = Adw.Banner()
        self.banner.set_revealed(False)
        self._banner_callback = None
        self.banner.connect("button-clicked", self._on_banner_button_clicked)
        root_box.append(self.banner)

        # OverlaySplitView for modern sidebar + content layout
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_min_sidebar_width(260)
        self.split_view.set_max_sidebar_width(320)
        self.split_view.set_sidebar_width_fraction(0.32)
        self.split_view.set_vexpand(True)
        root_box.append(self.split_view)

        # === SIDEBAR ===
        sidebar_toolbar = Adw.ToolbarView()

        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_show_end_title_buttons(False)

        # Centered title
        title_label = Gtk.Label(label=_("BigLinux Settings"))
        title_label.add_css_class("heading")
        sidebar_header.set_title_widget(title_label)

        sidebar_toolbar.add_top_bar(sidebar_header)

        # Scrollable sidebar content
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_vexpand(True)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        sidebar_box.set_margin_start(12)
        sidebar_box.set_margin_end(12)
        sidebar_box.set_margin_top(6)
        sidebar_box.set_margin_bottom(12)

        # Navigation ListBox with built-in selection
        self.sidebar_list = Gtk.ListBox()
        self.sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar_list.add_css_class("navigation-sidebar")
        self.sidebar_list.connect("row-selected", self.on_sidebar_row_selected)
        sidebar_box.append(self.sidebar_list)

        sidebar_scroll.set_child(sidebar_box)
        sidebar_toolbar.set_content(sidebar_scroll)

        self.split_view.set_sidebar(sidebar_toolbar)

        # === CONTENT ===
        content_toolbar = Adw.ToolbarView()

        content_header = Adw.HeaderBar()
        content_header.set_show_start_title_buttons(False)

        # Search entry centered
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(_("Search..."))
        self.search_entry.set_hexpand(False)
        self.search_entry.set_width_chars(30)
        self.search_entry.connect("search-changed", self.on_search_changed)
        self.search_entry.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Search settings")],
        )
        content_header.set_title_widget(self.search_entry)

        # Sidebar toggle button (visible only when sidebar is collapsed)
        self.sidebar_toggle = Gtk.ToggleButton()
        self.sidebar_toggle.set_icon_name("sidebar-show-symbolic")
        self.sidebar_toggle.set_tooltip_text(_("Toggle navigation sidebar"))
        self.sidebar_toggle.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Toggle navigation sidebar")],
        )
        self.sidebar_toggle.connect("toggled", self._on_sidebar_toggle)
        content_header.pack_start(self.sidebar_toggle)

        # Hamburger menu with About
        menu = Gio.Menu()
        menu.append(_("About"), "app.about")
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu)
        menu_button.set_tooltip_text(_("Main Menu"))
        menu_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Main Menu")],
        )
        content_header.pack_end(menu_button)

        content_toolbar.add_top_bar(content_header)

        # === SEARCH RESULTS ===
        self.search_results_scroll = Gtk.ScrolledWindow()
        self.search_results_scroll.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC
        )
        self.search_results_scroll.set_vexpand(True)
        self.search_results_scroll.set_visible(False)

        self.search_results_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=0,
            margin_top=12,
            margin_bottom=12,
            margin_start=20,
            margin_end=20,
        )
        self.search_results_scroll.set_child(self.search_results_box)

        self.search_results_group = Adw.PreferencesGroup()
        self.search_results_box.append(self.search_results_group)

        self.search_result_rows = []

        # === PAGE STACK ===
        self.page_stack = Gtk.Stack()
        self.page_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.page_stack.set_transition_duration(200)
        self.page_stack.set_vexpand(True)

        # Content wrapper to switch between pages and search results
        self.content_wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_wrapper.append(self.page_stack)
        self.content_wrapper.append(self.search_results_scroll)
        content_toolbar.set_content(self.content_wrapper)

        self.split_view.set_content(content_toolbar)

        # Show sidebar toggle only when sidebar is collapsed
        self.split_view.connect("notify::collapsed", self._on_sidebar_collapsed)
        self.sidebar_toggle.set_visible(self.split_view.get_collapsed())

        # === CREATE PAGES ===
        self.pages_config = [
            {
                "label": _("System"),
                "icon": "system-symbolic",
                "id": "system",
                "class": SystemPage,
            },
            {
                "label": _("Usability"),
                "icon": "usability-symbolic",
                "id": "usability",
                "class": UsabilityPage,
            },
            {
                "label": _("PreLoad"),
                "icon": "preload-symbolic",
                "id": "preload",
                "class": PreloadPage,
            },
            {
                "label": _("Devices"),
                "icon": "devices-symbolic",
                "id": "devices",
                "class": DevicesPage,
            },
            {
                "label": _("A.I."),
                "icon": "ai-symbolic",
                "id": "ai",
                "class": AIPage,
            },
            {
                "label": _("Docker"),
                "icon": "docker-geral-symbolic",
                "id": "docker",
                "class": DockerPage,
            },
            {
                "label": _("Developer"),
                "icon": "developer-symbolic",
                "id": "developer",
                "class": DeveloperPage,
            },
            {
                "label": _("Performance"),
                "icon": "performance-symbolic",
                "id": "performance",
                "class": PerformancePage,
            },
            {
                "label": _("Suspend"),
                "icon": "sleep-symbolic",
                "id": "sleep",
                "class": SleepPage,
            },
        ]

        for page_cfg in self.pages_config:
            # Sidebar navigation row
            row = Gtk.ListBoxRow()
            row.page_id = page_cfg["id"]

            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(8)
            box.set_margin_end(8)

            icon_path = os.path.join(ICONS_DIR, f"{page_cfg['icon']}.svg")
            gfile = Gio.File.new_for_path(icon_path)
            img = Gtk.Image.new_from_gicon(Gio.FileIcon.new(gfile))
            img.set_pixel_size(20)
            img.add_css_class("symbolic-icon")
            box.append(img)

            lbl = Gtk.Label(label=page_cfg["label"], xalign=0, hexpand=True)
            box.append(lbl)

            row.set_child(box)
            row.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [page_cfg["label"]],
            )
            self.sidebar_list.append(row)

            # Page instance (no sync in __init__ — deferred to first show)
            page_instance = page_cfg["class"](self)
            page_cfg["instance"] = page_instance
            self.page_stack.add_named(page_instance, page_cfg["id"])

        # Select first page
        first_row = self.sidebar_list.get_row_at_index(0)
        if first_row:
            self.sidebar_list.select_row(first_row)

    def on_sidebar_row_selected(self, listbox, row):
        if row is None or self.is_searching:
            return
        self.current_page_id = row.page_id
        self._show_single_page(row.page_id)
        # Auto-close sidebar on narrow windows when user selects a page
        if self.split_view.get_collapsed():
            self.split_view.set_show_sidebar(False)

    def _on_sidebar_toggle(self, button):
        """Toggle the sidebar visibility when in collapsed mode."""
        self.split_view.set_show_sidebar(button.get_active())

    def _on_sidebar_collapsed(self, split_view, _pspec):
        """Show/hide sidebar toggle button based on collapsed state."""
        collapsed = split_view.get_collapsed()
        self.sidebar_toggle.set_visible(collapsed)
        if not collapsed:
            self.sidebar_toggle.set_active(False)

    def _show_single_page(self, page_id):
        """Show only one page via Gtk.Stack (normal mode)."""
        self._clear_search_results()

        self.search_results_scroll.set_visible(False)
        self.page_stack.set_visible(True)
        self.page_stack.set_visible_child_name(page_id)

        # Reset filter on visible page
        for page_cfg in self.pages_config:
            instance = page_cfg.get("instance")
            if instance and hasattr(instance, "set_search_mode"):
                instance.set_search_mode(False)
            if (
                page_cfg["id"] == page_id
                and instance
                and hasattr(instance, "filter_rows")
            ):
                instance.filter_rows("")

        # Lazy sync: only sync a page on first visit
        if page_id not in self._synced_pages:
            for page_cfg in self.pages_config:
                if page_cfg["id"] == page_id:
                    instance = page_cfg["instance"]
                    if hasattr(instance, "sync_all_switches_async"):
                        instance.sync_all_switches_async()
                    self._synced_pages.add(page_id)
                    break

    def _show_search_results(self, search_text):
        """Show search results in a single compact container."""
        self._clear_search_results()

        self.page_stack.set_visible(False)
        self.search_results_scroll.set_visible(True)

        # Ensure all pages are synced for accurate search results. Pages still
        # syncing are left out (their unsupported rows are not hidden yet) and
        # the results are rebuilt when each sync lands.
        for page_cfg in self.pages_config:
            page_id = page_cfg["id"]
            if page_id not in self._synced_pages:
                instance = page_cfg["instance"]
                if hasattr(instance, "sync_all_switches_async"):
                    self._syncing_pages.add(page_id)
                    instance.sync_all_switches_async(
                        on_done=lambda pid=page_id: self._on_search_page_synced(pid)
                    )
                self._synced_pages.add(page_id)

        for page_cfg in self.pages_config:
            if page_cfg["id"] in self._syncing_pages:
                continue
            instance = page_cfg.get("instance")
            if instance and hasattr(instance, "get_matching_rows"):
                matching_rows = instance.get_matching_rows(search_text)
                for row, _original_parent in matching_rows:
                    self._add_search_result(row, page_cfg, search_text)

    def _on_search_page_synced(self, page_id):
        self._syncing_pages.discard(page_id)
        search_text = self.search_entry.get_text().lower().strip()
        if self.is_searching and len(search_text) >= 2:
            self._show_search_results(search_text)

    @staticmethod
    def _highlight_text(text, search_text):
        """Wrap matching substring with bold Pango markup, escaping existing markup."""
        return _highlight_text(text, search_text)

    def _add_search_result(self, original_row, page_cfg, search_text):
        """Add a non-destructive search result that opens its source page."""
        if not isinstance(original_row, Adw.ActionRow):
            return
        title = original_row.get_title() or ""
        subtitle = original_row.get_subtitle() or ""
        result = Adw.ActionRow(title=self._highlight_text(title, search_text))
        if subtitle:
            result.set_subtitle(self._highlight_text(subtitle, search_text))
        button = Gtk.Button(
            icon_name="go-next-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=_("Open setting"),
        )
        button.add_css_class("flat")
        button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Open {} setting").format(title)],
        )
        button.connect(
            "clicked", lambda _button: self._open_search_result(page_cfg["id"])
        )
        result.add_suffix(button)
        result.set_activatable_widget(button)
        self.search_results_group.add(result)
        self.search_result_rows.append(result)

    def _clear_search_results(self):
        for row in self.search_result_rows:
            self.search_results_group.remove(row)
        self.search_result_rows.clear()

    def _open_search_result(self, page_id):
        self.search_entry.set_text("")
        row = self.sidebar_list.get_first_child()
        while row:
            if getattr(row, "page_id", None) == page_id:
                self.sidebar_list.select_row(row)
                break
            row = row.get_next_sibling()

    def on_search_changed(self, entry):
        search_text = entry.get_text().lower().strip()

        if len(search_text) < 2:
            self.is_searching = False
            self.sidebar_list.set_sensitive(True)
            self._show_single_page(self.current_page_id or self.pages_config[0]["id"])
        else:
            self.is_searching = True
            self.sidebar_list.set_sensitive(False)
            self._show_search_results(search_text)

    def _cancel_banner_timeout(self):
        if self._banner_timeout_id is not None:
            GLib.source_remove(self._banner_timeout_id)
            self._banner_timeout_id = None

    def _cancel_pending_undo(self, revert=False):
        pending = self._pending_undo
        if not pending:
            return

        timer_id = pending.get("timer_id")
        if timer_id is not None:
            GLib.source_remove(timer_id)

        self._pending_undo = None

        if revert:
            page = pending.get("page")
            switch = pending.get("switch")
            state = pending.get("state")
            if page is not None and switch is not None:
                page._set_switch_active_without_handler(switch, not state)

    def _hide_banner_from_timeout(self):
        self._banner_timeout_id = None
        self._banner_callback = None
        self.banner.set_revealed(False)
        return False

    def show_toast(self, message):
        # Leave a pending click on another switch alone: it still gets applied
        # when its undo window ends; only the undo button is replaced.
        self._cancel_banner_timeout()
        # Adw.Banner parses markup; messages are plain text (may hold "&")
        self.banner.set_title(html.escape(html.unescape(message), quote=False))
        self.banner.set_button_label(_("Dismiss"))
        self._banner_callback = None
        self.banner.set_revealed(True)
        self._banner_timeout_id = GLib.timeout_add(TOAST_TIMEOUT_MS, self._hide_banner_from_timeout)

    def _on_banner_button_clicked(self, banner):
        """Handle banner button click — calls undo callback if set, otherwise just dismisses."""
        self._cancel_banner_timeout()
        callback = self._banner_callback
        self._banner_callback = None
        banner.set_revealed(False)
        if callback:
            callback()


def main():
    app = BiglinuxSettingsApp()
    return app.run()


if __name__ == "__main__":
    main()
