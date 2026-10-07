"""Keyboard light (Scroll Lock LED) toggle, run against a fake sysfs tree."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "usr/share/biglinux/biglinux-settings"
INSTALLED = "/usr/share/biglinux/biglinux-settings"
RULE = "99-biglinux-keyboard-led.rules"


@pytest.fixture
def led_env(tmp_path):
    leds = tmp_path / "leds"
    for name, trigger in [
        ("input2::scrolllock", "kbd-scrolllock"),
        ("input7::scrolllock", "kbd-scrolllock"),
        ("input2::capslock", "kbd-capslock"),
    ]:
        led = leds / name
        led.mkdir(parents=True)
        (led / "trigger").write_text(trigger + "\n")
        (led / "brightness").write_text("0\n")
        (led / "max_brightness").write_text("1\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pkexec = fake_bin / "pkexec"
    # Run the repository copy of the root helper instead of the installed one
    pkexec.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$*" >> "$FAKE_LOG"\n'
        f'prefix="{INSTALLED}"; script="{SCRIPTS}${{1#"$prefix"}}"; shift\n'
        'exec "$script" "$@"\n'
    )
    pkexec.chmod(0o755)

    class Env:
        rules = tmp_path / "rules.d"
        log = tmp_path / "pkexec.log"
        env = {
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "BIGLINUX_LEDS_DIR": str(leds),
            "BIGLINUX_UDEV_RULES_DIR": str(tmp_path / "rules.d"),
            "FAKE_LOG": str(tmp_path / "pkexec.log"),
        }

        @staticmethod
        def led(name, attr):
            return (leds / name / attr).read_text().strip()

        def run(self, script, *args):
            return subprocess.run(
                [str(SCRIPTS / script), *args],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )

        def check(self):
            result = self.run("usability/keyboardLed.sh", "check")
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

    return Env()


def test_enable_lights_every_keyboard_and_installs_rule(led_env):
    assert led_env.check() == "false"
    result = led_env.run("usability/keyboardLed.sh", "toggle", "true")
    assert result.returncode == 0, result.stderr

    for name in ("input2::scrolllock", "input7::scrolllock"):
        assert led_env.led(name, "trigger") == "none"
        assert led_env.led(name, "brightness") == "1"
    rule = (led_env.rules / RULE).read_text()
    assert 'KERNEL=="*::scrolllock"' in rule
    assert 'ATTR{trigger}="none"' in rule
    assert rule.index("ATTR{trigger}") < rule.index("ATTR{brightness}")
    assert oct((led_env.rules / RULE).stat().st_mode & 0o777) == "0o644"
    assert led_env.check() == "true"


def test_other_leds_are_left_alone(led_env):
    led_env.run("usability/keyboardLed.sh", "toggle", "true")
    assert led_env.led("input2::capslock", "trigger") == "kbd-capslock"
    assert led_env.led("input2::capslock", "brightness") == "0"


def test_disable_hands_led_back_to_scroll_lock_key(led_env):
    led_env.run("usability/keyboardLed.sh", "toggle", "true")
    result = led_env.run("usability/keyboardLed.sh", "toggle", "false")
    assert result.returncode == 0, result.stderr

    assert not (led_env.rules / RULE).exists()
    for name in ("input2::scrolllock", "input7::scrolllock"):
        assert led_env.led(name, "trigger") == "kbd-scrolllock"
    assert led_env.check() == "false"


def test_toggle_is_idempotent(led_env):
    for state in ("true", "true", "false", "false", "true"):
        assert led_env.run("usability/keyboardLed.sh", "toggle", state).returncode == 0
        assert led_env.check() == state
    assert [p.name for p in led_env.rules.iterdir()] == [RULE]  # no temp files left


def test_without_scrolllock_led_it_is_unsupported(led_env, tmp_path):
    empty = tmp_path / "no-leds"
    empty.mkdir()
    led_env.env["BIGLINUX_LEDS_DIR"] = str(empty)
    assert led_env.check() == "unsupported"
    assert led_env.run("usability/keyboardLed.sh", "toggle", "true").returncode != 0
    assert not led_env.log.exists()  # never asked for the password


def test_invalid_arguments(led_env):
    assert led_env.run("usability/keyboardLed.sh", "toggle", "maybe").returncode == 2
    assert led_env.run("usability/keyboardLedRun.sh", "on").returncode == 2
    assert led_env.run("usability/keyboardLedRun.sh").returncode == 2
    assert not led_env.log.exists()


def test_cancelled_password_prompt_fails(led_env, tmp_path):
    (tmp_path / "bin/pkexec").write_text("#!/bin/bash\nexit 126\n")
    result = led_env.run("usability/keyboardLed.sh", "toggle", "true")
    assert result.returncode == 126
    assert led_env.check() == "false"


def test_failed_led_write_is_reported(led_env, tmp_path):
    trigger = tmp_path / "leds/input7::scrolllock/trigger"
    trigger.chmod(0o444)
    try:
        result = led_env.run("usability/keyboardLedRun.sh", "enable")
        assert result.returncode != 0
        # The other keyboard is still handled
        assert led_env.led("input2::scrolllock", "trigger") == "none"
    finally:
        trigger.chmod(0o644)


@pytest.mark.skipif(
    subprocess.run(["sh", "-c", "udevadm verify --help"], capture_output=True).returncode != 0,
    reason="udevadm verify unavailable",
)
def test_udev_rule_syntax(led_env):
    led_env.run("usability/keyboardLed.sh", "toggle", "true")
    result = subprocess.run(
        ["udevadm", "verify", str(led_env.rules / RULE)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
