"""
biglinux-sleep-monitor — user-level D-Bus monitor for suspend/resume events.

Runs as a systemd user service. Watches for extensions that enter ERROR state
after suspend/resume and fixes them with a disable+wait+enable cycle.

With s2idle (freeze), the GNOME Shell process is simply frozen/thawed, so
extensions keep their state. No proactive disable/enable is needed.
The original user-theme corruption only happened with S3 deep sleep where
GNOME Shell went through a full extension lifecycle during resume.

This monitor is now a safety-net: it only intervenes if something goes wrong.
"""
import logging
import os
import sys
import time

import gi
gi.require_version('GLib', '2.0')
gi.require_version('Gio', '2.0')
from gi.repository import GLib, Gio

sys.path.insert(0, "/usr/lib/biglinux")
from sleep.handlers.gnome import (
    DEFERRED_EXTENSIONS,
    GnomeHandler,
    _dbus_call,
    _ext_state,
)

logging.basicConfig(
    level=logging.INFO,
    format="biglinux-sleep-monitor: %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("monitor")

UID = str(os.getuid())
_just_resumed = False
_screen_active = False

# logind "delay" inhibitor: logind waits (up to InhibitDelayMaxSec) for this fd
# to be closed before suspending, so pre_suspend gets to run first.
_system_bus = None
_inhibit_fd: int | None = None

# How long to wait after unlock before checking extension health (ms).
_CHECK_DELAY_MS = 2000


def _ext_op(method: str, uuid: str) -> bool:
    result = _dbus_call(UID, "org.gnome.Shell.Extensions", method, "s", uuid)
    return result == "b true"


def _disable_wait_enable(uuid: str, wait: float = 3.0) -> bool:
    """Fix an extension in ERROR state with a clean disable+wait+enable cycle."""
    log.info("Fixing %s: disable + %.1fs wait + enable", uuid, wait)
    if _ext_op("DisableExtension", uuid):
        time.sleep(wait)
        if _ext_op("EnableExtension", uuid):
            log.info("Fixed %s", uuid)
            return True
        log.warning("Could not re-enable %s", uuid)
    else:
        log.warning("Could not disable %s", uuid)
    return False


def _take_inhibitor() -> bool:
    """Acquire a logind delay inhibitor for sleep. Never raises."""
    global _inhibit_fd
    if _inhibit_fd is not None:
        return True
    if _system_bus is None:
        return False
    try:
        result, fd_list = _system_bus.call_with_unix_fd_list_sync(
            "org.freedesktop.login1",
            "/org/freedesktop/login1",
            "org.freedesktop.login1.Manager",
            "Inhibit",
            GLib.Variant("(ssss)", (
                "sleep",
                "biglinux-sleep-monitor",
                "Prepare GNOME Shell extensions for suspend",
                "delay",
            )),
            GLib.VariantType.new("(h)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            None,
        )
        _inhibit_fd = fd_list.get(result.unpack()[0])
    except Exception as e:  # GLib.Error, or a broken/absent logind
        log.warning("Cannot take logind sleep delay inhibitor: %s", e)
        _inhibit_fd = None
        return False
    log.info("Holding logind sleep delay inhibitor")
    return True


def _release_inhibitor() -> None:
    """Close the inhibitor fd so logind may proceed with suspend."""
    global _inhibit_fd
    fd, _inhibit_fd = _inhibit_fd, None
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError as e:
        log.warning("Cannot release sleep inhibitor: %s", e)


def _check_extensions_health() -> bool:
    """Check if any user-enabled deferred extension is in ERROR state and fix it."""
    fixed_any = False
    for uuid in DEFERRED_EXTENSIONS:
        info = _ext_state(UID, uuid)
        if not info:
            continue
        error = info.get("error", "")
        state = info.get("state")
        # Only a real ERROR (state 3) of an extension the user has enabled:
        # a stale error string alone, or a disabled extension, is left alone.
        if info.get("enabled") and state == 3:
            log.warning("Extension %s in bad state (state=%s, error=%s)",
                        uuid, state, error)
            if _disable_wait_enable(uuid):
                fixed_any = True
    if not fixed_any:
        log.info("All deferred extensions healthy after resume")
    return GLib.SOURCE_REMOVE


def _resume_extensions() -> bool:
    """Restore extensions saved by the pre-suspend handler, then verify health."""
    try:
        GnomeHandler().post_resume("suspend")
    except Exception as e:
        log.error("post_resume failed: %s", e, exc_info=True)
    return _check_extensions_health()


def _on_prepare_for_sleep(connection, sender, path, iface, signal, params, _):
    global _just_resumed
    going_to_sleep = params[0]

    if going_to_sleep:
        log.info("PrepareForSleep(True): system going to sleep")
        _just_resumed = False
        try:
            GnomeHandler().pre_suspend("suspend")
        except Exception as e:
            log.error("pre_suspend failed: %s", e, exc_info=True)
        finally:
            _release_inhibitor()
    else:
        log.info("PrepareForSleep(False): system waking up")
        _take_inhibitor()
        _just_resumed = True
        if not _screen_active:
            _just_resumed = False
            GLib.timeout_add(3000, _resume_extensions)


def _on_screensaver_changed(connection, sender, path, iface, signal, params, _):
    global _just_resumed, _screen_active
    is_active = params[0]
    _screen_active = is_active

    if not is_active and _just_resumed:
        log.info("Screen unlocked after resume — checking extension health")
        _just_resumed = False
        GLib.timeout_add(_CHECK_DELAY_MS, _resume_extensions)


def _is_gnome_session() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    session = os.environ.get("XDG_SESSION_DESKTOP", "")
    return "GNOME" in desktop.upper() or "gnome" in session.lower()


def main():
    global _system_bus
    if not _is_gnome_session():
        log.info("Not a GNOME session (XDG_CURRENT_DESKTOP=%s), exiting",
                 os.environ.get("XDG_CURRENT_DESKTOP", "(unset)"))
        return 0

    log.info("Starting biglinux-sleep-monitor (uid=%s)", UID)

    try:
        system_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        system_bus.signal_subscribe(
            "org.freedesktop.login1",
            "org.freedesktop.login1.Manager",
            "PrepareForSleep",
            "/org/freedesktop/login1",
            None,
            Gio.DBusSignalFlags.NONE,
            _on_prepare_for_sleep,
            None,
        )
        log.info("Subscribed to PrepareForSleep on system bus")
        _system_bus = system_bus
        _take_inhibitor()
    except GLib.Error as e:
        log.error("Cannot connect to system bus: %s", e)
        return 1

    try:
        session_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        session_bus.signal_subscribe(
            "org.gnome.ScreenSaver",
            "org.gnome.ScreenSaver",
            "ActiveChanged",
            "/org/gnome/ScreenSaver",
            None,
            Gio.DBusSignalFlags.NONE,
            _on_screensaver_changed,
            None,
        )
        log.info("Subscribed to ScreenSaver.ActiveChanged on session bus")
    except GLib.Error as e:
        log.error("Cannot connect to session bus: %s", e)
        return 1

    # Restore saved state or check health at startup (in case of crash recovery)
    GLib.timeout_add(5000, _resume_extensions)

    loop = GLib.MainLoop()
    log.info("Event loop running")
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
