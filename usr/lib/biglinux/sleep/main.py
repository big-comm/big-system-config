"""
biglinux-sleep — system-level sleep hook for BigLinux/BigCommunity.

Called by systemd as: biglinux-sleep <pre|post> <sleep-type>

Handles hardware-level save/restore (backlight, LEDs, WiFi).
GNOME Shell extension fixes are handled by the user-level monitor service
(biglinux-sleep-monitor) which has access to the session D-Bus.

This separation is intentional:
  - Root hook: fast, hardware-only, no D-Bus session needed
  - User monitor: GNOME state management via session D-Bus

Handler loading is controlled by /etc/biglinux/sleep.conf.
"""
import configparser
import importlib
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, "/usr/lib/biglinux")

from sleep.handlers.base import SleepHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("biglinux-sleep")

CONFIG_FILE = Path("/etc/biglinux/sleep.conf")

# Map config keys to handler module.class
_HANDLER_MAP = {
    "backlight": ("sleep.handlers.backlight", "BacklightHandler"),
    "network": ("sleep.handlers.network", "NetworkHandler"),
}


def _load_config() -> dict[str, bool]:
    """Read handler enabled states from config file.

    A damaged config must never abort the hook: any key that cannot be read
    falls back to disabled, and the rest of the file is still honoured.
    """
    config = configparser.ConfigParser(strict=False, inline_comment_prefixes=("#", ";"))

    try:
        if CONFIG_FILE.exists():
            config.read(str(CONFIG_FILE))
    except (configparser.Error, OSError, UnicodeDecodeError) as e:
        log.error("Ignoring unreadable config %s: %s", CONFIG_FILE, e)
        config = configparser.ConfigParser()

    result = {}
    for key in _HANDLER_MAP:
        try:
            result[key] = config.getboolean("handlers", key, fallback=False)
        except ValueError:
            log.error(
                "Invalid value for '%s' in %s, treating as false", key, CONFIG_FILE
            )
            result[key] = False
    return result


def _load_handlers() -> list[SleepHandler]:
    """Dynamically load enabled handlers from config."""
    enabled = _load_config()
    handlers = []

    for key, (module_path, class_name) in _HANDLER_MAP.items():
        if not enabled.get(key, False):
            log.info("Handler '%s' disabled by config", key)
            continue
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            handlers.append(cls())
            log.info("Loaded handler: %s", key)
        except Exception as e:
            log.error("Failed to load handler '%s': %s", key, e)

    return handlers


def run(phase: str, sleep_type: str) -> int:
    handlers = _load_handlers()
    log.info("phase=%s type=%s handlers=%d", phase, sleep_type, len(handlers))
    errors = 0
    for handler in handlers:
        try:
            if not handler.enabled or not handler.is_available():
                continue
            t0 = time.monotonic()
            if phase == "pre":
                handler.pre_suspend(sleep_type)
            else:
                handler.post_resume(sleep_type)
            log.info("[%s] done in %.2fs", handler.name, time.monotonic() - t0)
        except Exception as e:
            log.error("[%s] failed: %s", handler.name, e, exc_info=True)
            errors += 1
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("pre", "post"):
        log.error("Usage: biglinux-sleep <pre|post> <sleep-type>")
        sys.exit(2)
    sys.exit(run(sys.argv[1], sys.argv[2]))
