"""
GNOME Shell extension race condition fix.

ROOT CAUSE:
  Main.loadTheme() copies all custom stylesheets from the previous St.Theme
  to the new one without validating if the underlying GLib resources are still
  registered. When copyous.ThemeManager.destroy() unregisters its gresource,
  it calls unload_stylesheet() on the OLD St.Theme object (stored at enable()
  time), not the current active one. Result: copyous's stylesheet stays in the
  active theme's custom list. On the next Main.loadTheme() call (at any unlock
  or session transition), it tries to load a resource:// URI whose gresource
  is no longer registered → IOErrorEnum → broken layout on lock screen AND
  desktop after resume.

FIX (no extension modification needed):
  Before suspend: disable user-theme via org.gnome.Shell.Extensions D-Bus.
  This removes it from the enabled-extensions gsettings list. When GNOME Shell
  re-enables extensions at unlock, user-theme is absent → other extensions
  (including copyous) enable first, registering their gresources.
  After unlock + short delay: re-enable user-theme. Now copyous IS ready,
  loadTheme() succeeds, theme renders correctly.

  WHY disable+wait+enable works but ReloadExtension does NOT:
  ReloadExtension calls disable()+enable() but also reloads the JS module,
  which can interfere with GNOME Shell 49's async ESM loader state.
  DisableExtension/EnableExtension cleanly modifies gsettings and triggers
  a fresh enable() with a stable theme context.
"""
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from .base import SleepHandler

log = logging.getLogger(__name__)

# Persistent (not tmpfs): pre_suspend writes the disable to gsettings, so if the
# machine loses power while suspended the pending re-enable must survive the
# reboot. The monitor replays it at startup.
STATE_FILE = (
    Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    / "biglinux-settings"
    / "gnome-ext-state.json"
)

# D-Bus interface of the GNOME Shell extension manager.
SHELL_EXTENSIONS_IFACE = "org.gnome.Shell.Extensions"

# Extensions that must be disabled before suspend and re-enabled after resume.
# user-theme calls Main.loadTheme() immediately in enable(), before other
# extensions can register their resources. It must be the LAST to enable.
DEFERRED_EXTENSIONS = [
    "user-theme@gnome-shell-extensions.gcampax.github.com",
]


def _variant(result: str, key: str) -> tuple[str, str] | None:
    match = re.search(
        rf'"{re.escape(key)}"\s+([a-z]+)\s+((?:"(?:\\.|[^"])*")|true|false|-?\d+)',
        result,
    )
    if not match:
        return None
    return match.group(1), match.group(2)


def _variant_bool(result: str, key: str) -> bool:
    value = _variant(result, key)
    return bool(value and value[0] == "b" and value[1] == "true")


def _variant_int(result: str, key: str) -> int | None:
    value = _variant(result, key)
    if not value or value[0] not in ("i", "u", "x", "t", "n", "q", "d"):
        return None
    try:
        return int(float(value[1]))
    except ValueError:
        return None


def _variant_string(result: str, key: str) -> str:
    value = _variant(result, key)
    if not value or value[0] != "s":
        return ""
    return value[1].strip('"')


def _dbus_call(uid: str, interface: str, method: str, *args) -> str | None:
    """Run a busctl call in the user's D-Bus session."""
    dbus_addr = f"unix:path=/run/user/{uid}/bus"
    cmd = ["busctl", "--user", f"--address={dbus_addr}",
           "call", "org.gnome.Shell", "/org/gnome/Shell",
           interface, method] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception as e:
        log.debug("dbus_call %s.%s failed: %s", interface, method, e)
        return None


def _ext_state(uid: str, uuid: str) -> dict | None:
    result = _dbus_call(uid, SHELL_EXTENSIONS_IFACE,
                        "GetExtensionInfo", "s", uuid)
    if result:
        return {
            "enabled": _variant_bool(result, "enabled"),
            "state": _variant_int(result, "state"),
            "error": _variant_string(result, "error"),
        }
    return None


def _disable_extension(uid: str, uuid: str) -> bool:
    result = _dbus_call(uid, SHELL_EXTENSIONS_IFACE,
                        "DisableExtension", "s", uuid)
    return result == "b true"


def _enable_extension(uid: str, uuid: str) -> bool:
    result = _dbus_call(uid, SHELL_EXTENSIONS_IFACE,
                        "EnableExtension", "s", uuid)
    return result == "b true"


