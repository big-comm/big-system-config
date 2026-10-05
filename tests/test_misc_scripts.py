"""Behavioral tests for the AI, developer, Docker, Wi-Fi and CPU profile scripts.

The scripts run for real inside a sandbox: every external tool they call
(pacman, systemctl, nmcli, powerprofilesctl, docker, npm, git, ...) is a small
fake on PATH that logs its calls and keeps state in files, and HOME is a
temporary directory. PATH does not include the system directories; only a
handful of coreutils are linked in, so a tool can be made "missing" by simply
not creating its fake.
"""

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "usr/share/biglinux/biglinux-settings"

CORE_TOOLS = [
    "bash", "cat", "mkdir", "rm", "rmdir", "mv", "cp", "ls", "chmod", "install",
    "mktemp", "grep", "sed", "tr", "cut", "dirname", "basename", "head", "tail",
    "env", "id", "touch", "sleep", "readlink", "python3",
]

FAKES = {
    "_log": """
        printf '%s %s\\n' "$(basename "$0")" "$*" >> "$FAKE_STATE/calls.log"
    """,
    # Package database: one "name reason" line per installed package. Installing
    # a GPU variant pulls "ollama" in as a dependency, like the Arch packages.
    "pacman": """
        . "$FAKE_BIN/_log"
        db="$FAKE_STATE/pkgs"
        touch "$db"
        op="$1"; shift
        targets=()
        for a in "$@"; do [[ "$a" == -* ]] || targets+=("$a"); done
        has() { grep -q "^$1 " "$db"; }
        case "$op" in
          -Q)
            for t in "${targets[@]}"; do has "$t" || exit 1; done
            exit 0 ;;
          -S*)
            [ -n "$FAKE_PACMAN_FAIL" ] && exit 1
            for t in "${targets[@]}"; do
              has "$t" || echo "$t explicit" >> "$db"
              if [[ "$t" == ollama-* ]] && ! has ollama; then echo "ollama dep" >> "$db"; fi
            done
            exit 0 ;;
          -R*)
            [ -n "$FAKE_PACMAN_REMOVE_FAIL" ] && exit 1
            for t in "${targets[@]}"; do
              has "$t" || exit 1
              grep -v "^$t " "$db" > "$db.tmp"; mv "$db.tmp" "$db"
              # -c: cascade to the packages that depend on ollama
              if [[ "$t" == ollama && "$op" == *c* ]]; then
                grep -v "^ollama-" "$db" > "$db.tmp"; mv "$db.tmp" "$db"
              fi
            done
            # -s: drop ollama if it was a dependency nobody needs anymore
            if [[ "$op" == *s* ]] && grep -q "^ollama dep" "$db" && ! grep -q "^ollama-" "$db"; then
              grep -v "^ollama " "$db" > "$db.tmp"; mv "$db.tmp" "$db"
            fi
            exit 0 ;;
        esac
        exit 1
    """,
    # ollama.service exists while the "ollama" package is installed.
    "systemctl": """
        . "$FAKE_BIN/_log"
        unit_exists() { grep -q "^ollama " "$FAKE_STATE/pkgs" 2>/dev/null; }
        case "$1" in
          daemon-reload) exit 0 ;;
          cat) unit_exists ;;
          enable)
            [ -n "$FAKE_SYSTEMCTL_FAIL" ] && exit 1
            unit_exists || exit 5
            touch "$FAKE_STATE/ollama.enabled" ;;
          disable)
            unit_exists || exit 5
            rm -f "$FAKE_STATE/ollama.enabled" ;;
          try-restart) unit_exists || exit 5 ;;
          restart|start) unit_exists || exit 5 ;;
        esac
    """,
    "pkexec": """
        . "$FAKE_BIN/_log"
        exit 0
    """,
    "npm": """
        . "$FAKE_BIN/_log"
        exit 0
    """,
    "nmcli": """
        . "$FAKE_BIN/_log"
        [ -n "$FAKE_NMCLI_FAIL" ] && exit 8
        echo "${FAKE_NMCLI_RADIO:-enabled}"
    """,
    "powerprofilesctl": """
        . "$FAKE_BIN/_log"
        store="$FAKE_STATE/power-profile"
        [ -f "$store" ] || echo balanced > "$store"
        case "$1" in
          get) cat "$store" ;;
          set) echo "$2" > "$store" ;;
          *) exit 1 ;;
        esac
    """,
    "docker": """
        . "$FAKE_BIN/_log"
        [ "$1 $2" = "compose ls" ] && cat "$FAKE_STATE/compose-ls" 2>/dev/null
        exit 0
    """,
    # --- ComfyUI install -----------------------------------------------------
    "curl": """
        while [ $# -gt 0 ]; do
          [ "$1" = --output ] && { echo '{"tag_name": "v0.3.0"}' > "$2"; exit 0; }
          shift
        done
        exit 1
    """,
    "git": """
        if [ "$1" = clone ]; then
          dest="${@: -1}"
          mkdir -p "$dest"; touch "$dest/main.py" "$dest/requirements.txt"
        elif [ "$1" = -C ]; then
          echo 0123456789abcdef
        fi
    """,
    "lspci": """
        echo "01:00.0 VGA compatible controller: NVIDIA Corporation"
    """,
    # Like the real venv/pip: pip and every script it installs get a shebang
    # with the absolute path of the venv's python at creation/install time.
    "python": """
        [ "$1 $2" = "-m venv" ] || exit 1
        venv="$3"
        mkdir -p "$venv/bin"
        printf '#!/bin/bash\\nexit 0\\n' > "$venv/bin/python"
        {
          echo '#!/bin/bash'
          echo "# real shebang: #!$venv/bin/python"
          echo '[ -n "$FAKE_PIP_FAIL" ] && exit 1'
          echo 'd="$(cd "$(dirname "$0")" && pwd)"'
          echo 'printf "#!%s/python\\n" "$d" > "$d/torchrun"'
        } > "$venv/bin/pip"
        chmod +x "$venv/bin/python" "$venv/bin/pip"
    """,
}


