"""Behavioral tests for the sleep handlers, the user monitor and the sleep toggles.

Python handlers run against fake sysfs trees in tmp_path. Shell toggles run for
real with fake tools on PATH; the root helpers that write under /etc run inside
an unprivileged user+mount namespace with temporary directories bind-mounted
over the real ones, so nothing on the host is touched.
"""

import configparser
import fcntl
import importlib
import json
import os
import shlex
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "usr/lib/biglinux"
SLEEP_SCRIPTS = ROOT / "usr/share/biglinux/biglinux-settings/sleep"


def _fresh_import(monkeypatch, name):
    monkeypatch.syspath_prepend(str(LIB_DIR))
    for mod in [m for m in sys.modules if m == "sleep" or m.startswith("sleep.")]:
        monkeypatch.delitem(sys.modules, mod)
    return importlib.import_module(name)


# --- user monitor: logind delay inhibitor ----------------------------------------


class _FakeResult:
    def unpack(self):
        return (0,)


class _FakeFdList:
    def __init__(self, fd):
        self.fd = fd

    def get(self, _index):
        return os.dup(self.fd)


class _FakeSystemBus:
    def __init__(self, fail=False):
        self.fail = fail
        self.inhibit_calls = []
        self._pipes = []

    def call_with_unix_fd_list_sync(self, *args):
        self.inhibit_calls.append(args[:4])
        if self.fail:
            raise RuntimeError("Access denied")
        read_end, write_end = os.pipe()
        self._pipes += [read_end, write_end]
        return _FakeResult(), _FakeFdList(read_end)

    def close(self):
        for fd in self._pipes:
            os.close(fd)


def _fd_is_open(fd):
    try:
        os.fstat(fd)
    except OSError:
        return False
    return True


