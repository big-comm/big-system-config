"""Package rename biglinux-settings -> big-system-config.

Regression: removing the old package saved the user's /etc/biglinux/sleep.conf
as sleep.conf.pacsave and installed the default (every handler off). The
Realtek Wi-Fi protection was silently disabled and the adapter did not come
back after the next suspend. post_install must restore the user's choices.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTLET = ROOT / "pkgbuild/big-system-config.install"

DEFAULT = """# BigLinux Sleep Handler Configuration
[handlers]
backlight=false
network=false
"""

pytestmark = pytest.mark.skipif(
    os.geteuid() == 0, reason="the test-only path override is ignored as root"
)


def run_post_install(conf: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'. "{SCRIPTLET}"; post_install'],
        env={"PATH": "/usr/bin:/bin", "BIG_SYSTEM_CONFIG_SLEEP_CONF": str(conf)},
        capture_output=True,
        text=True,
        timeout=30,
    )


def handlers(conf: Path) -> dict[str, str]:
    values = {}
    for line in conf.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def test_restores_wifi_protection_from_pacsave(tmp_path):
    conf = tmp_path / "sleep.conf"
    conf.write_text(DEFAULT)
    # The file saved from the user's machine: Wi-Fi protection on
    (tmp_path / "sleep.conf.pacsave").write_text(
        "[handlers]\nbacklight=false\nnetwork=true\ngnome=false\n"
    )

    result = run_post_install(conf)

    assert result.returncode == 0, result.stderr
    assert handlers(conf) == {"backlight": "false", "network": "true"}
    assert not (tmp_path / "sleep.conf.pacsave").exists()
    assert (tmp_path / "sleep.conf.pacsave.migrated").exists()
    assert "restored suspend options" in result.stdout


def test_reads_only_the_handlers_section_and_tolerates_formatting(tmp_path):
    conf = tmp_path / "sleep.conf"
    conf.write_text(DEFAULT)
    (tmp_path / "sleep.conf.pacsave").write_text(
        "[other]\nnetwork=false\n[handlers]\n  BackLight = TRUE  # on\nNetwork=true\n"
    )
    assert run_post_install(conf).returncode == 0
    assert handlers(conf) == {"backlight": "true", "network": "true"}


def test_without_pacsave_nothing_changes(tmp_path):
    conf = tmp_path / "sleep.conf"
    conf.write_text(DEFAULT)
    assert run_post_install(conf).returncode == 0
    assert conf.read_text() == DEFAULT


def test_invalid_saved_values_are_ignored(tmp_path):
    conf = tmp_path / "sleep.conf"
    conf.write_text(DEFAULT)
    saved = tmp_path / "sleep.conf.pacsave"
    saved.write_text("[handlers]\nnetwork=maybe\n")
    assert run_post_install(conf).returncode == 0
    assert conf.read_text() == DEFAULT
    assert saved.exists()  # nothing migrated: keep it for the user


def test_pkgbuild_ships_the_scriptlet():
    pkgbuild = (ROOT / "pkgbuild/PKGBUILD").read_text()
    assert "install=big-system-config.install" in pkgbuild
    assert "backup=('etc/biglinux/sleep.conf')" in pkgbuild
