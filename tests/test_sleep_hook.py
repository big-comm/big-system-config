"""Tests for the root sleep hook config loading and the GNOME handler state."""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "usr/lib/biglinux"
MAIN = LIB_DIR / "sleep/main.py"


@pytest.fixture
def sleep_main(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(LIB_DIR))
    for name in [m for m in sys.modules if m == "sleep" or m.startswith("sleep.")]:
        monkeypatch.delitem(sys.modules, name)
    module = importlib.import_module("sleep.main")
    monkeypatch.setattr(module, "CONFIG_FILE", tmp_path / "sleep.conf")
    return module


def write_conf(module, text):
    module.CONFIG_FILE.write_text(text)


def test_missing_config_disables_everything(sleep_main):
    assert sleep_main._load_config() == {"backlight": False, "network": False}


def test_valid_config(sleep_main):
    write_conf(sleep_main, "[handlers]\nbacklight=true\nnetwork=false\n")
    assert sleep_main._load_config() == {"backlight": True, "network": False}


@pytest.mark.parametrize(
    "text, expected",
    [
        # duplicate key: last one wins instead of DuplicateOptionError
        ("[handlers]\nbacklight=false\nbacklight=true\n", {"backlight": True, "network": False}),
        # inline comment
        ("[handlers]\nbacklight=true # keep\nnetwork=yes ; on\n", {"backlight": True, "network": True}),
        # bad value only disables that key
        ("[handlers]\nbacklight=maybe\nnetwork=true\n", {"backlight": False, "network": True}),
        # no section header at all
        ("backlight=true\n", {"backlight": False, "network": False}),
        # binary garbage
        ("\udcff\udcfe", {"backlight": False, "network": False}),
    ],
)
def test_damaged_config_never_raises(sleep_main, text, expected):
    sleep_main.CONFIG_FILE.write_bytes(text.encode("utf-8", "surrogateescape"))
    assert sleep_main._load_config() == expected


def test_damaged_config_still_runs_hook(sleep_main):
    write_conf(sleep_main, "[handlers]\nbacklight=maybe\nbacklight=true\n[")
    # Unparseable file: nothing is enabled, so no real hardware is touched
    assert sleep_main._load_config() == {"backlight": False, "network": False}
    assert sleep_main.run("pre", "suspend") == 0


@pytest.mark.parametrize("args", [[], ["pre"], ["foo", "suspend"]])
def test_cli_rejects_bad_phase(args):
    result = subprocess.run(
        [sys.executable, str(MAIN), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(LIB_DIR)},
        timeout=30,
    )
    assert result.returncode == 2


# --- GNOME handler -------------------------------------------------------------


@pytest.fixture
def gnome(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(LIB_DIR))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    for name in [m for m in sys.modules if m == "sleep" or m.startswith("sleep.")]:
        monkeypatch.delitem(sys.modules, name)
    return importlib.import_module("sleep.handlers.gnome")


def test_gnome_state_survives_reboot(gnome, tmp_path):
    # $XDG_RUNTIME_DIR is tmpfs: a pending re-enable stored there is lost if
    # the battery dies during suspend, leaving user-theme disabled for good.
    assert gnome.STATE_FILE.is_relative_to(tmp_path / "state")
    gnome._save_state(["user-theme@gnome-shell-extensions.gcampax.github.com"])
    assert gnome._load_state() == ["user-theme@gnome-shell-extensions.gcampax.github.com"]
    gnome._clear_state()
    assert gnome._load_state() == []


def test_gnome_corrupt_state_is_ignored(gnome):
    gnome.STATE_FILE.parent.mkdir(parents=True)
    gnome.STATE_FILE.write_text("{not json")
    assert gnome._load_state() == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root looks sessions up via loginctl")
def test_gnome_user_monitor_targets_its_own_session(gnome, monkeypatch):
    def no_loginctl(*_args, **_kwargs):
        raise AssertionError("must not pick another user's session")

    monkeypatch.setattr(gnome.subprocess, "check_output", no_loginctl)
    assert gnome._find_gnome_uid() == str(os.getuid())
