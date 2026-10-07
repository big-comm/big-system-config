"""Disk health monitoring switch (performance/unloadSmartMonitor.sh).

Regression: with smartmontools not installed, turning monitoring on ran
`systemctl enable --now smartd` and failed with "Unit smartd.service does not
exist". It must install smartmontools first.
"""

import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "usr/share/biglinux/biglinux-settings"
INSTALLED = "/usr/share/biglinux/biglinux-settings"
SCRIPT = "performance/unloadSmartMonitor.sh"

FAKES = {
    # smartd.service exists once $STATE/installed exists; active once $STATE/active
    "systemctl": """
        echo "systemctl $*" >> "$STATE/calls.log"
        case "$1" in
          list-unit-files)
            [ -e "$STATE/installed" ] && echo "smartd.service disabled disabled"
            exit 0 ;;
          is-active)
            [ -e "$STATE/active" ]; exit $? ;;
          enable)
            [ -e "$STATE/installed" ] || { echo "Failed to enable unit: Unit smartd.service does not exist" >&2; exit 1; }
            touch "$STATE/active"; exit 0 ;;
          disable)
            rm -f "$STATE/active"; exit 0 ;;
          daemon-reload) exit 0 ;;
        esac
        exit 0
    """,
    "pacman": """
        echo "pacman $*" >> "$STATE/calls.log"
        [ "${FAKE_PACMAN_RC:-0}" = 0 ] || exit "$FAKE_PACMAN_RC"
        touch "$STATE/installed"
    """,
    "systemd-detect-virt": """
        echo none; exit 1
    """,
}


@pytest.fixture
def env(tmp_path):
    fake_bin = tmp_path / "bin"
    state = tmp_path / "state"
    fake_bin.mkdir()
    state.mkdir()
    for name, body in FAKES.items():
        path = fake_bin / name
        path.write_text("#!/bin/bash\n" + textwrap.dedent(body))
        path.chmod(0o755)
    pkexec = fake_bin / "pkexec"
    pkexec.write_text(
        "#!/bin/bash\n"
        'echo "pkexec $*" >> "$STATE/calls.log"\n'
        f'prefix="{INSTALLED}"; script="{SCRIPTS}${{1#"$prefix"}}"; shift\n'
        'exec "$script" "$@"\n'
    )
    pkexec.chmod(0o755)

    class Env:
        def __init__(self):
            self.state = state
            self.vars = {"PATH": f"{fake_bin}:/usr/bin:/bin", "STATE": str(state)}

        def run(self, *args, **extra):
            return subprocess.run(
                [str(SCRIPTS / SCRIPT), *args],
                env={**self.vars, **{k: str(v) for k, v in extra.items()}},
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )

        def check(self):
            return self.run("check").stdout.strip()

        def calls(self):
            log = state / "calls.log"
            return log.read_text().splitlines() if log.exists() else []

    return Env()


def test_enabling_monitoring_installs_smartmontools_when_missing(env):
    # Script semantics: "true" = monitor unloaded; the UI shows it inverted
    assert env.check() == "true"
    result = env.run("toggle", "false")
    assert result.returncode == 0, result.stderr
    calls = env.calls()
    assert any(c.startswith("pacman -S --needed --noconfirm smartmontools") for c in calls)
    assert "systemctl enable --now smartd.service" in calls
    assert env.check() == "false"
    # one password prompt for install + enable
    assert sum(c.startswith("pkexec ") for c in calls) == 1


def test_enabling_monitoring_does_not_reinstall(env):
    (env.state / "installed").touch()
    assert env.run("toggle", "false").returncode == 0
    assert not any(c.startswith("pacman") for c in env.calls())
    assert env.check() == "false"


def test_failed_install_reports_failure(env):
    result = env.run("toggle", "false", FAKE_PACMAN_RC=1)
    assert result.returncode != 0
    assert not any("enable" in c for c in env.calls() if c.startswith("systemctl"))
    assert env.check() == "true"


def test_unloading_without_smartd_is_already_done(env):
    result = env.run("toggle", "true")
    assert result.returncode == 0
    assert not any(c.startswith("pkexec") for c in env.calls())


def test_unloading_stops_smartd(env):
    (env.state / "installed").touch()
    (env.state / "active").touch()
    assert env.check() == "false"
    assert env.run("toggle", "true").returncode == 0
    assert "systemctl disable --now smartd.service" in env.calls()
    assert env.check() == "true"


def test_invalid_arguments(env):
    assert env.run("toggle", "maybe").returncode == 2
    root_helper = subprocess.run(
        [str(SCRIPTS / "performance/unloadSmartMonitorRun.sh"), "bogus"],
        env=env.vars,
        capture_output=True,
    )
    assert root_helper.returncode == 2