@pytest.fixture
def monitor(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    module = _fresh_import(monkeypatch, "sleep.monitor")
    yield module
    if module._inhibit_fd is not None:
        os.close(module._inhibit_fd)
        module._inhibit_fd = None


@pytest.fixture
def system_bus(monitor, monkeypatch):
    bus = _FakeSystemBus()
    monkeypatch.setattr(monitor, "_system_bus", bus)
    yield bus
    bus.close()


def _prepare_for_sleep(monitor, going_to_sleep):
    monitor._on_prepare_for_sleep(None, None, None, None, None, (going_to_sleep,), None)


def test_monitor_holds_delay_inhibitor_until_pre_suspend_ran(monitor, system_bus, monkeypatch):
    seen = []

    class Handler:
        def pre_suspend(self, _sleep_type):
            seen.append(_fd_is_open(monitor._inhibit_fd))

    monkeypatch.setattr(monitor, "GnomeHandler", Handler)
    assert monitor._take_inhibitor() is True
    fd = monitor._inhibit_fd
    assert system_bus.inhibit_calls[0][2:] == ("org.freedesktop.login1.Manager", "Inhibit")

    _prepare_for_sleep(monitor, True)
    # pre_suspend ran while logind was still waiting on us; then the lock is gone
    assert seen == [True]
    assert monitor._inhibit_fd is None
    assert not _fd_is_open(fd)

    _prepare_for_sleep(monitor, False)
    # re-armed for the next suspend
    assert len(system_bus.inhibit_calls) == 2
    assert monitor._inhibit_fd is not None and _fd_is_open(monitor._inhibit_fd)


def test_monitor_releases_inhibitor_even_if_pre_suspend_crashes(monitor, system_bus, monkeypatch):
    class Handler:
        def pre_suspend(self, _sleep_type):
            raise RuntimeError("boom")

    monkeypatch.setattr(monitor, "GnomeHandler", Handler)
    monitor._take_inhibitor()
    fd = monitor._inhibit_fd
    _prepare_for_sleep(monitor, True)
    assert monitor._inhibit_fd is None
    assert not _fd_is_open(fd)


def test_monitor_works_without_inhibitor(monitor, monkeypatch):
    bus = _FakeSystemBus(fail=True)
    monkeypatch.setattr(monitor, "_system_bus", bus)
    calls = []

    class Handler:
        def pre_suspend(self, sleep_type):
            calls.append(sleep_type)

    monkeypatch.setattr(monitor, "GnomeHandler", Handler)
    assert monitor._take_inhibitor() is False
    _prepare_for_sleep(monitor, True)
    _prepare_for_sleep(monitor, False)
    assert calls == ["suspend"]
    assert monitor._inhibit_fd is None


# --- extension health: only real, user-enabled ERROR states ------------------------


HEALTH_CASES = [
    # stale error string but the extension is running fine
    ({"enabled": True, "state": 1, "error": "old failure"}, False),
    # ERROR, but the user disabled it: leave it disabled
    ({"enabled": False, "state": 3, "error": "boom"}, False),
    ({"enabled": False, "state": 2, "error": "boom"}, False),
    ({"enabled": True, "state": 3, "error": "boom"}, True),
]


@pytest.mark.parametrize("info, fixed", HEALTH_CASES)
def test_monitor_health_check_only_fixes_enabled_error(monitor, monkeypatch, info, fixed):
    fixes = []
    monkeypatch.setattr(monitor, "_ext_state", lambda _uid, _uuid: info)
    monkeypatch.setattr(monitor, "_disable_wait_enable", lambda uuid: fixes.append(uuid) or True)
    monitor._check_extensions_health()
    assert bool(fixes) is fixed


@pytest.mark.parametrize("info, fixed", HEALTH_CASES)
def test_gnome_fallback_only_fixes_enabled_error(monkeypatch, tmp_path, info, fixed):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    gnome = _fresh_import(monkeypatch, "sleep.handlers.gnome")
    ops = []
    monkeypatch.setattr(gnome, "_ext_state", lambda _uid, _uuid: info)
    monkeypatch.setattr(gnome, "_disable_extension", lambda _u, uuid: ops.append("off") or True)
    monkeypatch.setattr(gnome, "_enable_extension", lambda _u, uuid: ops.append("on") or True)
    monkeypatch.setattr(gnome.time, "sleep", lambda _s: None)
    gnome.GnomeHandler()._fix_error_state("1000")
    assert ops == (["off", "on"] if fixed else [])


# --- backlight handler --------------------------------------------------------------


def _led(base, name, brightness, max_brightness=1, trigger=None):
    device = base / name
    device.mkdir(parents=True)
    (device / "brightness").write_text(f"{brightness}\n")
    (device / "max_brightness").write_text(f"{max_brightness}\n")
    if trigger is not None:
        (device / "trigger").write_text(trigger + "\n")
    return device


@pytest.fixture
def backlight(monkeypatch, tmp_path):
    module = _fresh_import(monkeypatch, "sleep.handlers.backlight")
    monkeypatch.setattr(module, "BACKLIGHT_DIR", tmp_path / "backlight")
    monkeypatch.setattr(module, "LEDS_DIR", tmp_path / "leds")
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "run/backlight-state.json")
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    return module


def _brightness(device):
    return int((device / "brightness").read_text())


def test_backlight_only_handles_screens_and_keyboard_backlight(backlight, tmp_path):
    screen = _led(tmp_path / "backlight", "intel_backlight", 400, 1000)
    kbd = _led(tmp_path / "leds", "asus::kbd_backlight", 2, 3, "[none] kbd-scrolllock")
    caps = _led(tmp_path / "leds", "input3::capslock", 1, 1, "none [kbd-capslock]")
    mic = _led(tmp_path / "leds", "platform::micmute", 1, 1, "none [audio-micmute]")
    timer_kbd = _led(tmp_path / "leds", "dell::kbd_backlight", 1, 2, "none [timer]")

    handler = backlight.BacklightHandler()
    handler.pre_suspend("suspend")
    saved = json.loads(backlight.STATE_FILE.read_text())
    assert set(saved) == {str(screen), str(kbd)}
    assert _brightness(kbd) == 0  # ASUS EC workaround

    # resume: firmware reset everything, caps lock got toggled meanwhile
    for device, value in ((screen, 0), (caps, 0), (mic, 0), (timer_kbd, 0)):
        (device / "brightness").write_text(f"{value}\n")
    handler.post_resume("suspend")

    assert _brightness(screen) == 400
    assert _brightness(kbd) == 2
    # LEDs owned by the kernel/triggers are never written
    assert _brightness(caps) == 0
    assert _brightness(mic) == 0
    assert _brightness(timer_kbd) == 0


