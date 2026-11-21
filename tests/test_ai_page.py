"""Test package source selection and the interactive AUR install flow."""

import importlib.util
import sys
from unittest.mock import MagicMock

import pytest

from .test_base_page import ActionRow, MODULE_PATH, Switch
from .test_base_page import base_page as base_page


@pytest.fixture
def ai_page(base_page, monkeypatch):
    monkeypatch.setitem(sys.modules, "base_page", base_page)
    spec = importlib.util.spec_from_file_location(
        "ai_page_under_test", MODULE_PATH.with_name("ai_page.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    page = module.AIPage.__new__(module.AIPage)
    base_page.BaseSettingsPage.__init__(page, MagicMock())
    page._pending_aur_packages = set()
    return module, page


@pytest.mark.parametrize(
    ("script", "state", "exit_code", "stderr", "aur_package"),
    [
        ("lmStudio.sh", True, 1, "error: package 'lmstudio-bin' was not found", "lmstudio-bin"),
        ("ollamaLab.sh", True, 1, "error: package 'ollama-lab-bin' was not found", "ollama-lab-bin"),
        ("chatbox.sh", True, 1, "error: package 'chatbox-bin' was not found", "chatbox-bin"),
        (
            "lmStudio.sh", True, 1,
            "warning: missing database\nerror: package 'lmstudio-bin' was not found\n",
            "lmstudio-bin",
        ),
        (
            "lmStudio.sh", True, 1,
            "error: package 'lmstudio-bin' was not found in the selected repository",
            None,
        ),
        ("lmStudio.sh", True, 0, "", None),
        ("lmStudio.sh", True, 1, "error: failed to initialize alpm library", None),
        ("lmStudio.sh", False, None, None, None),
        ("ollamaCpu.sh", True, None, None, None),
    ],
)
def test_ai_offers_aur_only_for_missing_repository_packages(
    ai_page, monkeypatch, script, state, exit_code, stderr, aur_package
):
    module, page = ai_page
    native_toggle = MagicMock()
    monkeypatch.setattr(module.BaseSettingsPage, "_execute_toggle", native_toggle)
    page._offer_aur_install = MagicMock()
    switch = Switch(active=state)
    row = ActionRow()
    page.switch_scripts[switch] = f"ai/{script}"
    page._set_wd(switch, "row", row)
    launcher = module.Gio.SubprocessLauncher.new.return_value
    query = launcher.spawnv.return_value

    page._execute_toggle(switch, state)
    if exit_code is None:
        launcher.spawnv.assert_not_called()
    else:
        launcher.spawnv.assert_called_once_with(
            ["pacman", "-Si", "--", module.AUR_PACKAGES[script]]
        )
        assert not row.sensitive
        assert switch in page._busy_switches
        # A window closed during the lookup waits for it instead of quitting.
        window = page.main_window
        window.change_started.assert_called_once_with()
        native_toggle.side_effect = lambda *_: window.change_finished.assert_not_called()
        query.communicate_utf8_finish.return_value = (True, None, stderr)
        query.get_if_exited.return_value = True
        query.get_exit_status.return_value = exit_code
        callback = query.communicate_utf8_async.call_args.args[2]
        callback(query, None)
        assert row.sensitive
        assert switch not in page._busy_switches
        window.change_finished.assert_called_once_with()

    if aur_package:
        page._offer_aur_install.assert_called_once_with(aur_package)
        native_toggle.assert_not_called()
        assert not switch.get_active()
        assert not switch.get_state()
    else:
        page._offer_aur_install.assert_not_called()
        native_toggle.assert_called_once_with(switch, state)


@pytest.fixture
def aur_dialog(ai_page, monkeypatch):
    module, _page = ai_page
    module.Adw.AlertDialog = MagicMock()
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000)
    return module.Adw.AlertDialog.return_value


@pytest.mark.parametrize("has_yay", [True, False])
def test_ai_aur_install_requires_confirmation(ai_page, aur_dialog, monkeypatch, has_yay):
    module, page = ai_page
    monkeypatch.setattr(
        module.GLib,
        "find_program_in_path",
        lambda name: None if name == "yay" and not has_yay else f"/usr/bin/{name}",
        raising=False,
    )
    page._offer_aur_install("lmstudio-bin")
    respond = aur_dialog.connect.call_args.args[1]

    respond(aur_dialog, "cancel")
    module.Gio.Subprocess.new.assert_not_called()
    assert not page._pending_aur_packages

    respond(aur_dialog, "install")
    helper = "/usr/bin/yay" if has_yay else "/usr/bin/paru"
    module.Gio.Subprocess.new.assert_called_once_with(
        [
            "/usr/bin/xdg-terminal-exec", "--hold", "--", helper, "-S",
            "--aur", "--needed", "--", "lmstudio-bin",
        ],
        module.Gio.SubprocessFlags.NONE,
    )
    terminal = module.Gio.Subprocess.new.return_value
    terminal.wait_check_async.assert_not_called()
    page.main_window.show_toast.assert_not_called()
    assert page._pending_aur_packages == {"lmstudio-bin"}


def test_ai_reports_terminal_start_failure(ai_page, aur_dialog, monkeypatch):
    module, page = ai_page
    monkeypatch.setattr(
        module.GLib, "find_program_in_path", lambda name: f"/usr/bin/{name}", raising=False
    )
    monkeypatch.setattr(module.GLib, "Error", RuntimeError, raising=False)
    module.Gio.Subprocess.new.side_effect = RuntimeError("launch failed")

    page._offer_aur_install("lmstudio-bin")
    aur_dialog.connect.call_args.args[1](aur_dialog, "install")

    page.main_window.show_toast.assert_called_once_with(
        module._("Could not open a terminal to install {}.").format("lmstudio-bin")
    )
    assert not page._pending_aur_packages


def test_ai_refreshes_on_focus_until_pending_packages_are_installed(ai_page, monkeypatch):
    module, page = ai_page
    window = page.main_window
    window.is_active.return_value = True
    page.sync_all_switches_async = MagicMock()
    monkeypatch.setattr(module.BaseSettingsPage, "_apply_switch_result", MagicMock())

    page._refresh_after_external_install(window, None)
    page.sync_all_switches_async.assert_not_called()

    page._pending_aur_packages.update(("lmstudio-bin", "chatbox-bin"))
    window.is_active.return_value = False
    page._refresh_after_external_install(window, None)
    page.sync_all_switches_async.assert_not_called()

    window.is_active.return_value = True
    page._refresh_after_external_install(window, None)
    page.sync_all_switches_async.assert_called_once_with()

    lm_studio = Switch()
    chatbox = Switch()
    page.switch_scripts[lm_studio] = "ai/lmStudio.sh"
    page.switch_scripts[chatbox] = "ai/chatbox.sh"
    page._apply_current_sync_results(
        [(lm_studio, (True, None)), (chatbox, (False, None))], []
    )
    assert page._pending_aur_packages == {"chatbox-bin"}

    page._refresh_after_external_install(window, None)
    assert page.sync_all_switches_async.call_count == 2
    page._apply_current_sync_results([(chatbox, (True, None))], [])
    assert not page._pending_aur_packages

    page._refresh_after_external_install(window, None)
    assert page.sync_all_switches_async.call_count == 2


def test_ai_aur_install_explains_missing_helper(ai_page, monkeypatch):
    module, page = ai_page
    monkeypatch.setattr(
        module.GLib, "find_program_in_path", lambda _name: None, raising=False
    )
    page._show_info_dialog = MagicMock()

    page._offer_aur_install("chatbox-bin")

    title, message = page._show_info_dialog.call_args.args
    assert "AUR" in title
    assert "chatbox-bin" in message
    module.Gio.Subprocess.new.assert_not_called()
