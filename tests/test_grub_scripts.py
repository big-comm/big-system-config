"""Run the GRUB editing scripts for real inside a sandbox.

The scripts edit /etc/default/grub as root and regenerate grub.cfg. Here the
GRUB file is a temporary copy (BIGLINUX_GRUB_FILE), update-grub/grub-mkconfig
are fakes that record their calls and succeed or fail on demand
(BIGLINUX_GRUB_UPDATE, FAKE_GRUB_RC), and pkexec is a fake that just runs the
repository copy of the requested script.
"""

import fcntl
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "usr/share/biglinux/biglinux-settings"
INSTALLED = "/usr/share/biglinux/biglinux-settings"

FAKES = {
    "update-grub": """
        echo "$(basename "$0") $*" >> "$FAKE_STATE/grub-calls.log"
        exit "${FAKE_GRUB_RC:-0}"
    """,
    "grub-mkconfig": """
        echo "$(basename "$0") $*" >> "$FAKE_STATE/grub-calls.log"
        exit "${FAKE_GRUB_RC:-0}"
    """,
    # Runs the repository copy instead of the installed one; keeps the env.
    "pkexec": f"""
        cmd="$1"; shift
        prefix="{INSTALLED}"
        [[ "$cmd" == "$prefix"/* ]] && cmd="$FAKE_SCRIPTS${{cmd#"$prefix"}}"
        exec bash "$cmd" "$@"
    """,
    # Pretend to be root only when asked to (s2idle.sh re-execs via pkexec).
    "id": """
        if [ "$1" = "-u" ] && [ -n "$FAKE_ROOT" ]; then echo 0; exit 0; fi
        exec /usr/bin/id "$@"
    """,
}


@pytest.fixture
def sandbox(tmp_path):
    fake_bin = tmp_path / "bin"
    state = tmp_path / "state"
    fake_bin.mkdir()
    state.mkdir()
    for name, body in FAKES.items():
        fake = fake_bin / name
        fake.write_text("#!/bin/bash\n" + textwrap.dedent(body))
        fake.chmod(0o755)
    grub = tmp_path / "grub"

    class Sandbox:
        def __init__(self):
            self.grub = grub
            self.env = {
                "PATH": f"{fake_bin}:/usr/bin:/bin",
                "HOME": str(tmp_path),
                "USER": "tester",
                "LANG": "C",
                "FAKE_STATE": str(state),
                "FAKE_SCRIPTS": str(SCRIPTS),
                "FAKE_ROOT": "1",
                "BIGLINUX_GRUB_FILE": str(grub),
                "BIGLINUX_GRUB_UPDATE": str(fake_bin / "update-grub"),
            }

        def write(self, text):
            self.grub.write_text(textwrap.dedent(text).lstrip())

        def read(self):
            return self.grub.read_text()

        def run(self, script, *args, **env):
            merged = {**self.env, **{k: str(v) for k, v in env.items()}}
            return subprocess.run(
                ["bash", str(SCRIPTS / script), *args],
                env=merged,
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )

        def check(self, script):
            result = self.run(script, "check")
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

        def toggle(self, script, value, **env):
            return self.run(script, "toggle", value, **env)

        def grub_calls(self):
            log = state / "grub-calls.log"
            return log.read_text().splitlines() if log.exists() else []

    return Sandbox()


def active_line(text, key="GRUB_CMDLINE_LINUX_DEFAULT"):
    lines = [line for line in text.splitlines() if line.startswith(f"{key}=")]
    assert lines, text
    return lines[-1]


CMDLINE_TOGGLES = [
    ("performance/noWatchdog.sh", ["nowatchdog", "tsc=nowatchdog"]),
    ("performance/meltdownMitigations.sh", ["mitigations=off"]),
    ("sleep/s2idle.sh", ["mem_sleep_default=s2idle"]),
]


# --- kernel command line toggles ----------------------------------------------


@pytest.mark.parametrize("script,tokens", CMDLINE_TOGGLES)
@pytest.mark.parametrize(
    "initial",
    [
        'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"',
        "GRUB_CMDLINE_LINUX_DEFAULT='quiet splash'",
        "GRUB_CMDLINE_LINUX_DEFAULT=quiet",
    ],
)
def test_cmdline_round_trip(sandbox, script, tokens, initial):
    sandbox.write(f'GRUB_TIMEOUT=5\n{initial}\nGRUB_CMDLINE_LINUX=""\n')
    assert sandbox.check(script) == "false"

    result = sandbox.toggle(script, "true")
    assert result.returncode == 0, result.stderr
    assert sandbox.check(script) == "true"
    words = active_line(sandbox.read()).split("=", 1)[1].strip("\"'").split()
    assert "quiet" in words
    for token in tokens:
        assert words.count(token) == 1

    result = sandbox.toggle(script, "false")
    assert result.returncode == 0, result.stderr
    assert sandbox.check(script) == "false"
    line = active_line(sandbox.read())
    assert "quiet" in line
    assert "  " not in line
    for token in tokens:
        assert token not in line
    assert len(sandbox.grub_calls()) == 2