def test_backlight_ignores_foreign_leds_in_old_state_file(backlight, tmp_path):
    caps = _led(tmp_path / "leds", "input3::capslock", 0, 1, "[kbd-capslock]")
    backlight.STATE_FILE.parent.mkdir(parents=True)
    backlight.STATE_FILE.write_text(json.dumps({str(caps): 1}))
    backlight.BacklightHandler().post_resume("suspend")
    assert _brightness(caps) == 0


def test_backlight_does_not_zero_triggered_asus_led(backlight, tmp_path):
    kbd = _led(tmp_path / "leds", "asus::kbd_backlight", 2, 3, "none [timer]")
    backlight.BacklightHandler().pre_suspend("suspend")
    assert _brightness(kbd) == 2


# --- network handler ------------------------------------------------------------------


BRIDGE = "0000:00:1c.0"
WIFI = "0000:01:00.0"


@pytest.fixture
def network(monkeypatch, tmp_path):
    module = _fresh_import(monkeypatch, "sleep.handlers.network")
    real_bridge = tmp_path / "devices/pci0000:00" / BRIDGE
    real_wifi = real_bridge / WIFI
    real_wifi.mkdir(parents=True)
    (real_bridge / "d3cold_allowed").write_text("1\n")
    (real_wifi / "d3cold_allowed").write_text("1\n")
    (real_wifi / "power_state").write_text("D0\n")
    bus = tmp_path / "bus"
    bus.mkdir()
    (bus / BRIDGE).symlink_to(real_bridge)
    (bus / WIFI).symlink_to(real_wifi)

    monkeypatch.setattr(module, "_PCI_DEVICES", bus)
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "run/network-state.json")
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        module, "_fallback_recovery", lambda *_a: pytest.fail("unexpected recovery")
    )

    handler = module.NetworkHandler()
    handler._module, handler._pci_slot = "rtw89_8852be", WIFI
    module.handler = handler
    module.d3cold = lambda slot: (bus / slot / "d3cold_allowed").read_text().strip()
    module.set_d3cold = lambda slot, v: (bus / slot / "d3cold_allowed").write_text(v)
    return module


def test_network_restores_original_d3cold_values(network):
    network.set_d3cold(WIFI, "0")  # pinned by the user / another tool

    network.handler.pre_suspend("suspend")
    assert (network.d3cold(WIFI), network.d3cold(BRIDGE)) == ("0", "0")

    network.handler.post_resume("suspend")
    assert (network.d3cold(WIFI), network.d3cold(BRIDGE)) == ("0", "1")
    assert not network.STATE_FILE.exists()


def test_network_repeated_pre_suspend_keeps_first_originals(network):
    network.handler.pre_suspend("suspend")
    # second pre without a post in between: sysfs now holds our own "0"
    network.handler.pre_suspend("suspend")
    network.handler.post_resume("suspend")
    assert (network.d3cold(WIFI), network.d3cold(BRIDGE)) == ("1", "1")


def test_network_restores_after_fallback_recovery(network, monkeypatch):
    network.set_d3cold(BRIDGE, "0")
    network.handler.pre_suspend("suspend")
    (network._PCI_DEVICES / WIFI / "power_state").write_text("D3cold\n")
    recovered = []
    monkeypatch.setattr(network, "_fallback_recovery", lambda *a: recovered.append(a))
    network.handler.post_resume("suspend")
    assert recovered
    assert (network.d3cold(WIFI), network.d3cold(BRIDGE)) == ("1", "0")


