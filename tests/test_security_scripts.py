"""Regression tests for high-risk script behavior."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "usr/share/biglinux/biglinux-settings"


def script(relative_path: str) -> str:
    return (SCRIPTS / relative_path).read_text(encoding="utf-8")


def test_docker_socket_is_not_world_writable():
    content = script("docker/dockerEnableRun.sh")
    assert "chmod 666" not in content
    assert "docker.socket" in content


def test_krita_uninstall_only_removes_plugin_owned_paths():
    content = script("ai/krita.sh")
    assert 'rm -rf "$HOME/.local/share/krita/pykrita"' not in content
    assert ".bashrc" not in content
    assert "pykrita/ai_diffusion" in content


def test_grub_generation_has_explicit_output():
    assert "grub-mkconfig -o /boot/grub/grub.cfg" in script("grub-default.sh")
    for name in ["noWatchdogRun.sh", "meltdownMitigationsRun.sh"]:
        assert "/../grub-default.sh" in script(f"performance/{name}")


def test_comfyui_requires_management_marker_before_removal():
    content = script("ai/comfyUIInstall.sh")
    marker_check = content.index('[[ ! -f "$markerFile" ]]')
    removal = content.index('rm -rf -- "$installDir"')
    assert marker_check < removal


def test_upower_policy_suspends_at_exactly_twenty_percent():
    content = script("sleep/suspend-at-20Run.sh")
    assert "PercentageLow=25" in content
    assert "PercentageCritical=22" in content
    assert "PercentageAction=20" in content
    assert "CriticalPowerAction=Suspend" in content


def test_search_results_do_not_reparent_live_setting_rows():
    content = (SCRIPTS / "main.py").read_text(encoding="utf-8")
    assert "original_parent.remove(row)" not in content
    assert "self._add_search_result" in content
