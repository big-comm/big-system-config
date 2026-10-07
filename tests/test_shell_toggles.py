"""Run toggle scripts for real inside a sandbox.

Every desktop/system tool the scripts call (kwriteconfig6, qdbus6, xfconf-query,
pkexec, pacman, ...) is replaced by a small fake on PATH that records its calls
and keeps state in files, and HOME points to a temporary directory. This checks
the contract the GUI relies on: after `toggle X`, `check` must print X, and a
failed or unsupported toggle must exit non-zero.
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "usr/share/biglinux/biglinux-settings"

FAKES = {
    # Records every call; reconfigure and friends just succeed.
    "_log": """
        printf '%s %s\\n' "$(basename "$0")" "$*" >> "$FAKE_STATE/calls.log"
    """,
    "xfconf-query": """
        . "$FAKE_BIN/_log"
        while [ $# -gt 0 ]; do
          case "$1" in
            -c) channel="$2"; shift 2 ;;
            -p) prop="$2"; shift 2 ;;
            -s) value="$2"; shift 2 ;;
            *) shift ;;
          esac
        done
        store="$FAKE_STATE/xfconf/$channel${prop//\\//_}"
        mkdir -p "$FAKE_STATE/xfconf"
        if [ -n "${value+x}" ]; then printf '%s\\n' "$value" > "$store"; exit 0; fi
        [ -f "$store" ] || exit 1
        cat "$store"
    """,
    "kwriteconfig6": """
        . "$FAKE_BIN/_log"
        while [ $# -gt 1 ]; do
          case "$1" in
            --file) file="$2"; shift 2 ;;
            --group) shift 2 ;;
            --key) key="$2"; shift 2 ;;
            *) shift ;;
          esac
        done
        [[ "$file" == /* ]] || file="$HOME/.config/$file"
        mkdir -p "$(dirname "$file")"
        # Like the real tool: replace the key instead of appending a duplicate
        { grep -v "^$key=" "$file" 2>/dev/null; printf '%s=%s\\n' "$key" "$1"; } > "$file.tmp"
        mv "$file.tmp" "$file"
    """,
    "kreadconfig6": """
        while [ $# -gt 0 ]; do
          case "$1" in
            --file) file="$2"; shift 2 ;;
            --group) shift 2 ;;
            --key) key="$2"; shift 2 ;;
            *) shift ;;
          esac
        done
        [[ "$file" == /* ]] || file="$HOME/.config/$file"
        grep "^$key=" "$file" 2>/dev/null | tail -1 | cut -d= -f2-
    """,
    "qdbus6": """
        . "$FAKE_BIN/_log"
        effects="$FAKE_STATE/effects"
        touch "$effects"
        case "$*" in
          *loadedEffects) cat "$effects" ;;
          *unloadEffect*) grep -vxF "${@: -1}" "$effects" > "$effects.tmp"; mv "$effects.tmp" "$effects" ;;
          *loadEffect*) printf '%s\\n' "${@: -1}" >> "$effects" ;;
          "org.kde.KWin") printf '%s\\n' /org/kde/KWin/InputDevice/event0 /org/kde/KWin/InputDevice/event1 ;;
          # event1 is a keyboard: it has no naturalScroll, setting it fails
          *event1*naturalScroll*) exit 1 ;;
        esac
        exit 0
    """,
    "qdbus": """
        . "$FAKE_BIN/_log"
        exit 127
    """,
    "pkexec": """
        . "$FAKE_BIN/_log"
        exit "${FAKE_PKEXEC_RC:-0}"
    """,
    "pacman": """
        . "$FAKE_BIN/_log"
        exit "${FAKE_PACMAN_Q_RC:-1}"
    """,
    "balooctl6": """
        . "$FAKE_BIN/_log"
        [ "$1" = status ] && exit "${FAKE_BALOO_STATUS_RC:-0}"
        exit 0
    """,
    "systemd-detect-virt": """
        echo "${FAKE_VIRT:-none}"
        [ "${FAKE_VIRT:-none}" = none ] && exit 1
        exit 0
    """,
}
NOOP_FAKES = ["gsettings", "killall", "systemctl", "sleep", "jamesdsp"]


@pytest.fixture
def sandbox(tmp_path):
    fake_bin = tmp_path / "bin"
    state = tmp_path / "state"
    home = tmp_path / "home"
    for directory in (fake_bin, state, home):
        directory.mkdir()

    for name, body in FAKES.items():
        (fake_bin / name).write_text("#!/bin/bash\n" + textwrap.dedent(body))
    for name in NOOP_FAKES:
        (fake_bin / name).write_text('#!/bin/bash\n. "$FAKE_BIN/_log"\nexit 0\n')
    for fake in fake_bin.iterdir():
        fake.chmod(0o755)

    class Sandbox:
        def __init__(self):
            self.home = home
            self.state = state
            self.env = {
                "PATH": f"{fake_bin}:/usr/bin:/bin",
                "HOME": str(home),
                "USER": "tester",
                "LANG": "C.UTF-8",
                "FAKE_BIN": str(fake_bin),
                "FAKE_STATE": str(state),
                "XDG_STATE_HOME": str(home / ".local/state"),
            }

        def run(self, script, *args, **env):
            merged = {**self.env, **{k: str(v) for k, v in env.items()}}
            return subprocess.run(
                [str(SCRIPTS / script), *args],
                env=merged,
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )

        def check(self, script, **env):
            result = self.run(script, "check", **env)
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

        def calls(self):
            log = state / "calls.log"
            return log.read_text().splitlines() if log.exists() else []

    return Sandbox()


# --- window buttons ----------------------------------------------------------


@pytest.mark.parametrize("desktop", ["XFCE", "KDE"])
def test_window_buttons_check_follows_toggle(sandbox, desktop):
    script = "usability/windowButtonOnLeftSide.sh"
    for state in ["true", "false", "true"]:
        result = sandbox.run(script, "toggle", state, XDG_CURRENT_DESKTOP=desktop)
        assert result.returncode == 0, result.stderr
        assert sandbox.check(script, XDG_CURRENT_DESKTOP=desktop) == state


def test_window_buttons_kde_reconfigures_with_qdbus6(sandbox):
    sandbox.run(
        "usability/windowButtonOnLeftSide.sh", "toggle", "true", XDG_CURRENT_DESKTOP="KDE"
    )
    calls = sandbox.calls()
    assert any(c.startswith("qdbus6 ") and "reconfigure" in c for c in calls)
    assert not any(c.startswith("qdbus ") for c in calls)


# --- unsupported desktop ------------------------------------------------------


@pytest.mark.parametrize(
    "script",
    [
        "usability/windowButtonOnLeftSide.sh",
        "usability/recentFiles.sh",
        "usability/kzones.sh",
        "devices/reverse-mouse_scroll.sh",
        "performance/disableBalooIndexer.sh",
        "performance/disableVisualEffects.sh",
    ],
)
def test_toggle_on_unsupported_desktop_fails(sandbox, script):
    assert sandbox.check(script, XDG_CURRENT_DESKTOP="Unknown") == "unsupported"
    result = sandbox.run(script, "toggle", "true", XDG_CURRENT_DESKTOP="Unknown")
    assert result.returncode != 0


def test_recent_files_is_unsupported_on_xfce_and_leaves_session_alone(sandbox):
    script = "usability/recentFiles.sh"
    assert sandbox.check(script, XDG_CURRENT_DESKTOP="XFCE") == "unsupported"
    assert sandbox.run(script, "toggle", "true", XDG_CURRENT_DESKTOP="XFCE").returncode
    assert not any(c.startswith("xfconf-query") for c in sandbox.calls())


# --- visual effects -------------------------------------------------------------


def test_visual_effects_round_trip_restores_every_effect(sandbox):
    script = "performance/disableVisualEffects.sh"
    effects = ["blur", "slide", "zoom"]
    (sandbox.state / "effects").write_text("\n".join(effects) + "\n")

    assert sandbox.check(script, XDG_CURRENT_DESKTOP="KDE") == "false"
    assert sandbox.run(script, "toggle", "true", XDG_CURRENT_DESKTOP="KDE").returncode == 0
    assert sandbox.check(script, XDG_CURRENT_DESKTOP="KDE") == "true"
    saved = sandbox.home / ".config/biglinux-settings/effectsEnable"
    assert saved.read_text().split() == effects

    # A second "disable" with nothing loaded must not wipe the saved list.
    assert sandbox.run(script, "toggle", "true", XDG_CURRENT_DESKTOP="KDE").returncode == 0
    assert saved.read_text().split() == effects

    assert sandbox.run(script, "toggle", "false", XDG_CURRENT_DESKTOP="KDE").returncode == 0
    assert sorted((sandbox.state / "effects").read_text().split()) == effects
    assert sandbox.check(script, XDG_CURRENT_DESKTOP="KDE") == "false"


def test_visual_effects_restore_without_saved_list(sandbox):
    result = sandbox.run(
        "performance/disableVisualEffects.sh", "toggle", "false", XDG_CURRENT_DESKTOP="KDE"
    )
    assert result.returncode == 0
    assert "No such file" not in result.stderr


# --- reverse scroll ---------------------------------------------------------------


def test_reverse_scroll_ignores_devices_without_scroll(sandbox):
    script = "devices/reverse-mouse_scroll.sh"
    result = sandbox.run(script, "toggle", "true", XDG_CURRENT_DESKTOP="KDE")
    assert result.returncode == 0
    assert sandbox.check(script, XDG_CURRENT_DESKTOP="KDE") == "true"


# --- privileged installs -----------------------------------------------------------


def test_kzones_stops_when_install_is_cancelled(sandbox):
    result = sandbox.run(
        "usability/kzones.sh", "toggle", "true", XDG_CURRENT_DESKTOP="KDE", FAKE_PKEXEC_RC=126
    )
    assert result.returncode == 126
    assert not any(c.startswith("kwriteconfig6") for c in sandbox.calls())


def test_jamesdsp_stops_when_install_is_cancelled(sandbox):
    result = sandbox.run("devices/jamesdsp.sh", "toggle", "true", FAKE_PKEXEC_RC=126)
    assert result.returncode == 126
    assert not (sandbox.home / ".config/jamesdsp").exists()
    assert not any(c.startswith("jamesdsp") for c in sandbox.calls())


def test_ollama_share_works_without_optional_session_variables(sandbox):
    # LANGUAGE and XAUTHORITY are commonly unset (e.g. on Wayland); with
    # `set -u` they used to abort the script before pkexec ran.
    result = sandbox.run("ai/ollamaShare.sh", "toggle", "true")
    assert result.returncode == 0, result.stderr
    assert any(c.startswith("pkexec ") for c in sandbox.calls())


# --- ComfyUI ---------------------------------------------------------------------


def test_comfyui_ignores_pid_reused_by_another_process(sandbox):
    other = subprocess.Popen(["/bin/sleep", "30"])
    try:
        state_dir = sandbox.home / ".local/state/biglinux-settings"
        state_dir.mkdir(parents=True)
        (state_dir / "comfyui.pid").write_text(f"{other.pid}\n")
        assert sandbox.check("ai/comfyUIRun.sh") == "false"
    finally:
        other.kill()
        other.wait()


# --- recent files / Baloo ------------------------------------------------------------


@pytest.mark.parametrize("baloo_enabled", [True, False])
def test_recent_files_respects_baloo_switch(sandbox, baloo_enabled):
    result = sandbox.run(
        "usability/recentFilesRun.sh",
        "enable",
        FAKE_BALOO_STATUS_RC=0 if baloo_enabled else 1,
    )
    assert result.returncode == 0, result.stderr
    reenabled = any(c == "balooctl6 enable" for c in sandbox.calls())
    assert reenabled is baloo_enabled


# --- check output contract -------------------------------------------------------------


VALID_CHECK_OUTPUT = {"true", "false", "true_disabled", "unsupported"}


@pytest.mark.parametrize(
    "script", sorted(p.relative_to(SCRIPTS).as_posix() for p in (SCRIPTS / "preload").glob("*.sh"))
)
def test_preload_check_output_is_valid(sandbox, script):
    assert sandbox.check(script) in VALID_CHECK_OUTPUT


def test_smart_monitor_is_unsupported_in_vm(sandbox):
    assert sandbox.check("performance/unloadSmartMonitor.sh", FAKE_VIRT="kvm") == "unsupported"


def test_no_check_script_prints_empty_string_for_unavailable():
    offenders = [
        path.relative_to(SCRIPTS).as_posix()
        for path in SCRIPTS.rglob("*.sh")
        if 'echo ""' in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


@pytest.mark.skipif(os.geteuid() == 0, reason="scripts behave differently as root")
def test_sandbox_does_not_touch_real_home(sandbox):
    assert sandbox.env["HOME"] != os.path.expanduser("~")