@pytest.fixture
def sandbox(tmp_path):
    fake_bin = tmp_path / "bin"
    core_bin = tmp_path / "core"
    state = tmp_path / "state"
    home = tmp_path / "home dir [x].y"  # space and regex characters on purpose
    for directory in (fake_bin, core_bin, state, home):
        directory.mkdir()

    for tool in CORE_TOOLS:
        path = shutil.which(tool)
        if path:
            (core_bin / tool).symlink_to(path)
    for name, body in FAKES.items():
        fake = fake_bin / name
        fake.write_text("#!/bin/bash\n" + textwrap.dedent(body))
        fake.chmod(0o755)

    class Sandbox:
        def __init__(self):
            self.home = home
            self.state = state
            self.fake_bin = fake_bin
            self.env = {
                "PATH": f"{fake_bin}:{core_bin}",
                "HOME": str(home),
                "USER": "tester",
                "LANG": "C.UTF-8",
                "FAKE_BIN": str(fake_bin),
                "FAKE_STATE": str(state),
                "XDG_STATE_HOME": str(home / ".local/state"),
            }

        def remove_tool(self, name):
            (fake_bin / name).unlink()

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

        def calls(self, tool=None):
            log = state / "calls.log"
            lines = log.read_text().splitlines() if log.exists() else []
            if tool:
                lines = [c for c in lines if c.split(" ", 1)[0] == tool]
            return lines

        def installed(self):
            db = state / "pkgs"
            return {line.split()[0] for line in db.read_text().splitlines()} if db.exists() else set()

        def install(self, *packages):
            with (state / "pkgs").open("a") as db:
                for package in packages:
                    db.write(f"{package} explicit\n")

        def service_enabled(self):
            return (state / "ollama.enabled").exists()

    return Sandbox()


# --- Ollama variants -------------------------------------------------------------

OLLAMA_VARIANTS = [
    ("ai/ollamaCpu", "ollama"),
    ("ai/ollamaAmd", "ollama-rocm"),
    ("ai/ollamaNvidia", "ollama-cuda"),
    ("ai/ollamaVulkan", "ollama-vulkan"),
]


@pytest.mark.parametrize("script, package", OLLAMA_VARIANTS)
def test_ollama_install_round_trip(sandbox, script, package):
    result = sandbox.run(f"{script}Run.sh", "install")
    assert result.returncode == 0, result.stderr
    assert package in sandbox.installed()
    assert sandbox.service_enabled()
    assert any("--needed" in c for c in sandbox.calls("pacman") if c.startswith("pacman -S"))
    assert sandbox.check(f"{script}.sh") == "true"

    result = sandbox.run(f"{script}Run.sh", "uninstall")
    assert result.returncode == 0, result.stderr
    assert sandbox.installed() == set()
    assert sandbox.check(f"{script}.sh") == "false"


@pytest.mark.parametrize("script, package", OLLAMA_VARIANTS)
def test_ollama_failed_pacman_is_not_masked_by_systemctl(sandbox, script, package):
    result = sandbox.run(f"{script}Run.sh", "install", FAKE_PACMAN_FAIL=1)
    assert result.returncode != 0
    assert not any(c.startswith("systemctl enable") for c in sandbox.calls())


@pytest.mark.parametrize("script, package", OLLAMA_VARIANTS)
def test_ollama_failed_service_start_fails_install(sandbox, script, package):
    result = sandbox.run(f"{script}Run.sh", "install", FAKE_SYSTEMCTL_FAIL=1)
    assert result.returncode != 0