@pytest.mark.parametrize("script,tokens", CMDLINE_TOGGLES)
def test_commented_line_is_ignored(sandbox, script, tokens):
    commented = f'#GRUB_CMDLINE_LINUX_DEFAULT="{" ".join(tokens)}"'
    sandbox.write(
        f'{commented}\n# {" ".join(tokens)}\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"\n'
    )
    assert sandbox.check(script) == "false"

    result = sandbox.toggle(script, "true")
    assert result.returncode == 0, result.stderr
    assert sandbox.check(script) == "true"
    text = sandbox.read()
    assert text.splitlines()[0] == commented
    for token in tokens:
        assert token in active_line(text)

    result = sandbox.toggle(script, "false")
    assert result.returncode == 0, result.stderr
    assert sandbox.check(script) == "false"
    assert sandbox.read().splitlines()[0] == commented


@pytest.mark.parametrize("script,tokens", CMDLINE_TOGGLES)
def test_tokens_in_other_order_are_removed(sandbox, script, tokens):
    mixed = " ".join([tokens[-1], "quiet", *tokens[:-1], "splash"])
    sandbox.write(f"GRUB_CMDLINE_LINUX_DEFAULT='{mixed}'\n")
    assert sandbox.check(script) == "true"

    result = sandbox.toggle(script, "false")
    assert result.returncode == 0, result.stderr
    assert sandbox.check(script) == "false"
    assert active_line(sandbox.read()) == "GRUB_CMDLINE_LINUX_DEFAULT='quiet splash'"


def test_mitigations_removal_leaves_no_junk(sandbox):
    sandbox.write('GRUB_CMDLINE_LINUX_DEFAULT="quiet mitigations=off splash"\n')
    result = sandbox.toggle("performance/meltdownMitigations.sh", "false")
    assert result.returncode == 0, result.stderr
    assert sandbox.read() == 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'


@pytest.mark.parametrize("script,tokens", CMDLINE_TOGGLES)
@pytest.mark.parametrize("value", ["true", "false"])
def test_failed_regeneration_restores_file(sandbox, script, tokens, value):
    if value == "true":
        original = 'GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n'
    else:
        original = f'GRUB_CMDLINE_LINUX_DEFAULT="quiet {" ".join(tokens)}"\n'
    sandbox.write(original)
    result = sandbox.toggle(script, value, FAKE_GRUB_RC=1)
    assert result.returncode != 0
    assert sandbox.read() == original
    assert sandbox.grub_calls()


@pytest.mark.parametrize("script,tokens", CMDLINE_TOGGLES)
def test_missing_regeneration_tool_restores_file(sandbox, script, tokens):
    original = 'GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n'
    sandbox.write(original)
    result = sandbox.toggle(
        script, "true", BIGLINUX_GRUB_UPDATE="/nonexistent/update-grub"
    )
    assert result.returncode != 0
    assert sandbox.read() == original


@pytest.mark.parametrize("script,tokens", CMDLINE_TOGGLES)
def test_already_enabled_does_not_regenerate(sandbox, script, tokens):
    sandbox.write(f'GRUB_CMDLINE_LINUX_DEFAULT="quiet {" ".join(tokens)}"\n')
    result = sandbox.toggle(script, "true")
    assert result.returncode == 0, result.stderr
    assert sandbox.grub_calls() == []


@pytest.mark.parametrize("script,tokens", CMDLINE_TOGGLES)
def test_invalid_state_exits_2(sandbox, script, tokens):
    original = 'GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n'
    sandbox.write(original)
    result = sandbox.toggle(script, "maybe")
    assert result.returncode == 2
    assert sandbox.read() == original
    assert sandbox.grub_calls() == []


@pytest.mark.parametrize(
    "script", ["performance/noWatchdogRun.sh", "performance/meltdownMitigationsRun.sh"]
)
def test_run_script_invalid_function_exits_2(sandbox, script):
    sandbox.write('GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n')
    assert sandbox.run(script, "bogus").returncode == 2
    assert sandbox.grub_calls() == []


def test_enable_falls_back_to_cmdline_linux(sandbox):
    sandbox.write("GRUB_CMDLINE_LINUX='quiet'\n")
    result = sandbox.toggle("performance/noWatchdog.sh", "true")
    assert result.returncode == 0, result.stderr
    assert sandbox.read() == "GRUB_CMDLINE_LINUX='quiet nowatchdog tsc=nowatchdog'\n"
    assert sandbox.check("performance/noWatchdog.sh") == "true"


# --- GRUB timeout ---------------------------------------------------------------


@pytest.mark.parametrize(
    "line", ["GRUB_TIMEOUT=1", 'GRUB_TIMEOUT="1"', "GRUB_TIMEOUT='1'"]
)
def test_fast_grub_check_accepts_quoted_values(sandbox, line):
    sandbox.write(f"{line}\n")
    assert sandbox.check("system/fastGrub.sh") == "true"


