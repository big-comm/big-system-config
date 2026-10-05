#!/bin/bash
set -euo pipefail

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# check current status
if [ "${1:-}" == "check" ]; then
  if grep -Fxq 'Environment="OLLAMA_HOST=0.0.0.0"' /etc/systemd/system/ollama.service.d/90-biglinux-network.conf 2>/dev/null; then
    echo "true"
  else
    echo "false"
  fi

# change the state
elif [ "${1:-}" == "toggle" ]; then
  state="${2:-}"
  [[ "$state" == "true" || "$state" == "false" ]] || exit 2
  if [ "$state" == "true" ]; then
    pkexec /usr/share/biglinux/biglinux-settings/ai/ollamaShareRun.sh "install" "$USER" "${DISPLAY:-}" "${XAUTHORITY:-}" "${DBUS_SESSION_BUS_ADDRESS:-}" "${LANG:-}" "${LANGUAGE:-}"
    exitCode=$?
  else
    pkexec /usr/share/biglinux/biglinux-settings/ai/ollamaShareRun.sh "uninstall" "$USER" "${DISPLAY:-}" "${XAUTHORITY:-}" "${DBUS_SESSION_BUS_ADDRESS:-}" "${LANG:-}" "${LANGUAGE:-}"
    exitCode=$?
  fi
  exit "$exitCode"
else
  exit 2
fi