# --- shell toggles ------------------------------------------------------------------------


FAKES = {
    "_log": """
        printf '%s %s\\n' "$(basename "$0")" "$*" >> "$FAKE_STATE/calls.log"
    """,
    "id": """
        case "$1" in
          -u) echo "${FAKE_UID:-0}" ;;
          -nu) echo tester ;;
          *) exec /usr/bin/id "$@" ;;
        esac
    """,
    "pkexec": """
        . "$FAKE_BIN/_log"
        exit "${FAKE_PKEXEC_RC:-0}"
    """,
    "systemctl": """
        . "$FAKE_BIN/_log"
        case "$*" in
          *--global*) exit "${FAKE_SYSTEMCTL_GLOBAL_RC:-0}" ;;
          *--user*) exit "${FAKE_SYSTEMCTL_USER_RC:-0}" ;;
          *try-restart*) exit "${FAKE_SYSTEMCTL_RESTART_RC:-0}" ;;
        esac
        exit 0
    """,
    # Mimics logind: last value from the drop-ins wins; HandleLidSwitch
    # defaults to suspend, HandleLidSwitchExternalPower is unset ("").
    "busctl": """
        prop="${@: -1}"
        value=""
        [ "$prop" = HandleLidSwitch ] && value=suspend
        for file in /etc/systemd/logind.conf.d/*.conf; do
          [ -f "$file" ] || continue
          line="$(grep "^$prop=" "$file" | tail -1)"
          [ -n "$line" ] && value="${line#*=}"
        done
        printf 's "%s"\\n' "$value"
    """,
    "chmod": """
        [ -n "${FAKE_CHMOD_RC:-}" ] && exit "$FAKE_CHMOD_RC"
        exec /usr/bin/chmod "$@"
    """,
    "sleep": "exit 0",
}


@pytest.fixture
def shell(tmp_path):
    fake_bin = tmp_path / "bin"
    state = tmp_path / "state"
    for directory in (fake_bin, state):
        directory.mkdir()
    for name, body in FAKES.items():
        path = fake_bin / name
        path.write_text("#!/bin/bash\n" + textwrap.dedent(body))
        path.chmod(0o755)

    class Shell:
        conf = tmp_path / "etc/biglinux/sleep.conf"
        env = {
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "LANG": "C.UTF-8",
            "FAKE_BIN": str(fake_bin),
            "FAKE_STATE": str(state),
            "BIGLINUX_SLEEP_CONF": str(tmp_path / "etc/biglinux/sleep.conf"),
        }

        def command(self, script, *args, binds=None):
            argv = [str(SLEEP_SCRIPTS / script), *args]
            if binds is None:
                return argv
            mounts = "".join(
                f"mount --bind {shlex.quote(str(src))} {shlex.quote(dst)}; "
                for src, dst in binds.items()
            )
            return ["unshare", "-rm", "bash", "-c", f'set -e; {mounts}exec "$@"', "ns", *argv]

        def run(self, script, *args, binds=None, **env):
            return subprocess.run(
                self.command(script, *args, binds=binds),
                env={**self.env, **{k: str(v) for k, v in env.items()}},
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )

        def check(self, script, *args, **kwargs):
            result = self.run(script, "check", *args, **kwargs)
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

        def calls(self):
            log = state / "calls.log"
            return log.read_text().splitlines() if log.exists() else []

    return Shell()


def _userns_available():
    try:
        return subprocess.run(["unshare", "-rm", "true"], capture_output=True).returncode == 0
    except OSError:
        return False


needs_userns = pytest.mark.skipif(
    not _userns_available(), reason="unprivileged user namespaces unavailable"
)


def _parse(path):
    config = configparser.ConfigParser(strict=False)
    config.read(path)
    return config


# sleep.conf toggles