def test_fast_grub_check_ignores_commented_line(sandbox):
    sandbox.write("#GRUB_TIMEOUT=1\nGRUB_TIMEOUT=5\n")
    assert sandbox.check("system/fastGrub.sh") == "false"


def test_fast_grub_round_trip(sandbox):
    sandbox.write('#GRUB_TIMEOUT=3\nGRUB_TIMEOUT="5"\nGRUB_DEFAULT=saved\n')
    result = sandbox.toggle("system/fastGrub.sh", "true")
    assert result.returncode == 0, result.stderr
    assert sandbox.check("system/fastGrub.sh") == "true"
    assert sandbox.read() == "#GRUB_TIMEOUT=3\nGRUB_TIMEOUT=1\nGRUB_DEFAULT=saved\n"

    result = sandbox.toggle("system/fastGrub.sh", "false")
    assert result.returncode == 0, result.stderr
    assert sandbox.check("system/fastGrub.sh") == "false"
    assert sandbox.read() == "#GRUB_TIMEOUT=3\nGRUB_TIMEOUT=5\nGRUB_DEFAULT=saved\n"
    assert len(sandbox.grub_calls()) == 2


@pytest.mark.parametrize("value", ["true", "false"])
def test_grub_edit_keeps_link_and_mode(sandbox, tmp_path, value):
    # Edits and rollbacks rename a new file over the target, never truncate it.
    target = tmp_path / "default" / "grub"
    target.parent.mkdir()
    target.write_text("GRUB_TIMEOUT=5\n")
    target.chmod(0o640)
    sandbox.grub.symlink_to(target)
    inode = target.stat().st_ino
    result = sandbox.toggle("system/fastGrub.sh", "true", FAKE_GRUB_RC=0 if value == "true" else 1)
    expected = "GRUB_TIMEOUT=1\n" if value == "true" else "GRUB_TIMEOUT=5\n"
    assert sandbox.grub.is_symlink()
    assert target.read_text() == expected, result.stderr
    assert target.stat().st_mode & 0o777 == 0o640
    assert target.stat().st_ino != inode
    assert [p.name for p in target.parent.iterdir()] == ["grub"]


@pytest.mark.parametrize("timeout", ["", "abc", "1;reboot", "1/", "-1", "1 2"])
def test_fast_grub_run_rejects_invalid_timeout(sandbox, timeout):
    original = "GRUB_TIMEOUT=5\n"
    sandbox.write(original)
    result = sandbox.run("system/fastGrubRun.sh", timeout)
    assert result.returncode == 2
    assert sandbox.read() == original
    assert sandbox.grub_calls() == []


@pytest.mark.parametrize(
    "script", ["system/fastGrub.sh", *[script for script, _ in CMDLINE_TOGGLES]]
)
def test_failed_edit_keeps_file(sandbox, tmp_path, script):
    # An editor dying halfway (full disk) must not install its partial output.
    original = 'GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"\nGRUB_THEME=/x\n'
    sandbox.write(original)
    broken = tmp_path / "broken"
    broken.mkdir()
    awk = broken / "awk"
    awk.write_text("#!/bin/bash\necho GRUB_TIMEOUT=1\nexit 1\n")
    awk.chmod(0o755)
    result = sandbox.toggle(script, "true", PATH=f"{broken}:{sandbox.env['PATH']}")
    assert result.returncode != 0
    assert sandbox.read() == original
    assert sandbox.grub_calls() == []


def test_grub_edits_wait_for_lock(sandbox):
    sandbox.write("GRUB_TIMEOUT=5\n")
    with open(sandbox.grub.with_name("grub.lock"), "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        proc = subprocess.Popen(
            ["bash", str(SCRIPTS / "system/fastGrubRun.sh"), "1"],
            env=sandbox.env,
            stdin=subprocess.DEVNULL,
        )
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(timeout=1)
        assert sandbox.read() == "GRUB_TIMEOUT=5\n"
    assert proc.wait(timeout=10) == 0
    assert sandbox.read() == "GRUB_TIMEOUT=1\n"


def test_fast_grub_failed_regeneration_restores_file(sandbox):
    original = "GRUB_TIMEOUT=5\n"
    sandbox.write(original)
    result = sandbox.toggle("system/fastGrub.sh", "true", FAKE_GRUB_RC=1)
    assert result.returncode != 0
    assert sandbox.read() == original


def test_fast_grub_invalid_state_exits_2(sandbox):
    sandbox.write("GRUB_TIMEOUT=5\n")
    assert sandbox.toggle("system/fastGrub.sh", "maybe").returncode == 2
    assert sandbox.grub_calls() == []


def test_grub_update_falls_back_to_mkconfig():
    content = (SCRIPTS / "grub-default.sh").read_text(encoding="utf-8")
    assert "grub-mkconfig -o /boot/grub/grub.cfg" in content
