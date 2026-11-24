#!/bin/bash

# shellcheck source=../grub-default.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../grub-default.sh"

# check current status
if [ "$1" == "check" ]; then
  if [[ "$(grub_value GRUB_TIMEOUT)" == "1" ]]; then
    echo "true"
  else
    echo "false"
  fi

# change the state
elif [ "$1" == "toggle" ]; then
  state="$2"
  if [ "$state" == "true" ]; then
    pkexec /usr/share/biglinux/biglinux-settings/system/fastGrubRun.sh "1" "$USER" "$DISPLAY" "$XAUTHORITY" "$DBUS_SESSION_BUS_ADDRESS" "$LANG" "$LANGUAGE"
    exitCode=$?
  elif [ "$state" == "false" ]; then
    pkexec /usr/share/biglinux/biglinux-settings/system/fastGrubRun.sh "5" "$USER" "$DISPLAY" "$XAUTHORITY" "$DBUS_SESSION_BUS_ADDRESS" "$LANG" "$LANGUAGE"
    exitCode=$?
  else
    exitCode=2
  fi
  exit $exitCode
fi