@pytest.mark.parametrize(
    "text, backlight, network",
    [
        ("[other]\nbacklight=true\n[handlers]\nnetwork=true\n", "false", "true"),
        ("[handlers]\n  Backlight = TRUE\nNETWORK:yes ; why\n", "true", "true"),
        ("[handlers]\nbacklight=true\nbacklight=false\n[x]\nnetwork=true\n", "false", "false"),
        ("backlight=true\nnetwork=true\n", "false", "false"),
    ],
)
def test_sleep_conf_check_reads_handlers_section(shell, text, backlight, network):
    shell.conf.parent.mkdir(parents=True)
    shell.conf.write_text(text)
    assert shell.check("backlight.sh") == backlight
    assert shell.check("wifi-d3cold.sh") == network


def test_sleep_conf_toggle_only_edits_handlers_section(shell):
    shell.conf.parent.mkdir(parents=True)
    shell.conf.write_text("[other]\nbacklight=true\n[handlers]\n  BackLight = true\nnetwork=true\n")
    result = shell.run("backlight.sh", "toggle", "false")
    assert result.returncode == 0, result.stderr
    config = _parse(shell.conf)
    assert config["other"]["backlight"] == "true"
    assert config["handlers"]["backlight"] == "false"
    assert config["handlers"]["network"] == "true"
    assert shell.check("backlight.sh") == "false"


def test_sleep_conf_toggle_creates_missing_key_section_and_file(shell):
    for script in ("backlight.sh", "wifi-d3cold.sh"):
        for state in ("true", "false", "true"):
            result = shell.run(script, "toggle", state)
            assert result.returncode == 0, result.stderr
            assert shell.check(script) == state
    config = _parse(shell.conf)
    assert dict(config["handlers"]) == {"backlight": "true", "network": "true"}

    shell.conf.write_text("[other]\nx=1\n")
    assert shell.run("wifi-d3cold.sh", "toggle", "true").returncode == 0
    assert _parse(shell.conf)["handlers"]["network"] == "true"
    assert _parse(shell.conf)["other"]["x"] == "1"


