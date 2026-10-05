#!/bin/bash

# Keyboard light (Scroll Lock LED). Works on any desktop, X11 or Wayland:
# it only needs the kernel LED device, see keyboardLedRun.sh.

# Test-only overrides; this side runs as the user and only reads
ledsDir="${BIGLINUX_LEDS_DIR:-/sys/class/leds}"
ruleFile="${BIGLINUX_UDEV_RULES_DIR:-/etc/udev/rules.d}/99-biglinux-keyboard-led.rules"

has_scrolllock_led() {
  local led
  for led in "$ledsDir"/*::scrolllock; do
    [[ -e "$led" ]] && return 0
  done
  return 1
}

if [ "$1" == "check" ]; then
  if ! has_scrolllock_led; then
    echo "unsupported"
  elif [[ -f "$ruleFile" ]]; then
    echo "true"
  else
    echo "false"
  fi

elif [ "$1" == "toggle" ]; then
  state="$2"
  case "$state" in
    true) action="enable" ;;
    false) action="disable" ;;
    *) exit 2 ;;
  esac
  has_scrolllock_led || exit 1
  pkexec /usr/share/biglinux/biglinux-settings/usability/keyboardLedRun.sh "$action"
  exit $?
fi
