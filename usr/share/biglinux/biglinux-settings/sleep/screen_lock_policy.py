#!/usr/bin/python3
"""Turn the desktop screen lock off and back on, restoring the previous values."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "biglinux-settings"
    / "screen-lock"
)
MISSING = "__BIGLINUX_MISSING__"

# (schema, key, unlocked value) per desktop. lock-enabled covers idle and
# suspend; the lid-close lock asked for by gsd-power goes through the shell's
# Lock() method, which only honours disable-lock-screen.
GSETTINGS_KEYS = {
    "cinnamon": (
        ("org.cinnamon.desktop.screensaver", "lock-enabled", "false"),
        ("org.cinnamon.desktop.lockdown", "disable-lock-screen", "true"),
    ),
    "gnome": (
        ("org.gnome.desktop.screensaver", "lock-enabled", "false"),
        ("org.gnome.desktop.lockdown", "disable-lock-screen", "true"),
    ),
}
# kscreenlockerrc: idle lock and lock when waking from suspend
KDE_KEYS = ("Autolock", "LockOnResume")
# (channel, property): screensaver lock and lock before suspend
XFCE_KEYS = (
    ("xfce4-screensaver", "/lock/enabled"),
    ("xfce4-power-manager", "/xfce4-power-manager/lock-screen-suspend-hibernate"),
)


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


def desktop() -> str:
    value = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    for name in ("cinnamon", "gnome", "xfce"):
        if name in value:
            return name
    if "kde" in value or "plasma" in value:
        return "kde"
    return "unknown"


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def gsettings_keys() -> tuple[tuple[str, str, str], ...]:
    """Lock keys of the first desktop whose schemas are all installed."""
    if not command_exists("gsettings"):
        return ()
    schemas = set(run(["gsettings", "list-schemas"]).stdout.splitlines())
    current = desktop()
    candidates = sorted(GSETTINGS_KEYS, key=lambda name: name != current)
    for name in candidates:
        keys = GSETTINGS_KEYS[name]
        if all(schema in schemas for schema, _key, _value in keys):
            return keys
    return ()


def backend() -> str | None:
    current = desktop()
    if (
        current == "kde"
        and command_exists("kwriteconfig6")
        and command_exists("kreadconfig6")
    ):
        return "kde"
    if current == "xfce" and command_exists("xfconf-query"):
        return "xfce"
    if gsettings_keys():
        return "gsettings"
    return None


def kconfig_command(tool: str, key: str) -> list[str]:
    return [tool, "--file", "kscreenlockerrc", "--group", "Daemon", "--key", key]


def read_values(selected: str) -> list[dict[str, str]]:
    if selected == "gsettings":
        return [
            {
                "schema": schema,
                "key": key,
                "value": value,
                "old_value": run(["gsettings", "get", schema, key]).stdout.strip(),
            }
            for schema, key, value in gsettings_keys()
        ]
    if selected == "kde":
        values = []
        for key in KDE_KEYS:
            command = kconfig_command("kreadconfig6", key) + ["--default", MISSING]
            values.append({"key": key, "old_value": run(command).stdout.strip()})
        return values
    if selected == "xfce":
        values = []
        for channel, key in XFCE_KEYS:
            result = run(["xfconf-query", "-c", channel, "-p", key], check=False)
            value = result.stdout.strip() if result.returncode == 0 else MISSING
            values.append({"channel": channel, "key": key, "old_value": value})
        return values
    return []


def backup_path(selected: str) -> Path:
    return CONFIG_DIR / f"{selected}.json"


def write_backup(selected: str, values: list[dict[str, str]]) -> None:
    backup = backup_path(selected)
    if backup.exists():
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = backup.with_suffix(".tmp")
    temporary.write_text(json.dumps({"backend": selected, "values": values}, indent=2))
    temporary.replace(backup)


def refresh_kde() -> None:
    if command_exists("qdbus6"):
        run(
            ["qdbus6", "org.freedesktop.ScreenSaver", "/ScreenSaver", "configure"],
            check=False,
        )


def set_unlocked(selected: str) -> None:
    for item in read_values(selected):
        if selected == "gsettings":
            run(["gsettings", "set", item["schema"], item["key"], item["value"]])
        elif selected == "kde":
            run(kconfig_command("kwriteconfig6", item["key"]) + ["--type", "bool", "false"])
        elif selected == "xfce":
            command = ["xfconf-query", "-c", item["channel"], "-p", item["key"]]
            if item["old_value"] == MISSING:
                command.extend(["-n", "-t", "bool"])
            run(command + ["-s", "false"])
    if selected == "kde":
        refresh_kde()


def restore_backup(backup: Path) -> None:
    data = json.loads(backup.read_text())
    selected = str(data["backend"])
    for item in data.get("values", []):
        if selected == "gsettings":
            run(["gsettings", "set", item["schema"], item["key"], item["old_value"]])
        elif selected == "kde":
            command = kconfig_command("kwriteconfig6", item["key"])
            if item["old_value"] == MISSING:
                run(command + ["--delete", ""])
            else:
                run(command + [item["old_value"]])
        elif selected == "xfce":
            command = ["xfconf-query", "-c", item["channel"], "-p", item["key"]]
            if item["old_value"] == MISSING:
                run(command + ["-r"], check=False)
            else:
                run(command + ["-s", item["old_value"]])
    if selected == "kde":
        refresh_kde()
    backup.unlink()


def restore_all() -> None:
    for selected in ("gsettings", "kde", "xfce"):
        backup = backup_path(selected)
        if backup.exists():
            restore_backup(backup)


def is_unlocked(selected: str | None) -> bool:
    if not selected:
        return False
    values = read_values(selected)
    return bool(values) and all(
        str(item["old_value"]).strip("'\"") == item.get("value", "false")
        for item in values
    )


def enable(selected: str | None) -> int:
    """Back up the lock settings and turn the lock off; roll back on failure."""
    if not selected:
        return 1
    try:
        write_backup(selected, read_values(selected))
        set_unlocked(selected)
    except (OSError, ValueError, subprocess.SubprocessError):
        try:
            restore_all()
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return 1
    return 0


def disable() -> int:
    try:
        restore_all()
    except (OSError, ValueError, subprocess.SubprocessError):
        return 1
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"check", "toggle"}:
        return 2
    selected = backend()
    if sys.argv[1] == "check":
        print("true" if is_unlocked(selected) else "false")
        return 0
    if len(sys.argv) != 3 or sys.argv[2] not in {"true", "false"}:
        return 2
    return enable(selected) if sys.argv[2] == "true" else disable()


if __name__ == "__main__":
    raise SystemExit(main())
