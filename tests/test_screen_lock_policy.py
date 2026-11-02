"""Tests for the "don't lock the screen" sub-option of the lid policy."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SLEEP_DIR = ROOT / "usr/share/biglinux/biglinux-settings/sleep"
MODULE_PATH = SLEEP_DIR / "screen_lock_policy.py"


@pytest.fixture
def policy_module(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("screen_lock_policy", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "CONFIG_DIR", tmp_path / "config")
    return module


def fake_xfconf(values):
    def run(command, check=True):
        channel = command[command.index("-c") + 1]
        key = (channel, command[command.index("-p") + 1])
        if "-s" in command:
            values[key] = command[-1]
            return subprocess.CompletedProcess(command, 0, "", "")
        if "-r" in command:
            values.pop(key, None)
            return subprocess.CompletedProcess(command, 0, "", "")
        if key not in values:
            return subprocess.CompletedProcess(command, 1, "", "missing")
        return subprocess.CompletedProcess(command, 0, values[key] + "\n", "")

    return run


def test_xfce_unlock_restores_previous_values(policy_module, monkeypatch):
    screensaver, power = policy_module.XFCE_KEYS
    # The power manager key is unset: it must be removed again, not left false
    values = {screensaver: "true"}
    monkeypatch.setattr(policy_module, "run", fake_xfconf(values))

    assert policy_module.enable("xfce") == 0
    assert values == {screensaver: "false", power: "false"}
    assert policy_module.is_unlocked("xfce")

    assert policy_module.disable() == 0
    assert values == {screensaver: "true"}
    assert not policy_module.is_unlocked("xfce")


def test_enabling_twice_keeps_the_original_backup(policy_module, monkeypatch):
    screensaver, power = policy_module.XFCE_KEYS
    values = {screensaver: "true", power: "true"}
    monkeypatch.setattr(policy_module, "run", fake_xfconf(values))

    policy_module.enable("xfce")
    policy_module.enable("xfce")
    policy_module.disable()

    assert values == {screensaver: "true", power: "true"}


def test_gnome_unlock_also_blocks_the_lid_close_lock(policy_module, monkeypatch):
    # gsd-power locks on lid close through the shell's Lock(), which ignores
    # lock-enabled and only honours the lockdown key.
    monkeypatch.setattr(
        policy_module, "gsettings_keys", lambda: policy_module.GSETTINGS_KEYS["gnome"]
    )
    values = {"lock-enabled": "true", "disable-lock-screen": "false"}

    def run(command, check=True):
        if command[1] == "set":
            values[command[3]] = command[4]
        return subprocess.CompletedProcess(command, 0, values[command[3]] + "\n", "")

    monkeypatch.setattr(policy_module, "run", run)
    assert not policy_module.is_unlocked("gsettings")
    assert policy_module.enable("gsettings") == 0
    assert values == {"lock-enabled": "false", "disable-lock-screen": "true"}
    assert policy_module.is_unlocked("gsettings")

    values["disable-lock-screen"] = "false"
    assert not policy_module.is_unlocked("gsettings")

    assert policy_module.disable() == 0
    assert values == {"lock-enabled": "true", "disable-lock-screen": "false"}


def test_without_a_supported_desktop_nothing_is_enabled(policy_module):
    assert not policy_module.is_unlocked(None)
    assert policy_module.enable(None) == 1


@pytest.fixture
def lid_wrapper(tmp_path):
    """never-suspend-lid-ac.sh next to fake policy scripts that log their calls."""
    log = tmp_path / "calls"
    for name in ("lid_policy.py", "screen_lock_policy.py"):
        fake = tmp_path / name
        fake.write_text(f'#!/bin/bash\necho "{name} $*" >> "{log}"\n')
        fake.chmod(0o755)
    shutil.copy(SLEEP_DIR / "never-suspend-lid-ac.sh", tmp_path)

    def run(*args):
        subprocess.run([str(tmp_path / "never-suspend-lid-ac.sh"), *args], check=True)
        return log.read_text().splitlines()

    return run


def test_turning_lid_policy_off_restores_the_screen_lock(lid_wrapper):
    assert lid_wrapper("toggle", "false") == [
        "lid_policy.py toggle ac false",
        "screen_lock_policy.py toggle false",
    ]


def test_turning_lid_policy_on_leaves_the_screen_lock_alone(lid_wrapper):
    assert lid_wrapper("toggle", "true") == ["lid_policy.py toggle ac true"]
