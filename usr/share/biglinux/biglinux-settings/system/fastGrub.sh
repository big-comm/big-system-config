#!/bin/bash

# BIGLINUX_GRUB_FILE exists only for the test suite (read-only here).
grub_file="${BIGLINUX_GRUB_FILE:-/etc/default/grub}"

# check current status
if [ "$1" == "check" ]; then
  # Last active GRUB_TIMEOUT= line, accepting 1, "1" and '1'
  timeout="$(grep -E '^[[:space:]]*GRUB_TIMEOUT=' "$grub_file" 2>/dev/null | tail -n 1)"
  timeout="${timeout#*=}"
  timeout="${timeout//[\"\'[:space:]]/}"
  if [[ "$timeout" == "1" ]];then
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
