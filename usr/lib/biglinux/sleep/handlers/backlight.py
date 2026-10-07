"""
Backlight and LED handler.

Saves screen backlights (/sys/class/backlight/*) and keyboard backlight LEDs
(/sys/class/leds/*kbd_backlight*) before suspend and restores them after
resume. Other LEDs (caps/num lock, mic mute, ...) are driven by the kernel
or by their trigger and are never touched, nor is any LED with an active
trigger.

systemd-backlight only runs at boot/shutdown, not at suspend/resume.
This handler fills that gap.

ASUS-specific: The asus_nb_wmi driver may enter a bogus blinking mode
after S3 resume if the keyboard LED was on when entering sleep.
To mitigate, keyboard LED brightness is set to 0 before suspend, and
restored to the saved value after resume. This avoids the need to
reload the kernel module (which would break Fn hotkeys).
"""
import json
import logging
import time
from pathlib import Path

from .base import SleepHandler

log = logging.getLogger(__name__)

STATE_FILE = Path("/run/biglinux/backlight-state.json")

BACKLIGHT_DIR = Path("/sys/class/backlight")
LEDS_DIR = Path("/sys/class/leds")
_ASUS_KBD_LED_NAME = "asus::kbd_backlight"


def _read_brightness(device_path: Path) -> int | None:
    try:
        val = (device_path / "brightness").read_text().strip()
        return int(val)
    except (OSError, ValueError):
        return None


def _write_brightness(device_path: Path, value: int) -> bool:
    try:
        (device_path / "brightness").write_text(str(value))
        return True
    except OSError as e:
        log.warning("Cannot restore %s brightness: %s", device_path.name, e)
        return False


def _max_brightness(device_path: Path) -> int:
    try:
        return int((device_path / "max_brightness").read_text().strip())
    except (OSError, ValueError):
        return 0


def _led_trigger(device_path: Path) -> str | None:
    """Return the active trigger of an LED ("[none] foo" -> "none")."""
    try:
        text = (device_path / "trigger").read_text()
    except OSError:
        return None
    for token in text.split():
        if token.startswith("[") and token.endswith("]"):
            return token[1:-1]
    return None


def _is_managed(device_path: Path) -> bool:
    """Only screen backlights and trigger-less keyboard backlight LEDs."""
    parent = device_path.parent
    if parent == BACKLIGHT_DIR:
        return True
    if parent != LEDS_DIR or "kbd_backlight" not in device_path.name:
        return False
    trigger = _led_trigger(device_path)
    return trigger is None or trigger == "none"


def _collect_state() -> dict:
    state = {}
    for base_path in (BACKLIGHT_DIR, LEDS_DIR):
        if not base_path.exists():
            continue
        for device in sorted(base_path.iterdir()):
            if not _is_managed(device):
                continue
            brightness = _read_brightness(device)
            if brightness is not None:
                state[str(device)] = brightness
    return state


class BacklightHandler(SleepHandler):
    name = "backlight"

    def pre_suspend(self, sleep_type: str) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = _collect_state()
        STATE_FILE.write_text(json.dumps(state, indent=2))
        log.info("Saved brightness for %d devices", len(state))

        # ASUS-specific: turn off keyboard LED before entering S3.
        # Some ASUS EC firmware enters a bogus blinking mode on resume
        # if the LED was on when entering sleep. Setting to 0 avoids it.
        asus_led = LEDS_DIR / _ASUS_KBD_LED_NAME
        if str(asus_led) in state:
            if _write_brightness(asus_led, 0):
                log.info("Set ASUS keyboard LED to 0 before suspend")

    def post_resume(self, sleep_type: str) -> None:
        if not STATE_FILE.exists():
            log.warning("No backlight state file found, skipping restore")
            return

        try:
            state = json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.error("Cannot read backlight state: %s", e)
            return

        # Small delay to let hardware stabilize after resume
        time.sleep(0.3)

        restored = 0
        for path_str, value in state.items():
            device = Path(path_str)
            # Re-check: a state file from an older version may list other LEDs
            if not device.exists() or not _is_managed(device):
                continue
            if not isinstance(value, int):
                continue
            max_b = _max_brightness(device)
            # Clamp to max_brightness to avoid EINVAL
            clamped = min(value, max_b) if max_b > 0 else value
            if _write_brightness(device, clamped):
                restored += 1

        log.info("Restored brightness for %d/%d devices", restored, len(state))
