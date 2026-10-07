#!/bin/bash
set -euo pipefail

installDir="$HOME/ComfyUI"
stateDir="${XDG_STATE_HOME:-$HOME/.local/state}/biglinux-settings"
pidFile="$stateDir/comfyui.pid"

running_pid() {
  [[ -r "$pidFile" ]] || return 1
  local pid
  pid="$(<"$pidFile")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  tr '\0' '\n' < "/proc/$pid/cmdline" 2>/dev/null | grep -Fxq "$installDir/main.py" || return 1
  printf '%s\n' "$pid"
}

case "${1:-}" in
  check)
    if running_pid >/dev/null; then
      echo "true"
    else
      echo "false"
    fi
    ;;
  toggle)
    state="${2:-}"
    if [[ "$state" == "true" ]]; then
      [[ -f "$installDir/.biglinux-settings-managed" && -x "$installDir/bin/python" ]] || exit 1
      if running_pid >/dev/null; then
        exit 0
      fi
      mkdir -p "$stateDir"
      "$installDir/bin/python" "$installDir/main.py" --listen 0.0.0.0 > "$installDir/start.log" 2>&1 &
      pid=$!
      printf '%s\n' "$pid" > "$pidFile"
      sleep 5
      kill -0 "$pid" 2>/dev/null
    elif [[ "$state" == "false" ]]; then
      if pid="$(running_pid)"; then
        kill "$pid"
        for _ in {1..20}; do
          kill -0 "$pid" 2>/dev/null || break
          sleep 0.1
        done
        kill -0 "$pid" 2>/dev/null && exit 1
      fi
      rm -f "$pidFile"
    else
      exit 2
    fi
    ;;
  *)
    exit 2
    ;;
esac
