#!/usr/bin/env python3
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
import html
import logging
import os
import unicodedata

from ai_page import AIPage
from apps_page import AppsPage
from base_page import PATH_SEPARATOR, normalize_search_text
from config import _, APP_ID, APP_VERSION, BASE_DIR, ICONS_DIR, ngettext
from devices_page import DevicesPage
from gi.repository import Adw, Gdk, Gio, GLib, Gtk
from home_page import HomePage
from performance_page import PerformancePage
from sleep_page import SleepPage
from system_page import SystemPage
from usability_page import UsabilityPage

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")
# Icon name, CSS class and logger name shared across the app.
APP_SLUG = "biglinux-settings"
logger = logging.getLogger(APP_SLUG)
TOAST_TIMEOUT_MS = 3500
# Default size; the window is resizable and adapts down to MIN_WIDTH
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 760
MIN_WIDTH = 360
MIN_HEIGHT = 480
# Below this width the sidebar collapses into an overlay
SIDEBAR_COLLAPSE_WIDTH = "max-width: 720sp"
# Pages that open the "More features" part of the sidebar
MORE_FEATURES_FIRST_PAGE = "ai"
INSTALLED_MAIN = "/usr/share/biglinux/biglinux-settings/main.py"


def _app_name():
    """Translated application name."""
    return _("BigLinux Settings")


def _is_source_run(main_file=__file__):
    """Return whether the app is running outside the installed path."""
    return os.path.realpath(main_file) != os.path.realpath(INSTALLED_MAIN)


def _fold_with_index(text):
    """Accent/case-folded text plus, for each folded char, its source index."""
    folded, index = [], []
    for position, char in enumerate(text):
        for piece in unicodedata.normalize("NFKD", char):
            if unicodedata.combining(piece):
                continue
            for out in piece.casefold():
                folded.append(out)
                index.append(position)
    return "".join(folded), index


def _highlight_text(text, search_text):
    """Wrap the matching part with bold Pango markup, escaping existing markup.

    Row titles are stored already escaped (see base_page._plain_markup), so the
    text is unescaped first. Matching ignores case and accents ("nao" finds
    "não"), and the bold covers the original characters.
    """
    plain = html.unescape(text)
    query = normalize_search_text(search_text) if search_text else ""
    folded, index = _fold_with_index(plain)
    idx = folded.find(query) if query else -1
    if idx == -1:
        return html.escape(plain, quote=False)
    start = index[idx]
    end = index[idx + len(query) - 1] + 1
    return (
        html.escape(plain[:start], quote=False)
        + "<b>"
        + html.escape(plain[start:end], quote=False)
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
            application_name=_app_name(),
            application_icon=APP_SLUG,
            version=APP_VERSION,
            developer_name="BigLinux Community",
            website="https://www.biglinux.com.br",
            issue_url="https://github.com/big-comm/big-system-config/issues",
            license_type=Gtk.License.GPL_3_0,
            developers=[_("BigLinux Community")],
        )
        about.present(self.window)


class BiglinuxSettingsWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_css_class(APP_SLUG)
        self.set_title(_app_name())
        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.set_size_request(MIN_WIDTH, MIN_HEIGHT)

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
        self._last_query = ""
        self._navigating = False
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
        self.split_view.set_min_sidebar_width(220)
        self.split_view.set_max_sidebar_width(260)
        self.split_view.set_sidebar_width_fraction(0.24)
        self.split_view.set_vexpand(True)
        root_box.append(self.split_view)

        # Narrow windows: the sidebar becomes an overlay opened from the header
        breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse(SIDEBAR_COLLAPSE_WIDTH)
        )
        breakpoint.add_setter(self.split_view, "collapsed", True)
        self.add_breakpoint(breakpoint)

        # === SIDEBAR ===
        sidebar_toolbar = Adw.ToolbarView()

        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_show_end_title_buttons(False)

        # Centered title
        title_label = Gtk.Label(label=_app_name())
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
        self.sidebar_list.set_header_func(self._sidebar_header)
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
        self.search_entry.set_placeholder_text(_("Search settings…"))
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

        # Back to the results after opening one of them
        self.back_to_results = Gtk.Button(icon_name="go-previous-symbolic")
        self.back_to_results.set_tooltip_text(_("Back to search results"))
        self.back_to_results.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Back to search results")]
        )
        self.back_to_results.set_visible(False)
        self.back_to_results.connect("clicked", self._on_back_to_results)
        content_header.pack_start(self.back_to_results)

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
            spacing=12,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        results_clamp = Adw.Clamp(maximum_size=820, tightening_threshold=600)
        results_clamp.set_child(self.search_results_box)
        self.search_results_scroll.set_child(results_clamp)

        self.search_results_group = Adw.PreferencesGroup()
        self.search_results_box.append(self.search_results_group)

        self.search_empty = Adw.StatusPage(
            icon_name="edit-find-symbolic",
            title=_("No results"),
            description=_(
                "Try other words, like “don't sleep”, “remote access” or “battery”."
            ),
        )
        self.search_empty.set_visible(False)
        self.search_results_box.append(self.search_empty)

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
            {"label": _("Home"), "icon": "go-home-symbolic", "id": "home", "class": HomePage},
            {"label": _("System"), "icon": "system-symbolic", "id": "system", "class": SystemPage},
            {
                "label": _("Appearance & Usage"),
                "icon": "usability-symbolic",
                "id": "usability",
                "class": UsabilityPage,
            },
            {
                "label": _("Power & Suspend"),
                "icon": "sleep-symbolic",
                "id": "sleep",
                "class": SleepPage,
            },
            {
                "label": _("Performance"),
                "icon": "performance-symbolic",
                "id": "performance",
                "class": PerformancePage,
            },
            {"label": _("Devices"), "icon": "devices-symbolic", "id": "devices", "class": DevicesPage},
            {
                "label": _("Artificial Intelligence"),
                "icon": "ai-symbolic",
                "id": "ai",
                "class": AIPage,
            },
            {
                "label": _("Apps & Services"),
                "icon": "docker-geral-symbolic",
                "id": "apps",
                "class": AppsPage,
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
            if os.path.exists(icon_path):
                gfile = Gio.File.new_for_path(icon_path)
                img = Gtk.Image.new_from_gicon(Gio.FileIcon.new(gfile))
            else:
                img = Gtk.Image.new_from_icon_name(page_cfg["icon"])
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

        # Always start on Home
        self.select_page("home")

    def _sidebar_header(self, row, before):
        """Small "More features" label above the optional areas."""
        if getattr(row, "page_id", None) != MORE_FEATURES_FIRST_PAGE:
            row.set_header(None)
            return
        if row.get_header() is None:
            label = Gtk.Label(label=_("More features"), xalign=0)
            label.add_css_class("sidebar-section-label")
            row.set_header(label)

    def page_instance(self, page_id):
        for page_cfg in self.pages_config:
            if page_cfg["id"] == page_id:
                return page_cfg.get("instance")
        return None

    def page_label(self, page_id):
        for page_cfg in self.pages_config:
            if page_cfg["id"] == page_id:
                return page_cfg["label"]
        return ""

    def select_page(self, page_id):
        row = self.sidebar_list.get_first_child()
        while row:
            if getattr(row, "page_id", None) == page_id:
                self.sidebar_list.select_row(row)
                return True
            row = row.get_next_sibling()
        return False

    def open_setting(self, page_id, script_name=None, row=None):
        """Open a page and bring one setting into view (search, home cards)."""
        if self.search_entry.get_text():
            self._navigating = True
            self.search_entry.set_text("")
            self._navigating = False
            self._leave_search_mode()
        self.select_page(page_id)
        # select_row does nothing if the page was already selected
        self._show_single_page(page_id)
        page = self.page_instance(page_id)
        if page is None:
            return
        if row is None and script_name and hasattr(page, "find_switch"):
            switch = page.find_switch(script_name)
            row = page._get_wd(switch, "row") if switch is not None else None
        if row is not None and hasattr(page, "reveal_row"):
            page.reveal_row(row)

    def on_sidebar_row_selected(self, listbox, row):
        if row is None or self.is_searching:
            return
        self.current_page_id = row.page_id
        if not self._navigating:
            self.back_to_results.set_visible(False)
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

        self._reset_page_filters(page_id)
        if page_id == "home":
            # Cards show live state: refresh every time Home is shown
            self.page_instance("home").refresh()
            self._synced_pages.add(page_id)
        else:
            self._sync_page_once(page_id)

    def _reset_page_filters(self, page_id):
        """Leave search mode on every page and clear the visible page filter."""
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

    def _sync_page_once(self, page_id):
        """Lazy sync: only sync a page on first visit."""
        if page_id in self._synced_pages:
            return
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

        count = len(self.search_result_rows)
        still_loading = bool(self._syncing_pages)
        self.search_results_group.set_visible(count > 0)
        self.search_empty.set_visible(count == 0 and not still_loading)
        self.search_results_group.set_title(
            ngettext("{} result", "{} results", count).format(count)
        )

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
        """Add a non-destructive search result that opens its exact setting."""
        if not isinstance(original_row, Adw.ActionRow):
            return
        title = original_row.get_title() or ""
        page = page_cfg.get("instance")
        section = page.row_section(original_row) if page is not None else ""
        path = PATH_SEPARATOR.join(p for p in (page_cfg["label"], section) if p)
        result = Adw.ActionRow(title=self._highlight_text(title, search_text))
        result.set_subtitle(html.escape(path, quote=False))
        button = Gtk.Button(
            icon_name="go-next-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=_("Open setting"),
        )
        button.add_css_class("flat")
        button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Open {} setting").format(html.unescape(title))],
        )
        button.connect(
            "clicked",
            lambda _button: self._open_search_result(page_cfg["id"], original_row),
        )
        result.add_suffix(button)
        result.set_activatable_widget(button)
        self.search_results_group.add(result)
        self.search_result_rows.append(result)

    def _clear_search_results(self):
        for row in self.search_result_rows:
            self.search_results_group.remove(row)
        self.search_result_rows.clear()

    def _open_search_result(self, page_id, row=None):
        self._last_query = self.search_entry.get_text()
        self.open_setting(page_id, row=row)
        self.back_to_results.set_visible(True)

    def _on_back_to_results(self, _button):
        self.back_to_results.set_visible(False)
        self.search_entry.set_text(self._last_query)
        self.search_entry.grab_focus()
        self.search_entry.set_position(-1)

    def _leave_search_mode(self):
        self.is_searching = False
        self.sidebar_list.set_sensitive(True)

    def on_search_changed(self, entry):
        if self._navigating:
            return
        search_text = entry.get_text().lower().strip()

        if len(search_text) < 2:
            self._leave_search_mode()
            self._show_single_page(self.current_page_id or self.pages_config[0]["id"])
        else:
            self.is_searching = True
            self.back_to_results.set_visible(False)
            self.sidebar_list.set_sensitive(False)
            self._show_search_results(search_text)

    def _cancel_banner_timeout(self):
        if self._banner_timeout_id is not None:
            GLib.source_remove(self._banner_timeout_id)
            self._banner_timeout_id = None

    def _flush_pending_undo(self):
        """Apply a change still waiting in its undo window right away."""
        pending = self._pending_undo
        if not pending:
            return
        timer_id = pending.get("timer_id")
        if timer_id is not None:
            GLib.source_remove(timer_id)
        self._pending_undo = None
        self.banner.set_revealed(False)
        self._banner_callback = None
        page, switch = pending.get("page"), pending.get("switch")
        if page is not None and switch is not None:
            page._execute_toggle(switch, pending.get("state"))

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
