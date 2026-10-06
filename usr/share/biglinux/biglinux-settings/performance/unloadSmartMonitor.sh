#!/bin/bash

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# check current status
if [ "$1" == "check" ]; then
  # Check if it's a VM; if so, disable it. Smart only works on a physical machine.
  if [[ "$(systemd-detect-virt)" != "none" ]];then
    echo "unsupported"
  elif systemctl is-active smartd --quiet;then
    echo "false"
  else
    echo "true"
  fi

# change the state
elif [ "$1" == "toggle" ]; then
  state="$2"
  # "true" = unload the monitor (stop smartd); "false" = keep disks monitored.
  # Monitoring installs smartmontools first when smartd.service is missing.
  case "$state" in
    true) action="unload" ;;
    false) action="monitor" ;;
    *) exit 2 ;;
  esac
  if [[ "$action" == "unload" ]] && ! systemctl list-unit-files smartd.service --no-legend 2>/dev/null | grep -q '^smartd\.service'; then
    # smartd is not installed: it is already not running
    exit 0
  fi
  pkexec /usr/share/biglinux/biglinux-settings/performance/unloadSmartMonitorRun.sh "$action"
  exit $?
fi
