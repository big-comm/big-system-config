"""Tests for search and markup helpers."""

import os
import stat
import subprocess
from pathlib import Path

from base_page import _plain_markup
from main import WINDOW_HEIGHT, WINDOW_WIDTH, _highlight_text, _is_source_run


ROOT = Path(__file__).resolve().parents[1]
NUMLOCK_SCRIPT = ROOT / "usr/share/biglinux/biglinux-settings/usability/numLock.sh"


class TestHighlightText:
    """Tests for search text highlighting."""

    def test_basic_match(self):
        result = _highlight_text("Bluetooth", "blue")
        assert result == "<b>Blue</b>tooth"

    def test_no_match(self):
        result = _highlight_text("Bluetooth", "wifi")
        assert result == "Bluetooth"

    def test_html_chars_escaped(self):
        result = _highlight_text("A <b>test</b>", "test")
        assert "&lt;b&gt;" in result
        assert "<b>test</b>" in result

    def test_case_insensitive(self):
        result = _highlight_text("WiFi Settings", "wifi")
        assert "<b>WiFi</b>" in result

    def test_accents_are_ignored_and_original_text_is_bold(self):
        assert _highlight_text("Não dormir", "nao") == "<b>Não</b> dormir"
        assert _highlight_text("Ação rápida", "RAPIDA") == "Ação <b>rápida</b>"

    def test_empty_text(self):
        result = _highlight_text("", "test")
        assert result == ""


def test_window_default_geometry_fits_small_screens():
    # Resizable window: the default must still fit a 1366x768 screen
    assert WINDOW_WIDTH <= 1366 and WINDOW_HEIGHT <= 768


def test_repository_run_uses_an_independent_application_instance():
    assert _is_source_run(ROOT / "usr/share/biglinux/biglinux-settings/main.py")
    assert not _is_source_run("/usr/share/biglinux/biglinux-settings/main.py")


class TestPlainMarkup:
    """Tests for plain translated text escaped for markup-aware GTK labels."""

    def test_ampersand_is_escaped(self):
        assert _plain_markup("Mídia & Nuvem") == "Mídia &amp; Nuvem"

    def test_existing_entity_is_not_double_escaped(self):
        assert _plain_markup("Media &amp; Cloud") == "Media &amp; Cloud"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _base_env(tmp_path: Path, desktop: str) -> tuple[dict[str, str], Path, Path]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    sddm_dir = tmp_path / "sddm.conf.d"
    home.mkdir()
    bin_dir.mkdir()
    sddm_dir.mkdir()

    env = os.environ.copy()
    env.update({
        "HOME": str(home),
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "XDG_CURRENT_DESKTOP": desktop,
        "XDG_SESSION_DESKTOP": desktop,
        "NUMLOCK_SDDM_CONF": str(tmp_path / "sddm.conf"),
        "NUMLOCK_SDDM_CONF_DIR": str(sddm_dir),
    })
    return env, home, bin_dir


def _install_numlockx(bin_dir: Path, exit_code: int = 0) -> Path:
    log = bin_dir.parent / "numlockx.log"
    _write_executable(
        bin_dir / "numlockx",
        f"""#!/bin/bash
echo "$@" >> "{log}"
exit {exit_code}
""",
    )
    return log


def _install_gsettings(bin_dir: Path, state_dir: Path) -> None:
    state_dir.mkdir()
    _write_executable(
        bin_dir / "gsettings",
        f"""#!/bin/bash
state_dir="{state_dir}"
schema="$2"
key="$3"
file="$state_dir/${{schema}}.${{key}}"
case "$1" in
  range)
    case "$schema:$key" in
      org.gnome.desktop.peripherals.keyboard:numlock-state|org.gnome.desktop.peripherals.keyboard:remember-numlock-state|org.gnome.settings-daemon.peripherals.keyboard:remember-numlock-state|org.cinnamon.desktop.peripherals.keyboard:numlock-state|org.cinnamon.desktop.peripherals.keyboard:remember-numlock-state|org.cinnamon.settings-daemon.peripherals.keyboard:numlock-state|org.cinnamon.settings-daemon.peripherals.keyboard:remember-numlock-state)
        echo "type b"
        exit 0
        ;;
    esac
    exit 1
    ;;
  get)
    if [ -f "$file" ]; then
      cat "$file"
    else
      echo "false"
    fi
    ;;
  set)
    echo "$4" > "$file"
    ;;
esac
""",
    )


