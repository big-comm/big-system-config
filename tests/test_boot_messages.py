"""Boot messages switch (system/plymouthBootMessagesRun.sh).

Regression: with several kernels installed, messages kept showing at boot
although the switch was off. The splash runs from the initramfs, and each
kernel carries its own copy of the theme script; a preset that failed to
rebuild (or ran out of time) left a stale copy, and the script still
reported success because *another* image had been built.
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "usr/share/biglinux/biglinux-settings/system/plymouthBootMessagesRun.sh"

THEME = """# theme
Plymouth.SetDisplayNormalFunction(display_normal_callback);
Plymouth.SetDisplayMessageFunction (display_message_callback);
Plymouth.SetHideMessageFunction (hide_message_callback);
Plymouth.SetUpdateStatusFunction(display_message_callback);
"""

FAKES = {
    "plymouth-set-default-theme": "exit 0",
    # "Builds" the image: a snapshot of the theme script at build time.
    # FAIL lists presets that fail; STALE lists presets that keep an old copy.
    "mkinitcpio": """
        [ "$1" = "-p" ] || exit 2
        name="$2"
        echo "$name" >> "$STATE/built.log"
        case " $FAIL " in *" $name "*) exit 1 ;; esac
        image="$(. "$PRESETS/$name.preset"; printf '%s' "$default_image")"
        case " $STALE " in *" $name "*) exit 0 ;; esac
        cp "$THEME_SCRIPT" "$image"
    """,
    "lsinitcpio": """
        [ "$1" = "-x" ] || exit 2
        mkdir -p usr/share/plymouth/themes/community
        cp "$2" usr/share/plymouth/themes/community/animated-boot.script
    """,
}

pytestmark = pytest.mark.skipif(
    os.geteuid() == 0, reason="the test-only path overrides are ignored as root"
)


@pytest.fixture
def env(tmp_path):
    fake_bin = tmp_path / "bin"
    presets = tmp_path / "presets"
    boot = tmp_path / "boot"
    state = tmp_path / "state"
    for directory in (fake_bin, presets, boot, state):
        directory.mkdir()
    for name, body in FAKES.items():
        path = fake_bin / name
        path.write_text("#!/bin/bash\n" + textwrap.dedent(body))
        path.chmod(0o755)

    theme = tmp_path / "animated-boot.script"
    theme.write_text(THEME)
    for name in ("linux-big", "linux618", "linux72-comm"):
        kernel = boot / f"vmlinuz-{name}"
        kernel.write_text("kernel")
        image = boot / f"initramfs-{name}.img"
        image.write_text(THEME)  # built earlier, messages enabled
        (presets / f"{name}.preset").write_text(
            f'ALL_kver="{kernel}"\nPRESETS=(\'default\')\ndefault_image="{image}"\n'
        )

    class Env:
        def __init__(self):
            self.boot, self.theme, self.state = boot, theme, state
            self.vars = {
                "PATH": f"{fake_bin}:/usr/bin:/bin",
                "STATE": str(state),
                "PRESETS": str(presets),
                "THEME_SCRIPT": str(theme),
                "BIGLINUX_PLYMOUTH_CONFIG_DIR": str(tmp_path / "etc"),
                "BIGLINUX_PLYMOUTH_THEME_SCRIPT": str(theme),
                "BIGLINUX_MKINITCPIO_PRESETS": str(presets),
                "BIGLINUX_MKINITCPIO_CONF": str(tmp_path / "mkinitcpio.conf"),
                "FAIL": "",
                "STALE": "",
            }

        def run(self, state, **extra):
            return subprocess.run(
                [str(RUN), state],
                env={**self.vars, **extra},
                capture_output=True,
                text=True,
                timeout=60,
            )

        def image(self, name):
            return (boot / f"initramfs-{name}.img").read_text()

        def built(self):
            log = state / "built.log"
            return log.read_text().split() if log.exists() else []

    return Env()


def messages_enabled(text: str) -> bool:
    return any(
        line.startswith("Plymouth.SetUpdateStatusFunction") for line in text.splitlines()
    )


def test_disabling_updates_every_kernel_image(env):
    result = env.run("false")
    assert result.returncode == 0, result.stderr
    assert sorted(env.built()) == ["linux-big", "linux618", "linux72-comm"]
    for name in ("linux-big", "linux618", "linux72-comm"):
        assert not messages_enabled(env.image(name)), name
    assert not messages_enabled(env.theme.read_text())


def test_one_failing_kernel_is_reported_and_others_still_built(env):
    result = env.run("false", FAIL="linux72-comm")
    assert result.returncode != 0
    assert "linux72-comm" in result.stderr
    # it does not stop at the first failure: the other kernels are updated
    assert not messages_enabled(env.image("linux-big"))
    assert not messages_enabled(env.image("linux618"))


def test_image_left_with_the_old_theme_is_detected(env):
    result = env.run("false", STALE="linux618")
    assert result.returncode != 0
    assert "linux618" in result.stderr and "theme" in result.stderr


def test_removed_kernel_preset_is_skipped(env):
    (env.boot / "vmlinuz-linux618").unlink()
    result = env.run("false")
    assert result.returncode == 0, result.stderr
    assert "linux618" not in env.built()


def test_enabling_restores_messages_everywhere(env):
    assert env.run("false").returncode == 0
    result = env.run("true")
    assert result.returncode == 0, result.stderr
    assert messages_enabled(env.theme.read_text())
    for name in ("linux-big", "linux618", "linux72-comm"):
        assert messages_enabled(env.image(name)), name


def test_invalid_state(env):
    assert env.run("maybe").returncode != 0
    assert env.built() == []