def _find_gnome_uid() -> str | None:
    # The user-level monitor must act on its own session only; with several
    # logged-in users the first graphical session may belong to someone else.
    if os.getuid() != 0:
        return str(os.getuid())
    try:
        out = subprocess.check_output(
            ["loginctl", "list-sessions", "--no-legend"],
            text=True, timeout=5)
    except Exception:
        return None

    for line in out.strip().splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            props = subprocess.check_output(
                ["loginctl", "show-session", parts[0]],
                text=True, timeout=5)
        except Exception:
            continue
        info = dict(p.split("=", 1) for p in props.splitlines() if "=" in p)
        if (info.get("Type") in ("wayland", "x11") and
                info.get("Class") == "user" and
                info.get("State") in ("active", "online")):
            return info.get("User")
    return None


def _save_state(disabled: list[str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"disabled": disabled}))


def _load_state() -> list[str]:
    try:
        return json.loads(STATE_FILE.read_text()).get("disabled", [])
    except Exception:
        return []


def _clear_state() -> None:
    STATE_FILE.unlink(missing_ok=True)


class GnomeHandler(SleepHandler):
    name = "gnome"

    def is_available(self) -> bool:
        return subprocess.run(
            ["which", "busctl"], capture_output=True).returncode == 0

    def pre_suspend(self, sleep_type: str) -> None:
        """
        Disable user-theme BEFORE suspend so it's absent from enabled-extensions.
        When GNOME Shell re-enables extensions at unlock, user-theme won't be in
        the list — other extensions (including copyous) enable first, registering
        their gresources. We re-enable user-theme after that.
        """
        uid = _find_gnome_uid()
        if not uid:
            log.info("No graphical GNOME session found, skipping")
            return

        actually_disabled = []
        for uuid in DEFERRED_EXTENSIONS:
            info = _ext_state(uid, uuid)
            if info and info["enabled"]:
                log.info("pre_suspend: disabling %s", uuid)
                if _disable_extension(uid, uuid):
                    actually_disabled.append(uuid)
                else:
                    log.warning("Could not disable %s", uuid)

        if actually_disabled:
            _save_state(actually_disabled)

    def post_resume(self, sleep_type: str) -> None:
        """
        Re-enable deferred extensions after resume.
        Called from the user-level monitor (biglinux-sleep-monitor) after
        the screen is unlocked — at which point all other extensions have
        already completed their enable() and registered their gresources.
        """
        pending = _load_state()
        if not pending:
            # Fallback: if pre_suspend wasn't called (e.g., hibernation, crash),
            # check for ERROR state and fix it.
            uid = _find_gnome_uid()
            if uid:
                self._fix_error_state(uid)
            return

        uid = _find_gnome_uid()
        if not uid:
            log.warning("post_resume: no GNOME session found, state saved for next opportunity")
            return

        self._wait_shell_ready(uid)
        # Extra delay: let all other extensions finish enable() and register resources
        time.sleep(1.5)

        remaining = []
        for uuid in pending:
            log.info("post_resume: re-enabling %s", uuid)
            if _enable_extension(uid, uuid):
                log.info("Re-enabled %s successfully", uuid)
            else:
                log.warning("Could not re-enable %s", uuid)
                remaining.append(uuid)

        if remaining:
            _save_state(remaining)
        else:
            _clear_state()

    def _fix_error_state(self, uid: str) -> None:
        """
        Fix extensions stuck in ERROR state (fallback for missed pre_suspend).

        ReloadExtension does NOT reliably fix the broken St.Theme state because
        it goes through GNOME Shell 49's async ESM module loader which may
        interfere with the theme system mid-reload.

        DisableExtension + 3s wait + EnableExtension works because:
        - Disable: removes from gsettings, calls disable() cleanly, Main.loadTheme()
          runs with the current stable theme (all other extensions are enabled)
        - 3s wait: allows theme to fully stabilize
        - Enable: re-runs enable() with all other extensions (copyous) already
          running and their gresources registered → loadTheme() succeeds
        """
        for uuid in DEFERRED_EXTENSIONS:
            info = _ext_state(uid, uuid)
            # Only a real ERROR (state 3) of an extension the user enabled;
            # never resurrect one the user turned off.
            if not info or not info.get("enabled") or info.get("state") != 3:
                continue
            log.info("Extension %s is in ERROR state, applying disable+enable fix", uuid)
            if _disable_extension(uid, uuid):
                log.info("Disabled %s, waiting for theme to stabilize...", uuid)
                time.sleep(3.0)
                if _enable_extension(uid, uuid):
                    log.info("Re-enabled %s — fix applied", uuid)
                else:
                    log.warning("Could not re-enable %s", uuid)
            else:
                log.warning("Could not disable %s for error fix", uuid)

    def _wait_shell_ready(self, uid: str, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _dbus_call(uid, SHELL_EXTENSIONS_IFACE,
                          "GetExtensionInfo", "s", DEFERRED_EXTENSIONS[0]):
                return True
            time.sleep(0.3)
        log.warning("GNOME Shell not responsive after %.0fs", timeout)
        return False