def test_sleep_conf_toggles_are_serialized(shell):
    shell.conf.parent.mkdir(parents=True)
    shell.conf.write_text("[handlers]\nbacklight=false\nnetwork=false\n")
    lock = os.open(shell.conf.parent, os.O_RDONLY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        proc = subprocess.Popen(
            shell.command("backlight.sh", "toggle", "true"),
            env=shell.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.5)
        assert proc.poll() is None, "toggle did not wait for the lock"
        assert shell.check("backlight.sh") == "false"
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        os.close(lock)
    assert proc.wait(timeout=10) == 0
    assert shell.check("backlight.sh") == "true"


# gnome-monitor.sh


@pytest.mark.parametrize("state, verb", [("true", "enable"), ("false", "disable")])
def test_gnome_monitor_session_step_is_best_effort(shell, state, verb):
    result = shell.run(
        "gnome-monitor.sh", "toggle", state, PKEXEC_UID=1000, FAKE_SYSTEMCTL_USER_RC=1
    )
    assert result.returncode == 0, result.stderr
    assert f"systemctl --global {verb} biglinux-sleep-monitor.service" in shell.calls()
    assert "Warning" in result.stderr


def test_gnome_monitor_fails_when_global_change_fails(shell):
    result = shell.run(
        "gnome-monitor.sh", "toggle", "true", PKEXEC_UID=1000, FAKE_SYSTEMCTL_GLOBAL_RC=1
    )
    assert result.returncode != 0


# suspend-at-20Run.sh


needs_upower = pytest.mark.skipif(
    not (Path("/etc/UPower").is_dir()
         and (os.access("/usr/lib/upowerd", os.X_OK) or os.access("/usr/libexec/upowerd", os.X_OK))),
    reason="UPower not installed",
)


@needs_userns
@needs_upower
def test_suspend_at_20_disable_survives_failed_upower_restart(shell, tmp_path):
    upower = tmp_path / "upower"
    drop_in = upower / "UPower.conf.d/90-biglinux-suspend-at-20.conf"
    drop_in.parent.mkdir(parents=True)
    drop_in.write_text("[UPower]\nUsePercentageForPolicy=true\n")
    result = shell.run(
        "suspend-at-20Run.sh", "disable",
        binds={upower: "/etc/UPower"}, FAKE_SYSTEMCTL_RESTART_RC=1,
    )
    assert result.returncode == 0, result.stderr
    assert not drop_in.exists()
    assert "Warning" in result.stderr


@needs_userns
@needs_upower
def test_suspend_at_20_enable_rolls_back_on_failed_upower_restart(shell, tmp_path):
    upower = tmp_path / "upower"
    upower.mkdir()
    result = shell.run(
        "suspend-at-20Run.sh", "enable",
        binds={upower: "/etc/UPower"}, FAKE_SYSTEMCTL_RESTART_RC=1,
    )
    assert result.returncode == 1
    assert not (upower / "UPower.conf.d/90-biglinux-suspend-at-20.conf").exists()


# lid-policy-root.sh


@pytest.fixture
def lid(shell, tmp_path):
    etc_systemd = tmp_path / "etc-systemd"
    conf_d = etc_systemd / "logind.conf.d"
    conf_d.mkdir(parents=True)
    run_lock = tmp_path / "run-lock"
    run_lock.mkdir()
    binds = {etc_systemd: "/etc/systemd", run_lock: "/run/lock"}

    class Lid:
        dir = conf_d
        drop_in = conf_d / "90-biglinux-lid-policy.conf"
        legacy = conf_d / "biglinux-lid-suspend.conf"

        def toggle(self, source, state, **env):
            return shell.run("lid-policy-root.sh", "toggle", source, state, binds=binds, **env)

        def check(self, source):
            return shell.check("lid-policy-root.sh", source, binds=binds)

        def lines(self):
            return self.drop_in.read_text().splitlines()

    return Lid()


@needs_userns
def test_lid_battery_only_keeps_ac_lid_suspending(lid):
    result = lid.toggle("battery", "true")
    assert result.returncode == 0, result.stderr
    # logind falls back to HandleLidSwitch= when ExternalPower is unset, which
    # would make "battery only" ignore the lid on AC too.
    assert "HandleLidSwitch=ignore" in lid.lines()
    assert "HandleLidSwitchExternalPower=suspend" in lid.lines()
    assert lid.check("battery") == "true"
    assert lid.check("ac") == "false"


@needs_userns
def test_lid_battery_only_preserves_admin_ac_action(lid):
    (lid.dir / "10-admin.conf").write_text("[Login]\nHandleLidSwitchExternalPower=lock\n")
    assert lid.toggle("battery", "true").returncode == 0
    assert "HandleLidSwitchExternalPower=lock" in lid.lines()


@needs_userns
def test_lid_disabling_ac_while_battery_managed_restores_suspend(lid):
    assert lid.toggle("ac", "true").returncode == 0
    assert lid.toggle("battery", "true").returncode == 0
    assert lid.check("ac") == "true"
    assert lid.toggle("ac", "false").returncode == 0
    assert "HandleLidSwitchExternalPower=suspend" in lid.lines()
    assert lid.check("ac") == "false"
    assert lid.check("battery") == "true"


@needs_userns
def test_lid_legacy_file_survives_failed_write(lid):
    lid.legacy.write_text("[Login]\nHandleLidSwitch=suspend\n")
    result = lid.toggle("battery", "true", FAKE_CHMOD_RC=1)
    assert result.returncode != 0
    assert lid.legacy.exists()
    assert not lid.drop_in.exists()


@needs_userns
def test_lid_legacy_file_removed_after_successful_write(lid):
    lid.legacy.write_text("[Login]\nHandleLidSwitch=suspend\n")
    assert lid.toggle("ac", "true").returncode == 0
    assert not lid.legacy.exists()
    assert lid.check("ac") == "true"
