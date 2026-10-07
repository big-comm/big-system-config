"""Behavioral tests for BaseSettingsPage: script execution, sync and search.

conftest.py replaces gi with MagicMock, which turns BaseSettingsPage itself
into a mock. Here base_page.py is loaded against small widget stubs that model
only what the page logic touches (child/sibling tree, visibility, labels).
"""

import importlib.util
import sys
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "usr/share/biglinux/biglinux-settings/base_page.py"


class Widget:
    def __init__(self, **kwargs):
        self.children = []
        self.parent = None
        self.visible = True
        self.sensitive = True
        self.subtitle = kwargs.get("subtitle", "")

    def append(self, child):
        child.parent = self
        self.children.append(child)

    def remove(self, child):
        self.children.remove(child)
        child.parent = None

    def get_first_child(self):
        return self.children[0] if self.children else None

    def get_next_sibling(self):
        if self.parent is None:
            return None
        siblings = self.parent.children
        index = siblings.index(self)
        return siblings[index + 1] if index + 1 < len(siblings) else None

    def set_visible(self, visible):
        self.visible = visible

    def set_sensitive(self, sensitive):
        self.sensitive = sensitive

    def set_tooltip_text(self, _text):
        pass

    def get_subtitle(self):
        return self.subtitle

    def set_subtitle(self, subtitle):
        self.subtitle = subtitle

    def add_suffix(self, widget):
        self.append(widget)

    def update_property(self, *_args):
        pass

    def add_css_class(self, name):
        self.__dict__.setdefault("css", set()).add(name)

    def remove_css_class(self, name):
        self.__dict__.setdefault("css", set()).discard(name)

    def has_css_class(self, name):
        return name in self.__dict__.get("css", set())


class Label(Widget):
    def __init__(self, text):
        super().__init__()
        self.text = text

    def get_text(self):
        return self.text

    def get_label(self):
        return self.text


class ListBox(Widget):
    pass


class Revealer(Widget):
    pass


class ListBoxRow(Widget):
    pass


class PreferencesRow(Widget):
    pass


class ActionRow(PreferencesRow):
    def __init__(self, title="", subtitle=""):
        super().__init__(subtitle=subtitle)
        self.title = title
        self.append(Label(title))
        if subtitle:
            self.append(Label(subtitle))

    def get_title(self):
        return self.title


class ExpanderRow(PreferencesRow):
    """Mirrors libadwaita 1.x: Box > [ListBox > header, Revealer > ListBox]."""

    def __init__(self, title="", subtitle=""):
        super().__init__(subtitle=subtitle)
        self.title = title
        box = Widget()
        header_list = ListBox()
        header_list.append(ActionRow(title, subtitle))
        self.revealer = Revealer()
        self.rows = ListBox()
        self.revealer.append(self.rows)
        box.append(header_list)
        box.append(self.revealer)
        self.append(box)

    def get_title(self):
        return self.title

    def add_row(self, row):
        self.rows.append(row)


class PreferencesGroup(Widget):
    def __init__(self):
        super().__init__()
        self.listbox = ListBox()
        self.append(self.listbox)
        self.description = ""

    def get_description(self):
        return self.description

    def set_description(self, description):
        self.description = description

    def get_header_suffix(self):
        return None

    def add(self, row):
        self.listbox.append(row)


class Switch(Widget):
    def __init__(self, active=False):
        super().__init__()
        self.active = active
        self.state = active

    def handler_block_by_func(self, _handler):
        pass

    def handler_unblock_by_func(self, _handler):
        pass

    def set_active(self, active):
        self.active = active

    def set_state(self, state):
        self.state = state

    def get_active(self):
        return self.active

    def get_state(self):
        return self.state


class Spinner(Widget):
    pass


class Button(Widget):
    def __init__(self, **kwargs):
        super().__init__()
        self.kwargs = kwargs
        self.callbacks = []

    def connect(self, _signal, callback):
        self.callbacks.append(callback)

    def set_tooltip_text(self, _text):
        pass

    def click(self):
        for callback in self.callbacks:
            callback(self)


