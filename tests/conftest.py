"""Pytest configuration and shared fixtures for biglinux-settings tests."""

import sys
import os
from unittest.mock import MagicMock

# Mock GTK/GLib modules before any app code imports them
gi_mock = MagicMock()
gi_mock.require_version = MagicMock()

# Mock GObject introspection modules
for mod in [
    "gi",
    "gi.repository",
    "gi.repository.Gtk",
    "gi.repository.Adw",
    "gi.repository.Gio",
    "gi.repository.GLib",
    "gi.repository.Gdk",
]:
    sys.modules[mod] = MagicMock()

# Add source directory to path
SRC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "usr",
    "share",
    "biglinux",
    "biglinux-settings",
)
sys.path.insert(0, SRC_DIR)


# Test modules that execute the privileged helper scripts. Their test-only
# path overrides (BIGLINUX_GRUB_FILE, BIGLINUX_LEDS_DIR, ...) are ignored when
# running as root, by design, so as root these tests would edit the real
# /etc/default/grub, udev rules or LEDs. Never run them with root privileges
# (sudo, fakeroot).
PRIVILEGED_SCRIPT_TESTS = {
    "test_grub_scripts.py",
    "test_keyboard_led.py",
    "test_misc_scripts.py",
    "test_shell_toggles.py",
    "test_sleep_handlers.py",
    "test_smart_monitor.py",
}


def pytest_collection_modifyitems(config, items):
    if os.geteuid() != 0:
        return
    import pytest

    skip = pytest.mark.skip(
        reason="runs privileged helper scripts; refusing to run as root"
    )
    for item in items:
        if item.path.name in PRIVILEGED_SCRIPT_TESTS:
            item.add_marker(skip)