@pytest.mark.parametrize("script, package", OLLAMA_VARIANTS)
def test_ollama_failed_removal_fails_and_keeps_service(sandbox, script, package):
    assert sandbox.run(f"{script}Run.sh", "install").returncode == 0
    result = sandbox.run(f"{script}Run.sh", "uninstall", FAKE_PACMAN_REMOVE_FAIL=1)
    assert result.returncode != 0
    assert package in sandbox.installed()
    assert sandbox.service_enabled()


def test_ollama_removing_one_backend_keeps_service_for_the_other(sandbox):
    assert sandbox.run("ai/ollamaVulkanRun.sh", "install").returncode == 0
    assert sandbox.run("ai/ollamaNvidiaRun.sh", "install").returncode == 0
    result = sandbox.run("ai/ollamaNvidiaRun.sh", "uninstall")
    assert result.returncode == 0, result.stderr
    assert sandbox.installed() == {"ollama", "ollama-vulkan"}
    assert sandbox.service_enabled()
    assert sandbox.check("ai/ollamaVulkan.sh") == "true"


@pytest.mark.parametrize("script", ["ai/chatboxRun.sh", "ai/lmStudioRun.sh", "ai/ollamaLabRun.sh"])
def test_package_installs_use_needed(sandbox, script):
    assert sandbox.run(script, "install").returncode == 0
    installs = [c for c in sandbox.calls("pacman") if c.startswith("pacman -S")]
    assert installs and all("--needed" in c for c in installs)


# --- Ollama network sharing ----------------------------------------------------------


@pytest.fixture
def dropin(sandbox, tmp_path):
    directory = tmp_path / "etc/ollama.service.d"
    sandbox.env["BIGLINUX_SETTINGS_OLLAMA_DROPIN_DIR"] = str(directory)
    return directory / "90-biglinux-network.conf"


def test_ollama_share_refuses_without_ollama_and_writes_nothing(sandbox, dropin):
    result = sandbox.run("ai/ollamaShareRun.sh", "install")
    assert result.returncode != 0
    assert not dropin.exists()
    assert not dropin.parent.exists()


def test_ollama_share_does_not_start_a_stopped_service(sandbox, dropin):
    sandbox.install("ollama")
    result = sandbox.run("ai/ollamaShareRun.sh", "install")
    assert result.returncode == 0, result.stderr
    assert 'Environment="OLLAMA_HOST=0.0.0.0"' in dropin.read_text()
    systemctl = sandbox.calls("systemctl")
    assert "systemctl daemon-reload" in systemctl
    assert "systemctl try-restart ollama.service" in systemctl
    assert not any(c.split()[1] in ("restart", "start") for c in systemctl)

    result = sandbox.run("ai/ollamaShareRun.sh", "uninstall")
    assert result.returncode == 0, result.stderr
    assert not dropin.exists()


def test_ollama_share_uninstall_works_after_ollama_was_removed(sandbox, dropin):
    dropin.parent.mkdir(parents=True)
    dropin.write_text("[Service]\n")
    result = sandbox.run("ai/ollamaShareRun.sh", "uninstall")
    assert result.returncode == 0, result.stderr
    assert not dropin.exists()


# --- ComfyUI install ---------------------------------------------------------------


def test_comfyui_venv_scripts_point_to_the_final_location(sandbox):
    result = sandbox.run("ai/comfyUIInstall.sh", "install")
    assert result.returncode == 0, result.stderr
    install_dir = sandbox.home / "ComfyUI"
    assert (install_dir / ".biglinux-settings-managed").is_file()
    assert (install_dir / "main.py").is_file()
    # No leftover staging directory in HOME
    assert sorted(p.name for p in sandbox.home.iterdir()) == ["ComfyUI"]

    for script in ("pip", "torchrun"):
        content = (install_dir / "bin" / script).read_text()
        assert ".ComfyUI-install" not in content, f"bin/{script} points to the temp dir"
    shebang = (install_dir / "bin/torchrun").read_text().splitlines()[0]
    assert Path(shebang[2:]).exists()
    assert sandbox.check("ai/comfyUI.sh") == "true"


def test_comfyui_failed_install_leaves_nothing_behind(sandbox):
    result = sandbox.run("ai/comfyUIInstall.sh", "install", FAKE_PIP_FAIL=1)
    assert result.returncode != 0
    assert list(sandbox.home.iterdir()) == []


def test_comfyui_install_refuses_existing_directory(sandbox):
    user_dir = sandbox.home / "ComfyUI"
    user_dir.mkdir()
    (user_dir / "mine.txt").write_text("keep")
    result = sandbox.run("ai/comfyUIInstall.sh", "install")
    assert result.returncode != 0
    assert (user_dir / "mine.txt").read_text() == "keep"


# --- OpenClaude -----------------------------------------------------------------------