class StubNamespace(types.SimpleNamespace):
    """gi.repository stand-in: names the tests do not model become mocks.

    Python < 3.14 evaluates annotations such as ``-> Gtk.Box`` when a
    function is defined, so every name used there must resolve.
    """

    def __getattr__(self, name):
        return MagicMock(name=name)


@pytest.fixture
def base_page(monkeypatch):
    gtk = StubNamespace(
        Box=Widget,
        Widget=Widget,
        Label=Label,
        ListBox=ListBox,
        ListBoxRow=ListBoxRow,
        Revealer=Revealer,
        Switch=Switch,
        Spinner=Spinner,
        Button=Button,
        Align=types.SimpleNamespace(CENTER=0),
        AccessibleProperty=types.SimpleNamespace(DESCRIPTION=0, LABEL=1),
    )
    adw = StubNamespace(
        Bin=Widget,
        ActionRow=ActionRow,
        ExpanderRow=ExpanderRow,
        PreferencesRow=PreferencesRow,
        PreferencesGroup=PreferencesGroup,
        ApplicationWindow=Widget,
    )
    # Run idle callbacks right away: the tests drive the threads synchronously.
    glib = types.SimpleNamespace(
        idle_add=lambda func, *args: func(*args),
        timeout_add=MagicMock(return_value=1),
    )
    repository = types.SimpleNamespace(Adw=adw, Gtk=gtk, GLib=glib, Gio=MagicMock())
    gi = types.SimpleNamespace(require_version=lambda *_args: None, repository=repository)
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)

    spec = importlib.util.spec_from_file_location("base_page_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def page(base_page):
    main_window = MagicMock()
    return base_page.BaseSettingsPage(main_window)


def write_script(path: Path, body: str) -> str:
    path.write_bytes(b"#!/bin/bash\n" + body.encode())
    path.chmod(0o755)
    return str(path)


# --- script execution -------------------------------------------------------


def test_check_parses_states(page, tmp_path):
    for output, expected in [
        ("true", True),
        ("false", False),
        ("TRUE\n", True),
        ("true_disabled", "true_disabled"),
        ("unsupported", None),
        # Could not be read: reported as an error, not as "unsupported"
        ("", "error"),
        ("garbage", "error"),
    ]:
        script = write_script(tmp_path / "s.sh", f'printf "%s" "{output}"\n')
        status, _message = page.check_script_state(script)
        assert status == expected, output


def test_check_survives_non_utf8_output(page, tmp_path):
    script = write_script(tmp_path / "s.sh", "printf 'true\\xff\\xfe'\n")
    status, _message = page.check_script_state(script)
    assert status == "error"


def test_check_does_not_wait_on_inherited_stdin(page, tmp_path):
    # A script that reads stdin must see EOF, not hang until the 10 s timeout.
    script = write_script(tmp_path / "s.sh", "read -r _ignored; echo true\n")
    status, _message = page.check_script_state(script)
    assert status is True


def test_check_nonzero_exit_is_an_error(page, tmp_path):
    script = write_script(tmp_path / "s.sh", "echo true; exit 3\n")
    assert page.check_script_state(script)[0] == "error"


def test_check_missing_script(page, tmp_path):
    assert page.check_script_state(str(tmp_path / "missing.sh"))[0] is None


def test_toggle_verifies_new_state(page, tmp_path, monkeypatch):
    state_file = tmp_path / "state"
    state_file.write_text("false")
    script = write_script(
        tmp_path / "s.sh",
        f'if [ "$1" = toggle ]; then echo "$2" > "{state_file}"; '
        f'else cat "{state_file}"; fi\n',
    )
    assert page.toggle_script_state(script, True) is True
    assert state_file.read_text().strip() == "true"


def test_toggle_fails_when_state_does_not_change(page, tmp_path, monkeypatch):
    monkeypatch.setattr(page.__class__, "check_script_state", lambda *_: (False, ""))
    import time

    monkeypatch.setattr(time, "sleep", lambda *_: None)
    script = write_script(tmp_path / "s.sh", "exit 0\n")
    assert page.toggle_script_state(script, True) is False


def test_toggle_failure_with_binary_stderr(page, tmp_path):
    script = write_script(tmp_path / "s.sh", "printf '\\xff' >&2; exit 1\n")
    assert page.toggle_script_state(script, True) is False


# --- toggle lifecycle -------------------------------------------------------


class SyncThread:
    """threading.Thread replacement that runs the target inline."""

    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


def make_switch_row(page, script="x.sh"):
    switch = Switch()
    row = ActionRow("Title", "Subtitle")
    row.append(switch)
    page.switch_scripts[switch] = script
    page._set_wd(switch, "row", row)
    return switch, row


def test_toggle_exception_restores_row_and_resyncs(page, base_page, monkeypatch):
    monkeypatch.setattr(base_page, "threading", types.SimpleNamespace(Thread=SyncThread))
    switch, row = make_switch_row(page)
    page.sync_all_switches_async = MagicMock()

    def boom(*_args, **_kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    page.toggle_script_state = boom
    page._execute_toggle(switch, True)

    assert row.sensitive is True
    assert switch.visible is True
    assert not any(isinstance(child, Spinner) for child in row.children)
    assert row.get_subtitle() == "Subtitle"
    assert switch.active is False  # reverted
    assert switch not in page._busy_switches
    page.main_window.show_toast.assert_called_once()
    page.sync_all_switches_async.assert_called_once()


def test_toggle_success_keeps_state_and_resyncs(page, base_page, monkeypatch):
    monkeypatch.setattr(base_page, "threading", types.SimpleNamespace(Thread=SyncThread))
    switch, row = make_switch_row(page)
    page.sync_all_switches_async = MagicMock()
    page.toggle_script_state = lambda *_args, **_kwargs: True

    page._execute_toggle(switch, True)

    assert switch.active is True
    assert row.sensitive is True
    page.main_window.show_toast.assert_not_called()
    page.sync_all_switches_async.assert_called_once()


def test_sync_does_not_touch_switch_with_running_toggle(page, base_page, monkeypatch):
    switch, row = make_switch_row(page)
    started = threading.Event()
    release = threading.Event()

    def slow_toggle(*_args, **_kwargs):
        started.set()
        release.wait(5)
        return True

    page.toggle_script_state = slow_toggle
    page.sync_all_switches_async = MagicMock()
    page._execute_toggle(switch, True)
    assert started.wait(5)

    # A sync started by another switch lands while this toggle still runs.
    page._apply_sync_results(page._sync_generation, [(switch, (False, ""))], [])
    assert row.sensitive is False
    assert any(isinstance(child, Spinner) for child in row.children)

    release.set()
    for _ in range(100):
        if switch not in page._busy_switches:
            break
        threading.Event().wait(0.05)
    assert switch not in page._busy_switches
    assert row.sensitive is True
    assert switch.active is True


def test_sync_applies_to_idle_switch(page):
    switch, row = make_switch_row(page)
    page._apply_sync_results(page._sync_generation, [(switch, (True, ""))], [])
    assert switch.active is True

    page._apply_sync_results(page._sync_generation, [(switch, (None, ""))], [])
    assert row.visible is False
    assert page._get_wd(row, "hidden_no_support") is True


def test_stale_sync_generation_is_ignored(page):
    switch, _row = make_switch_row(page)
    stale = page._sync_generation
    page._sync_generation += 1
    page._apply_sync_results(stale, [(switch, (True, ""))], [])
    assert switch.active is False


def test_sync_thread_error_is_contained(page, base_page, monkeypatch):
    monkeypatch.setattr(base_page, "threading", types.SimpleNamespace(Thread=SyncThread))
    switch, _row = make_switch_row(page)

    def boom(_path):
        raise ValueError("bad output")

    page.check_script_state = boom
    done = MagicMock()
    page.sync_all_switches_async(on_done=done)  # must not raise
    # Callers (search) still learn the sync is over
    done.assert_called_once()


# --- search -----------------------------------------------------------------


def build_search_page(page):
    group = PreferencesGroup()
    group.add(ActionRow("Bluetooth", "Enable bluetooth"))
    expander = ExpanderRow("Ollama", "Local AI server")
    vulkan = ActionRow("Vulkan", "Runs on any GPU")
    cuda = ActionRow("Nvidia", "CUDA build")
    unsupported = ActionRow("AMD", "ROCm build")
    page._set_wd(unsupported, "hidden_no_support", True)
    for row in (vulkan, cuda, unsupported):
        expander.add_row(row)
    group.add(expander)
    content = Widget()
    content.append(group)
    page.content_box = content
    return vulkan, cuda, unsupported


def test_search_finds_rows_inside_expander(page):
    vulkan, _cuda, _unsupported = build_search_page(page)
    rows = [row for row, _group in page.get_matching_rows("vulkan")]
    assert rows == [vulkan]


def test_search_on_expander_title_lists_supported_children(page):
    vulkan, cuda, unsupported = build_search_page(page)
    rows = [row for row, _group in page.get_matching_rows("ollama")]
    assert rows == [vulkan, cuda]
    assert unsupported not in rows


def test_search_skips_hidden_unsupported_children(page):
    build_search_page(page)
    assert page.get_matching_rows("rocm") == []


def test_search_top_level_rows_still_work(page):
    build_search_page(page)
    rows = [row.get_title() for row, _group in page.get_matching_rows("blue")]
    assert rows == ["Bluetooth"]


# --- sync completion, groups, undo ---------------------------------------------


def test_sync_calls_on_done_even_when_stale(page):
    done = MagicMock()
    stale = page._sync_generation
    page._sync_generation += 1
    page._apply_sync_results(stale, [], [], done)
    done.assert_called_once()


def test_sync_async_reports_completion(page, base_page, monkeypatch):
    monkeypatch.setattr(base_page, "threading", types.SimpleNamespace(Thread=SyncThread))
    switch, _row = make_switch_row(page)
    page.check_script_state = lambda _path: (True, "")
    done = MagicMock()
    page.sync_all_switches_async(on_done=done)
    done.assert_called_once()
    assert switch.active is True


def make_group_page(page, statuses):
    group = PreferencesGroup()
    content = Widget()
    content.append(group)
    page.content_box = content
    results = []
    for status in statuses:
        switch, row = make_switch_row(page)
        group.add(row)
        results.append((switch, (status, "")))
    return group, results


def test_group_with_only_unsupported_rows_is_hidden(page):
    group, results = make_group_page(page, [None, None])
    page._apply_sync_results(page._sync_generation, results, [])
    assert group.visible is False
    # Leaving search mode must not bring the empty header back
    page.filter_rows("")
    assert group.visible is False


def test_group_with_a_supported_row_stays_visible(page):
    group, results = make_group_page(page, [None, False])
    page._apply_sync_results(page._sync_generation, results, [])
    assert group.visible is True


def test_reclick_inside_undo_window_does_not_queue_a_toggle(page, base_page):
    switch, _row = make_switch_row(page)
    # First click (off -> on) is pending: active moved, state did not.
    switch.active = True
    page.main_window._pending_undo = {"switch": switch, "state": True, "page": page}
    base_page.GLib.timeout_add.reset_mock()

    assert page.on_switch_changed(switch, False) is True

    page.main_window._cancel_pending_undo.assert_called_once_with(revert=True)
    base_page.GLib.timeout_add.assert_not_called()


def test_banner_uses_translated_title(page, base_page):
    switch, row = make_switch_row(page)
    row.title = "Recent Files &amp; Locations"
    page.main_window._pending_undo = None
    page.on_switch_changed(switch, True)
    title = page.main_window.banner.set_title.call_args[0][0]
    assert "Recent Files &amp; Locations" in title
    assert "x.sh" not in title and "&amp;amp;" not in title


def test_offline_local_ip_is_not_cached(base_page, monkeypatch):
    class OfflineSocket:
        def __init__(self, *_args):
            pass

        def settimeout(self, _timeout):
            pass

        def connect(self, _address):
            raise OSError("network unreachable")

        def close(self):
            pass

    monkeypatch.setattr(base_page.socket, "socket", OfflineSocket)
    base_page.BaseSettingsPage._cached_local_ip = None
    assert base_page.BaseSettingsPage.get_local_ip() == "127.0.0.1"
    assert base_page.BaseSettingsPage._cached_local_ip is None


# --- redesign: inverted rows, errors, undo flush, search metadata -------------


def test_inverted_row_shows_the_opposite_of_the_script(page):
    switch, _row = make_switch_row(page)
    page._set_wd(switch, "inverted", True)
    # "disableVisualEffects" check prints true = effects are off
    page._apply_sync_results(page._sync_generation, [(switch, (True, ""))], [])
    assert switch.active is False
    page._apply_sync_results(page._sync_generation, [(switch, (False, ""))], [])
    assert switch.active is True


def test_inverted_row_sends_the_script_its_own_state(page, base_page, monkeypatch):
    monkeypatch.setattr(base_page, "threading", types.SimpleNamespace(Thread=SyncThread))
    switch, _row = make_switch_row(page)
    page._set_wd(switch, "inverted", True)
    page.sync_all_switches_async = MagicMock()
    sent = []
    page.toggle_script_state = lambda _path, state, **_kw: sent.append(state) or True

    page._execute_toggle(switch, True)  # user turns "Visual effects" on

    assert sent == [False]  # disableVisualEffects toggle false
    assert switch.active is True


def test_check_error_keeps_row_visible_with_retry(page):
    switch, row = make_switch_row(page)
    page.sync_all_switches_async = MagicMock()
    page._apply_sync_results(page._sync_generation, [(switch, ("error", ""))], [])

    assert row.visible is True
    assert page._get_wd(row, "hidden_no_support") is False
    assert switch.sensitive is False
    assert row.has_css_class("row-error")
    retry = page._get_wd(row, "error_retry")
    assert retry is not None and retry in row.children
    retry.click()
    page.sync_all_switches_async.assert_called_once()

    # A later successful check restores the row
    page._apply_sync_results(page._sync_generation, [(switch, (True, ""))], [])
    assert switch.sensitive is True
    assert retry not in row.children
    assert row.get_subtitle() == "Subtitle"
    assert not row.has_css_class("row-error")


def test_unsupported_is_still_hidden(page):
    switch, row = make_switch_row(page)
    page._apply_sync_results(page._sync_generation, [(switch, (None, ""))], [])
    assert row.visible is False


def test_new_change_applies_the_pending_one_instead_of_reverting(page):
    first, _row = make_switch_row(page)
    second, _row2 = make_switch_row(page)
    page.main_window._pending_undo = {"switch": first, "state": True, "page": page}

    page.on_switch_changed(second, True)

    page.main_window._flush_pending_undo.assert_called_once_with()
    page.main_window._cancel_pending_undo.assert_not_called()


def test_restart_note_after_successful_change(page, base_page, monkeypatch):
    monkeypatch.setattr(base_page, "threading", types.SimpleNamespace(Thread=SyncThread))
    switch, _row = make_switch_row(page)
    page._set_wd(switch, "after_restart", True)
    page.sync_all_switches_async = MagicMock()
    page.toggle_script_state = lambda *_a, **_kw: True
    page._execute_toggle(switch, True)
    message = page.main_window.show_toast.call_args[0][0]
    # Compare with the translated text: the suite may run in any locale
    assert message == base_page._("Saved. It will take effect after the next restart.")


def test_search_ignores_accents_and_uses_keywords_and_section(page, base_page):
    group = PreferencesGroup()
    page._set_wd(group, "path_title", "Quando ficar sem usar")
    row = ActionRow("Manter ligado na bateria", "Não suspende por inatividade")
    page._register_search_metadata(row, group, ["não dormir"])
    group.add(row)
    content = Widget()
    content.append(group)
    page.content_box = content

    for query in ("nao dormir", "NÃO DORMIR", "inatividade", "sem usar", "bateria"):
        assert [r for r, _g in page.get_matching_rows(query)] == [row], query
    assert page.get_matching_rows("wifi") == []
    assert page.row_section(row) == "Quando ficar sem usar"


def test_normalize_search_text(base_page):
    assert base_page.normalize_search_text("Não Dormir &amp; Açúcar") == "nao dormir & acucar"


def test_find_switch_by_script_name(page):
    switch, _row = make_switch_row(page, script="system/sshStart.sh")
    assert page.find_switch("sshStart") is switch
    assert page.find_switch("missing") is None
