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


class Spinner(Widget):
    pass


@pytest.fixture
def base_page(monkeypatch):
    gtk = types.SimpleNamespace(
        Widget=Widget,
        Label=Label,
        ListBox=ListBox,
        ListBoxRow=ListBoxRow,
        Revealer=Revealer,
        Switch=Switch,
        Spinner=Spinner,
        Align=types.SimpleNamespace(CENTER=0),
        AccessibleProperty=types.SimpleNamespace(DESCRIPTION=0, LABEL=1),
    )
    adw = types.SimpleNamespace(
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
        ("", None),
        ("garbage", None),
    ]:
        script = write_script(tmp_path / "s.sh", f'printf "%s" "{output}"\n')
        status, _message = page.check_script_state(script)
        assert status == expected, output


def test_check_survives_non_utf8_output(page, tmp_path):
    script = write_script(tmp_path / "s.sh", "printf 'true\\xff\\xfe'\n")
    status, _message = page.check_script_state(script)
    assert status is None


def test_check_does_not_wait_on_inherited_stdin(page, tmp_path):
    # A script that reads stdin must see EOF, not hang until the 10 s timeout.
    script = write_script(tmp_path / "s.sh", "read -r _ignored; echo true\n")
    status, _message = page.check_script_state(script)
    assert status is True


def test_check_nonzero_exit_is_unavailable(page, tmp_path):
    script = write_script(tmp_path / "s.sh", "echo true; exit 3\n")
    assert page.check_script_state(script)[0] is None


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
    monkeypatch.setattr(base_page.threading, "Thread", SyncThread)
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
    monkeypatch.setattr(base_page.threading, "Thread", SyncThread)
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
    monkeypatch.setattr(base_page.threading, "Thread", SyncThread)
    switch, _row = make_switch_row(page)

    def boom(_path):
        raise ValueError("bad output")

    page.check_script_state = boom
    page.sync_all_switches_async()  # must not raise


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
