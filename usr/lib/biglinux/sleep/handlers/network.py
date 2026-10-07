"""
Network handler for sleep/resume.

Prevents WiFi PCIe devices from entering D3cold during s2idle suspend.
The Realtek rtw89 driver (RTL8852BE and similar) fails to re-initialize
after D3cold — the crystal oscillator doesn't stabilize ("xtal si not ready")
and the PCI config space becomes unreadable (header type 7f).

Strategy:
- pre_suspend: Disable d3cold_allowed for the WiFi device AND its parent
  PCIe root port.  This keeps the device in D3hot at most, preserving the
  PCIe link.  The loaded driver handles freeze/thaw during s2idle.
  The original d3cold_allowed of each device is saved in the state file.
- post_resume: Restore exactly the saved d3cold_allowed values, so a device
  the user or another tool had already pinned to 0 stays at 0.
  If the device ended up in a bad state anyway, fall back to module
  unload + PCI rescan + module reload.
"""
import json
import logging
import subprocess
import time
from pathlib import Path

from .base import SleepHandler

log = logging.getLogger(__name__)

# WiFi modules known to have D3cold issues after s2idle.
_WIFI_MODULES = [
    "rtw89_8852be_git",
    "rtw89_8852be",
    "rtw89_8852ce_git",
    "rtw89_8852ce",
]

_PCI_DEVICES = Path("/sys/bus/pci/devices")
_PCI_RESCAN = Path("/sys/bus/pci/rescan")
STATE_FILE = Path("/run/biglinux/network-state.json")


def _find_wifi_pci() -> tuple[str, str] | None:
    """Return (module_name, pci_slot) for the first loaded rtw89 module."""
    for module in _WIFI_MODULES:
        mod_sysfs = Path(f"/sys/module/{module.replace('-', '_')}")
        if not mod_sysfs.exists():
            continue
        # Walk PCI devices looking for one bound to this driver
        try:
            for dev in _PCI_DEVICES.iterdir():
                driver_link = dev / "driver"
                if driver_link.is_symlink():
                    drv_name = driver_link.resolve().name
                    if drv_name == module.replace("-", "_") or drv_name == module:
                        return (module, dev.name)
        except OSError:
            pass
    return None


def _save_state(module: str, pci_slot: str, d3cold: dict[str, str] | None = None) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(
        {"module": module, "pci_slot": pci_slot, "d3cold": d3cold or {}}))


def _load_saved_d3cold() -> dict[str, str]:
    """Original d3cold_allowed values recorded by pre_suspend ({slot: "0"|"1"})."""
    try:
        saved = json.loads(STATE_FILE.read_text()).get("d3cold", {})
    except (OSError, AttributeError, json.JSONDecodeError):
        return {}
    if not isinstance(saved, dict):
        return {}
    return {
        slot: value for slot, value in saved.items()
        if isinstance(slot, str) and value in ("0", "1")
    }


def _d3cold_targets(pci_slot: str) -> list[str]:
    return [t for t in (pci_slot, _parent_bridge(pci_slot)) if t is not None]


def _read_d3cold(target: str) -> str | None:
    try:
        value = (_PCI_DEVICES / target / "d3cold_allowed").read_text().strip()
    except OSError:
        return None
    return value if value in ("0", "1") else None


def _load_state() -> tuple[str, str] | None:
    try:
        state = json.loads(STATE_FILE.read_text())
        module = state["module"]
        pci_slot = state["pci_slot"]
        if module in _WIFI_MODULES and isinstance(pci_slot, str):
            return module, pci_slot
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        pass
    return None


def _set_d3cold(pci_slot: str, allowed: bool) -> None:
    """Set d3cold_allowed for a PCI device and its parent bridge."""
    val = "1" if allowed else "0"
    label = "Enabled" if allowed else "Disabled"

    for target in _d3cold_targets(pci_slot):
        path = _PCI_DEVICES / target / "d3cold_allowed"
        try:
            path.write_text(val)
            log.info("%s d3cold for %s", label, target)
        except OSError as e:
            log.warning("Failed to set d3cold=%s for %s: %s", val, target, e)


def _restore_d3cold(pci_slot: str, saved: dict[str, str]) -> None:
    """Write back the values saved at pre_suspend.

    A device without a saved value (state from an older version, or a device
    re-created by the fallback PCI rescan under a new parent) gets "1", the
    kernel default.
    """
    for target in _d3cold_targets(pci_slot):
        val = saved.get(target, "1")
        try:
            (_PCI_DEVICES / target / "d3cold_allowed").write_text(val)
            log.info("Restored d3cold_allowed=%s for %s", val, target)
        except OSError as e:
            log.warning("Failed to restore d3cold=%s for %s: %s", val, target, e)


