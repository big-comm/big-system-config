#!/bin/bash

# BIGLINUX_GRUB_FILE exists only for the test suite (read-only here).
grub_file="${BIGLINUX_GRUB_FILE:-/etc/default/grub}"

# Print the value of the last active KEY= line, ignoring commented lines and
# accepting double, single or no quotes.
grub_value() {
  local line value
  line="$(grep -E "^[[:space:]]*$1=" "$grub_file" 2>/dev/null | tail -n 1)"
  [[ -n "$line" ]] || return 1
  value="${line#*=}"
  case "$value" in
    \"*) value="${value#\"}"; value="${value%%\"*}" ;;
    \'*) value="${value#\'}"; value="${value%%\'*}" ;;
    *) value="${value%%[[:space:]]*}" ;;
  esac
  printf '%s\n' "$value"
}

# check current status
if [ "$1" == "check" ]; then
  cmdline=" $(grub_value GRUB_CMDLINE_LINUX) $(grub_value GRUB_CMDLINE_LINUX_DEFAULT) "
  cmdline="${cmdline//[[:space:]]/ }"
  if [[ "$cmdline" == *" nowatchdog "* ]] && [[ "$cmdline" == *" tsc=nowatchdog "* ]];then
    echo "true"
  else
    echo "false"
  fi

# change the state
elif [ "$1" == "toggle" ]; then
  state="$2"
  if [ "$state" == "true" ]; then
    pkexec /usr/share/biglinux/biglinux-settings/performance/noWatchdogRun.sh "enable" "$USER" "$DISPLAY" "$XAUTHORITY" "$DBUS_SESSION_BUS_ADDRESS" "$LANG" "$LANGUAGE"
    exitCode=$?
  elif [ "$state" == "false" ]; then
    pkexec /usr/share/biglinux/biglinux-settings/performance/noWatchdogRun.sh "disable" "$USER" "$DISPLAY" "$XAUTHORITY" "$DBUS_SESSION_BUS_ADDRESS" "$LANG" "$LANGUAGE"
    exitCode=$?
  else
    exitCode=2
  fi
  exit $exitCode
fi