def test_openclaude_installs_without_lifecycle_scripts(sandbox):
    result = sandbox.run("developer/openclaudeRun.sh", "install")
    assert result.returncode == 0, result.stderr
    installs = [c for c in sandbox.calls("npm") if c.startswith("npm install")]
    assert installs == ["npm install -g --ignore-scripts @gitlawb/openclaude"]


def test_openclaude_stops_when_dependencies_fail(sandbox):
    result = sandbox.run("developer/openclaudeRun.sh", "install", FAKE_PACMAN_FAIL=1)
    assert result.returncode != 0
    assert sandbox.calls("npm") == []


# --- Docker compose apps -----------------------------------------------------------------

COMPOSE_APPS = {
    "docker/adguardRun.sh": "Docker/Adguard/docker-compose.yml",
    "docker/jellyfinRun.sh": "Docker/Jellyfin/docker-compose.yml",
    "docker/lampRun.sh": "Docker/LAMP/docker-compose.yml",
    "docker/nextcloud-plusRun.sh": "Docker/Nextcloud-Plus/nextcloud.yml",
    "docker/openNotebookRun.sh": "Docker/open-notebook/docker-compose.yml",
    "docker/portainer-clientRun.sh": "Docker/Portainer/docker-compose.yml",
    "docker/swsRun.sh": "Docker/SWS/docker-compose.yml",
    "docker/v2rayaRun.sh": "Docker/V2rayA/docker-compose.yml",
    "ai/openNotebookRun.sh": "Docker/open-notebook/docker-compose.yml",
}


def compose_ls(*rows):
    lines = ["NAME                STATUS              CONFIG FILES"]
    lines += [f"app{i}                {status}          {path}" for i, (status, path) in enumerate(rows)]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("script, compose", sorted(COMPOSE_APPS.items()))
def test_docker_check_matches_compose_file_literally(sandbox, script, compose):
    ours = f"{sandbox.home}/{compose}"
    ls_file = sandbox.state / "compose-ls"

    ls_file.write_text(compose_ls(("running(2)", ours)))
    assert sandbox.check(script) == "true"

    ls_file.write_text(compose_ls(("exited(1)", ours)))
    assert sandbox.check(script) == "false"

    # Another project running from a path that only matches as a regex
    lookalike = ours.replace("[x]", "x").replace(".y", "zy")
    ls_file.write_text(compose_ls(("running(1)", lookalike), ("exited(1)", ours)))
    assert sandbox.check(script) == "false"


# --- Wi-Fi ----------------------------------------------------------------------------------


@pytest.mark.parametrize("radio, expected", [("enabled", "true"), ("disabled", "false")])
def test_wifi_check_queries_nmcli_once(sandbox, radio, expected):
    assert sandbox.check("devices/wifi.sh", FAKE_NMCLI_RADIO=radio) == expected
    assert len(sandbox.calls("nmcli")) == 1


@pytest.mark.parametrize("env", [{"FAKE_NMCLI_FAIL": 1}, {"FAKE_NMCLI_RADIO": "garbage"}])
def test_wifi_check_unsupported_when_nmcli_fails(sandbox, env):
    assert sandbox.check("devices/wifi.sh", **env) == "unsupported"


def test_wifi_check_unsupported_without_nmcli(sandbox):
    sandbox.remove_tool("nmcli")
    assert sandbox.check("devices/wifi.sh") == "unsupported"
    assert sandbox.run("devices/wifi.sh", "toggle", "true").returncode != 0


# --- CPU maximum performance ------------------------------------------------------------------

CPU = "performance/cpuMaximumPerformance.sh"


def test_cpu_performance_unsupported_without_powerprofilesctl(sandbox):
    sandbox.remove_tool("powerprofilesctl")
    assert sandbox.check(CPU) == "unsupported"
    assert sandbox.run(CPU, "toggle", "true").returncode != 0


@pytest.mark.parametrize("previous", ["power-saver", "balanced"])
def test_cpu_performance_restores_previous_profile(sandbox, previous):
    (sandbox.state / "power-profile").write_text(previous + "\n")
    assert sandbox.check(CPU) == "false"

    assert sandbox.run(CPU, "toggle", "true").returncode == 0
    assert sandbox.check(CPU) == "true"
    # Enabling twice must not overwrite the saved profile with "performance"
    assert sandbox.run(CPU, "toggle", "true").returncode == 0

    assert sandbox.run(CPU, "toggle", "false").returncode == 0
    assert (sandbox.state / "power-profile").read_text().strip() == previous
    assert sandbox.check(CPU) == "false"


def test_cpu_performance_disable_without_saved_profile_uses_balanced(sandbox):
    (sandbox.state / "power-profile").write_text("performance\n")
    assert sandbox.run(CPU, "toggle", "false").returncode == 0
    assert (sandbox.state / "power-profile").read_text().strip() == "balanced"