def _parent_bridge(pci_slot: str) -> str | None:
    """Return the PCI slot of the parent bridge (e.g. '0000:00:1c.0')."""
    dev = _PCI_DEVICES / pci_slot
    try:
        real = dev.resolve()
        parent = real.parent
        # parent should be another PCI device directory
        if (parent / "d3cold_allowed").exists():
            return parent.name
    except OSError:
        pass
    return None


def _device_healthy(pci_slot: str) -> bool:
    """Return True if the PCI device config space is readable and in D0/D3hot."""
    dev = _PCI_DEVICES / pci_slot
    if not dev.exists():
        return False
    try:
        power = (dev / "power_state").read_text().strip()
        # D0 and D3hot are fine; D3cold or unknown means trouble
        return power in ("D0", "D1", "D2", "D3hot")
    except OSError:
        return False


def _fallback_recovery(module: str, pci_slot: str) -> None:
    """Aggressive recovery: unload module, PCI rescan, reload module, restart NM."""
    log.warning("WiFi device in bad state — starting fallback recovery")

    # Unload module
    try:
        subprocess.run(["modprobe", "-r", module],
                       capture_output=True, timeout=15)
        log.info("Unloaded %s for recovery", module)
    except Exception:
        pass

    time.sleep(1)

    # Remove device from PCI bus if it still exists
    remove = _PCI_DEVICES / pci_slot / "remove"
    try:
        if remove.exists():
            remove.write_text("1")
            log.info("Removed PCI device %s", pci_slot)
            time.sleep(1)
    except OSError:
        pass

    # Rescan bus
    try:
        _PCI_RESCAN.write_text("1")
        log.info("Triggered PCI bus rescan")
        time.sleep(3)
    except OSError as e:
        log.warning("PCI rescan failed: %s", e)

    # Disable d3cold again before loading (prevent immediate D3cold)
    _set_d3cold(pci_slot, False)

    # Reload module
    try:
        subprocess.run(["modprobe", module],
                       capture_output=True, timeout=30, check=True)
        log.info("Reloaded %s after recovery", module)
    except subprocess.CalledProcessError as e:
        log.error("Failed to reload %s: %s", module, e)
        return

    time.sleep(2)

    # Restart NetworkManager
    try:
        subprocess.run(["systemctl", "restart", "NetworkManager.service"],
                       capture_output=True, timeout=20)
        log.info("Restarted NetworkManager after recovery")
    except Exception as e:
        log.warning("Failed to restart NetworkManager: %s", e)


class NetworkHandler(SleepHandler):
    name = "network"

    def __init__(self) -> None:
        self._module: str | None = None
        self._pci_slot: str | None = None

    def is_available(self) -> bool:
        info = _find_wifi_pci() or _load_state()
        if info:
            self._module, self._pci_slot = info
            log.info("Found WiFi: module=%s pci=%s", self._module, self._pci_slot)
            return True
        return False

    def pre_suspend(self, sleep_type: str) -> None:
        if not self._pci_slot or not self._module:
            return
        # Keep the originals from an earlier pre_suspend that never got its
        # post_resume: by now the sysfs values are our own "0".
        saved = _load_saved_d3cold() if _load_state() == (self._module, self._pci_slot) else {}
        for target in _d3cold_targets(self._pci_slot):
            if target not in saved:
                value = _read_d3cold(target)
                if value is not None:
                    saved[target] = value
        _save_state(self._module, self._pci_slot, saved)
        _set_d3cold(self._pci_slot, False)

    def post_resume(self, sleep_type: str) -> None:
        if not self._pci_slot or not self._module:
            return

        # Give the hardware a moment to stabilize after resume
        time.sleep(1)

        saved = _load_saved_d3cold()
        if _device_healthy(self._pci_slot):
            log.info("WiFi PCI device %s is healthy after resume", self._pci_slot)
        else:
            log.warning("WiFi PCI device %s unhealthy after resume", self._pci_slot)
            _fallback_recovery(self._module, self._pci_slot)
        # Back to the pre-suspend runtime PM policy
        _restore_d3cold(self._pci_slot, saved)
        STATE_FILE.unlink(missing_ok=True)
