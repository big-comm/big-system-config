#!/bin/bash
# Root helper for the "Disk health monitoring" switch (runs through pkexec).
#   monitor   install smartmontools if smartd is missing, then enable smartd
#   unload    stop and disable smartd
set -u

action="${1:-}"

smartd_unit_exists() {
  systemctl list-unit-files smartd.service --no-legend 2>/dev/null | grep -q '^smartd\.service'
}

case "$action" in
  monitor)
    if ! smartd_unit_exists; then
      pacman -S --needed --noconfirm smartmontools || exit $?
      systemctl daemon-reload
      smartd_unit_exists || exit 1
    fi
    systemctl enable --now smartd.service
    ;;
  unload)
    # Nothing installed means nothing to stop
    smartd_unit_exists || exit 0
    systemctl disable --now smartd.service
    ;;
  *)
    echo "Usage: $0 monitor|unload" >&2
    exit 2
    ;;
esac
