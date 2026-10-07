#!/bin/bash

# Profile that was active before "maximum performance" was enabled, so that
# disabling it goes back to it instead of always forcing "balanced".
stateDir="${XDG_STATE_HOME:-$HOME/.local/state}/biglinux-settings"
savedProfile="$stateDir/cpuPreviousPowerProfile"

# check current status
if [ "$1" == "check" ]; then
  if ! command -v powerprofilesctl &>/dev/null || ! current="$(powerprofilesctl get 2>/dev/null)"; then
    echo "unsupported"
  elif [[ "$current" == "performance" ]]; then
    echo "true"
  else
    echo "false"
  fi

# change the state
elif [ "$1" == "toggle" ]; then
  state="$2"
  command -v powerprofilesctl &>/dev/null || exit 1
  if [ "$state" == "true" ]; then
    current="$(powerprofilesctl get 2>/dev/null)"
    if [[ -n "$current" && "$current" != "performance" ]]; then
      mkdir -p "$stateDir" && printf '%s\n' "$current" > "$savedProfile"
    fi
    powerprofilesctl set performance
    exitCode=$?
  else
    previous="$(cat "$savedProfile" 2>/dev/null)"
    # Only accept known profiles; anything else falls back to balanced.
    case "$previous" in
      power-saver|balanced) ;;
      *) previous="balanced" ;;
    esac
    powerprofilesctl set "$previous"
    exitCode=$?
    [ "$exitCode" -eq 0 ] && rm -f "$savedProfile"
  fi
  exit $exitCode
fi