class TestNumLockScript:
    """NumLock script behavior across supported desktops."""

    def test_gnome_ignores_numlockx_display_failure(self, tmp_path):
        env, _home, bin_dir = _base_env(tmp_path, "GNOME")
        _install_gsettings(bin_dir, tmp_path / "gsettings")
        _install_numlockx(bin_dir, exit_code=1)

        result = subprocess.run(
            [str(NUMLOCK_SCRIPT), "toggle", "true"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr

        check = subprocess.run(
            [str(NUMLOCK_SCRIPT), "check"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert check.stdout.strip() == "true"

    def test_xfce_writes_autostart_with_absolute_numlockx_path(self, tmp_path):
        env, home, bin_dir = _base_env(tmp_path, "XFCE")
        numlockx_log = _install_numlockx(bin_dir)
        desktop_file = home / ".config/autostart/numlockx.desktop"
        desktop_file.parent.mkdir(parents=True)
        desktop_file.write_text(
            "[Desktop Entry]\nExec=numlockx on\n", encoding="utf-8"
        )

        check = subprocess.run(
            [str(NUMLOCK_SCRIPT), "check"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert check.stdout.strip() == "false"

        result = subprocess.run(
            [str(NUMLOCK_SCRIPT), "toggle", "true"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr

        assert (
            f"Exec={bin_dir / 'numlockx'} on"
            in desktop_file.read_text(encoding="utf-8")
        )
        assert numlockx_log.read_text(encoding="utf-8").strip() == "on"

        check = subprocess.run(
            [str(NUMLOCK_SCRIPT), "check"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert check.stdout.strip() == "true"

        result = subprocess.run(
            [str(NUMLOCK_SCRIPT), "toggle", "false"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert not desktop_file.exists()

    def test_kde_updates_user_config_and_calls_root_helper(self, tmp_path):
        env, _home, bin_dir = _base_env(tmp_path, "KDE")
        _install_numlockx(bin_dir)
        pkexec_log = tmp_path / "pkexec.log"
        kde_state = tmp_path / "kde-numlock"

        _write_executable(
            bin_dir / "pkexec",
            f"""#!/bin/bash
echo "$@" >> "{pkexec_log}"
exit 0
""",
        )
        _write_executable(
            bin_dir / "kwriteconfig6",
            f"""#!/bin/bash
echo "${{@: -1}}" > "{kde_state}"
""",
        )
        _write_executable(
            bin_dir / "kreadconfig6",
            f"""#!/bin/bash
cat "{kde_state}" 2>/dev/null || true
""",
        )

        result = subprocess.run(
            [str(NUMLOCK_SCRIPT), "toggle", "true"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert "numLockRun.sh enable" in pkexec_log.read_text(encoding="utf-8")

        check = subprocess.run(
            [str(NUMLOCK_SCRIPT), "check"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert check.stdout.strip() == "true"

    def test_cinnamon_uses_available_gsettings_schema(self, tmp_path):
        env, _home, bin_dir = _base_env(tmp_path, "X-Cinnamon")
        _install_gsettings(bin_dir, tmp_path / "gsettings")
        _install_numlockx(bin_dir)

        result = subprocess.run(
            [str(NUMLOCK_SCRIPT), "toggle", "true"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr

        check = subprocess.run(
            [str(NUMLOCK_SCRIPT), "check"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert check.stdout.strip() == "true"
