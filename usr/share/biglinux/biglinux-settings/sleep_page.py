import logging
import os
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from base_page import BaseSettingsPage, _  # noqa: E402

logger = logging.getLogger("biglinux-settings")


def _detect_desktop() -> str:
    """Return the current desktop environment id."""
    de = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "gnome" in de:
        return "gnome"
    if "kde" in de or "plasma" in de:
        return "kde"
    if "cinnamon" in de:
        return "cinnamon"
    if "xfce" in de:
        return "xfce"
    return de or "unknown"


def _has_rtw89() -> bool:
    """Check if any rtw89 WiFi module is loaded."""
    try:
        out = subprocess.run(
            ["lsmod"], capture_output=True, text=True, timeout=5
        ).stdout
        return "rtw89" in out
    except Exception:
        return False


def _has_asus_ec_bug() -> bool:
    """Detect ASUS notebooks susceptible to EC GPE bug after S3 deep sleep."""
    try:
        vendor_path = "/sys/class/dmi/id/board_vendor"
        if not os.path.exists(vendor_path):
            return False
        with open(vendor_path) as f:
            vendor = f.read().strip().lower()
        if "asus" not in vendor:
            return False

        # Check if deep sleep is available (the bug only matters when S3 exists)
        mem_sleep_path = "/sys/power/mem_sleep"
        if os.path.exists(mem_sleep_path):
            with open(mem_sleep_path) as f:
                modes = f.read().strip()
            if "deep" in modes:
                return True
        return False
    except Exception:
        return False


class SleepPage(BaseSettingsPage):
    def __init__(self, main_window, **kwargs):
        super().__init__(main_window, **kwargs)

        self._desktop = _detect_desktop()

        content = self.create_scrolled_content(
            _("Power & Suspend"),
            _(
                "What happens when the computer is idle, on battery or with the lid closed."
            ),
        )

        sleep_keywords = [_("don't sleep"), _("stay awake"), _("sleep"), _("suspend")]

        # --- When idle ---
        grp_idle = self.create_group(
            _("When idle"),
            _("Choose whether the computer suspends after a period without use."),
            "sleep",
        )
        content.append(grp_idle)

        self.create_row(
            grp_idle,
            _("Stay awake while plugged in"),
            _("Does not suspend when idle while connected to power."),
            "never-suspend-ac",
            None,
            keywords=sleep_keywords,
        )

        self.create_row(
            grp_idle,
            _("Stay awake on battery"),
            _(
                "Does not suspend when idle on battery. The critical-battery action "
                "still applies."
            ),
            "never-suspend-battery",
            None,
            keywords=sleep_keywords + [_("battery")],
        )

        self.create_row(
            grp_idle,
            _("Stay awake and suspend at 20% battery"),
            _(
                "Does not suspend when idle on battery and suspends automatically "
                "when the charge reaches 20%."
            ),
            "suspend-at-20",
            None,
            info_text=_(
                "This uses UPower's critical battery policy. Low and critical "
                "warnings occur before the suspend action at 20%."
            ),
            keywords=sleep_keywords + [_("battery"), _("low battery")],
        )

        # --- When the lid is closed (always visible) ---
        grp_lid = self.create_group(
            _("When the lid is closed"),
            _("Keep the computer working with the lid closed, for example with an external monitor."),
            "sleep",
        )
        content.append(grp_lid)

        lid_keywords = [_("lid"), _("laptop"), _("don't sleep"), _("stay awake")]

        self.create_row(
            grp_lid,
            _("Keep running with the lid closed while plugged in"),
            _(
                "Closing the lid will not lock or suspend the computer while it is "
                "connected to power. The session and network stay active."
            ),
            "never-suspend-lid-ac",
            None,
            info_text=_(
                "This prevents lid-triggered suspend and locking. Automatic "
                "idle locking remains separate. Keep the notebook ventilated "
                "while it runs with the lid closed."
            ),
            keywords=lid_keywords,
        )

        self.create_row(
            grp_lid,
            _("Keep running with the lid closed on battery"),
            _(
                "Closing the lid will not lock or suspend the computer on battery. "
                "The session and network stay active, using more battery."
            ),
            "never-suspend-lid-battery",
            None,
            info_text=_(
                "This prevents lid-triggered suspend and locking. Automatic "
                "idle locking remains separate, and the 20% critical battery "
                "policy still applies."
            ),
            keywords=lid_keywords + [_("battery")],
        )

        # --- Fix problems after resume ---
        grp_fix = self.create_group(
            _("Fix problems after resume"),
            _("Compatibility fixes for problems some computers have when waking from suspend."),
            "sleep",
        )
        content.append(grp_fix)

        # Light sleep (only for ASUS with EC bug)
        if _has_asus_ec_bug():
            self.create_row(
                grp_fix,
                _("Light sleep (s2idle)"),
                _(
                    "Uses a lighter sleep mode that keeps the Fn keys working after "
                    "resume on some ASUS notebooks. Uses slightly more battery while "
                    "suspended."
                ),
                "s2idle",
                None,
                info_text=_(
                    "S3 deep sleep can cause the Embedded Controller to stop "
                    "generating hotkey interrupts. s2idle keeps the EC powered, "
                    "avoiding this issue at a small cost in battery consumption."
                ),
                keywords=[_("sleep"), _("Fn keys"), _("hotkeys")],
                applies_after_restart=True,
            )

        # Wi-Fi d3cold prevention (only if rtw89 loaded)
        if _has_rtw89():
            self.create_row(
                grp_fix,
                _("Avoid losing Wi-Fi after resume"),
                _(
                    "Compatibility fix for some Realtek Wi-Fi adapters: keeps the "
                    "adapter from fully powering off during suspend, so the "
                    "connection works after resume."
                ),
                "wifi-d3cold",
                "wifi-symbolic",
                info_text=_(
                    "Some Realtek RTL8852BE/CE chips fail to reinitialize "
                    "after d3cold power gating. This keeps the chip in d3hot "
                    "(PCIe link alive) during suspend."
                ),
                keywords=[_("Wi-Fi"), _("wireless"), _("Realtek")],
            )

        # Backlight save/restore (always visible)
        self.create_row(
            grp_fix,
            _("Restore brightness after resume"),
            _(
                "Saves the screen brightness and keyboard lights before suspending "
                "and restores them when the computer wakes up."
            ),
            "backlight",
            None,
            keywords=[_("brightness"), _("backlight")],
        )

        # GNOME extension monitor (only on GNOME)
        if self._desktop == "gnome":
            self.create_row(
                grp_fix,
                _("Restart failed extensions after resume"),
                _(
                    "Checks GNOME Shell extensions after resume and restarts the "
                    "ones left in an error state."
                ),
                "gnome-monitor",
                None,
                keywords=[_("GNOME"), _("extensions")],
            )
