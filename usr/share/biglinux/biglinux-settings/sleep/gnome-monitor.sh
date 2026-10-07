#!/bin/bash
set -euo pipefail
# gnome-monitor.sh — Toggle GNOME extension health monitor.
# Enables the systemd user service for the GNOME session.

SERVICE_NAME="biglinux-sleep-monitor"

_require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        exec pkexec "$(readlink -f "$0")" "$@"
    fi
}

if [ "${1:-}" == "check" ]; then
    if systemctl --user is-enabled --quiet "${SERVICE_NAME}.service" 2>/dev/null; then
        echo "true"
    else
        echo "false"
    fi

elif [ "${1:-}" == "toggle" ]; then
    _require_root "$@"
    state="${2:-}"
    [[ "$state" == "true" || "$state" == "false" ]] || exit 2

    invokingUid="${PKEXEC_UID:-}"
    if [[ ! "$invokingUid" =~ ^[0-9]+$ ]]; then
        echo "Cannot determine the invoking user" >&2
        exit 1
    fi
    invokingUser="$(id -nu "$invokingUid")"

    if [ "$state" == "true" ]; then
        systemctl --global enable "${SERVICE_NAME}.service"
        # Best effort: the global enable above is what persists.
        systemctl --user --machine="${invokingUser}@.host" start "${SERVICE_NAME}.service" ||
            echo "Warning: could not start ${SERVICE_NAME} for ${invokingUser} now; it applies at next login" >&2
    else
        systemctl --global disable "${SERVICE_NAME}.service"
        # Best effort: the global disable above is what persists.
        systemctl --user --machine="${invokingUser}@.host" stop "${SERVICE_NAME}.service" ||
            echo "Warning: could not stop ${SERVICE_NAME} for ${invokingUser} now; it applies at next login" >&2
    fi
else
    exit 2
fi
