#!/usr/bin/python3
"""Manage lid-close policies without blocking unrelated suspend requests."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "biglinux-settings"
    / "lid-policy"
)
ROOT_HELPER = Path(__file__).with_name("lid-policy-root.sh")
MISSING = "__BIGLINUX_MISSING__"


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


def desktop() -> str:
    value = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "cinnamon" in value:
        return "cinnamon"
    if "gnome" in value:
        return "gnome"
    if "kde" in value or "plasma" in value:
        return "kde"
    if "xfce" in value:
        return "xfce"
    return "unknown"


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def gsettings_lid_key(source: str) -> tuple[str, str] | None:
    if not command_exists("gsettings"):
        return None
    schemas = set(run(["gsettings", "list-schemas"]).stdout.splitlines())
    schemas_by_desktop = {
        "cinnamon": "org.cinnamon.settings-daemon.plugins.power",
        "gnome": "org.gnome.settings-daemon.plugins.power",
    }
    preferred = schemas_by_desktop.get(desktop())
    candidates = [preferred] if preferred else []
    candidates.extend(
        schema for schema in schemas_by_desktop.values() if schema != preferred
    )
    key = f"lid-close-{'ac' if source == 'ac' else 'battery'}-action"
    for schema in candidates:
        if schema not in schemas:
            continue
        keys = set(run(["gsettings", "list-keys", schema]).stdout.splitlines())
        if key in keys:
            return schema, key
    return None


def backend(source: str) -> str | None:
    current = desktop()
    if (
        current == "kde"
        and command_exists("kwriteconfig6")
        and command_exists("kreadconfig6")
    ):
        return "kde"
    if current == "xfce" and command_exists("xfconf-query"):
        return "xfce"
    if gsettings_lid_key(source):
        return "gsettings"
    return None


def kde_items(source: str) -> list[dict[str, object]]:
    profiles = ["AC"] if source == "ac" else ["Battery", "LowBattery"]
    items: list[dict[str, object]] = []
    for profile in profiles:
        items.extend(
            [
                {
                    "file": "powerdevilrc",
                    "groups": [profile, "SuspendAndShutdown"],
                    "key": "LidAction",
                    "value": "0",
                },
                {
                    "file": "powermanagementprofilesrc",
                    "groups": [profile, "HandleButtonEvents"],
                    "key": "lidAction",
                    "value": "0",
                },
            ]
        )
    return items


def kconfig_command(tool: str, item: dict[str, object]) -> list[str]:
    command = [tool, "--file", str(item["file"])]
    for group in item["groups"]:
        command.extend(["--group", str(group)])
    command.extend(["--key", str(item["key"])])
    return command


def xfce_key(source: str) -> str:
    return f"/xfce4-power-manager/lid-action-on-{'ac' if source == 'ac' else 'battery'}"


def read_values(selected: str, source: str) -> list[dict[str, object]]:
    if selected == "gsettings":
        item = gsettings_lid_key(source)
        if not item:
            return []
        schema, key = item
        value = run(["gsettings", "get", schema, key]).stdout.strip()
        return [{"schema": schema, "key": key, "old_value": value}]
    if selected == "kde":
        values = []
        for item in kde_items(source):
            command = kconfig_command("kreadconfig6", item)
            command.extend(["--default", MISSING])
            value = run(command).stdout.strip()
            values.append({**item, "old_value": value})
        return values
    if selected == "xfce":
        key = xfce_key(source)
        result = run(
            ["xfconf-query", "-c", "xfce4-power-manager", "-p", key], check=False
        )
        value = result.stdout.strip() if result.returncode == 0 else MISSING
        return [{"key": key, "old_value": value, "value": "4"}]
    return []


def backup_path(source: str, selected: str) -> Path:
    return CONFIG_DIR / f"{source}-{selected}.json"


def write_backup(source: str, selected: str, values: list[dict[str, object]]) -> None:
    backup = backup_path(source, selected)
    if backup.exists():
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = backup.with_suffix(".tmp")
    temporary.write_text(json.dumps({"backend": selected, "values": values}, indent=2))
    temporary.replace(backup)


def set_never(selected: str, source: str) -> None:
    values = read_values(selected, source)
    if not values:
        return
    if selected == "gsettings":
        item = values[0]
        run(["gsettings", "set", str(item["schema"]), str(item["key"]), "nothing"])
    elif selected == "kde":
        for item in values:
            run(kconfig_command("kwriteconfig6", item) + [str(item["value"])])
        refresh_kde()
    elif selected == "xfce":
        item = values[0]
        command = ["xfconf-query", "-c", "xfce4-power-manager", "-p", str(item["key"])]
        if item["old_value"] == MISSING:
            command.extend(["-n", "-t", "uint"])
        run(command + ["-s", "4"])


def restore_backup(backup: Path) -> None:
    data = json.loads(backup.read_text())
    selected = str(data["backend"])
    for item in data.get("values", []):
        if selected == "gsettings":
            run(["gsettings", "set", item["schema"], item["key"], item["old_value"]])
        elif selected == "kde":
            command = kconfig_command("kwriteconfig6", item)
            if item["old_value"] == MISSING:
                run(command + ["--delete", ""])
            else:
                run(command + [str(item["old_value"])])
        elif selected == "xfce":
            command = ["xfconf-query", "-c", "xfce4-power-manager", "-p", item["key"]]
            if item["old_value"] == MISSING:
                run(command + ["-r"], check=False)
            else:
                run(command + ["-s", str(item["old_value"])])
    if selected == "kde":
        refresh_kde()
    backup.unlink()


def restore_all(source: str) -> None:
    for selected in ("gsettings", "kde", "xfce"):
        backup = backup_path(source, selected)
        if backup.exists():
            restore_backup(backup)


def refresh_kde() -> None:
    if not command_exists("qdbus6"):
        return
    base = ["qdbus6", "org.kde.Solid.PowerManagement", "/org/kde/Solid/PowerManagement"]
    run(base + ["org.kde.Solid.PowerManagement.reparseConfiguration"], check=False)
    run(base + ["org.kde.Solid.PowerManagement.refreshStatus"], check=False)


def native_is_never(selected: str | None, source: str) -> bool:
    if not selected:
        return True
    values = read_values(selected, source)
    if not values:
        return False
    if selected == "gsettings":
        return str(values[0]["old_value"]).strip("'\"") == "nothing"
    expected = "0" if selected == "kde" else "4"
    return all(str(item["old_value"]) == expected for item in values)


def root_command(action: str, source: str, state: bool | None = None) -> list[str]:
    command = [str(ROOT_HELPER), action, source]
    if state is not None:
        command.append("true" if state else "false")
        if os.geteuid() != 0:
            command.insert(0, "pkexec")
    return command


def root_is_never(source: str) -> bool:
    result = run(root_command("check", source), check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def main() -> int:
    if (
        len(sys.argv) < 3
        or sys.argv[1] not in {"check", "toggle"}
        or sys.argv[2] not in {"ac", "battery"}
    ):
        return 2
    action, source = sys.argv[1:3]
    selected = backend(source)
    if action == "check":
        print(
            "true"
            if root_is_never(source) and native_is_never(selected, source)
            else "false"
        )
        return 0
    if len(sys.argv) != 4 or sys.argv[3] not in {"true", "false"}:
        return 2
    if sys.argv[3] == "true":
        return enable_never(selected, source)
    return disable_never(source)


def _restore_quietly(source: str) -> None:
    """Best-effort rollback of the native settings backups."""
    try:
        restore_all(source)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def enable_never(selected: str | None, source: str) -> int:
    """Back up and force the "never" lid policy; roll back on failure."""
    try:
        if selected:
            write_backup(source, selected, read_values(selected, source))
            set_never(selected, source)
        result = run(root_command("toggle", source, True), check=False)
    except (OSError, ValueError, subprocess.SubprocessError):
        _restore_quietly(source)
        return 1
    if result.returncode != 0:
        _restore_quietly(source)
        return 1
    return 0


def disable_never(source: str) -> int:
    """Drop the root policy, then restore the native settings backups."""
    try:
        result = run(root_command("toggle", source, False), check=False)
    except OSError:
        return 1
    if result.returncode != 0:
        return 1
    try:
        restore_all(source)
    except (OSError, ValueError, subprocess.SubprocessError):
        try:
            run(root_command("toggle", source, True), check=False)
        except OSError:
            pass
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
