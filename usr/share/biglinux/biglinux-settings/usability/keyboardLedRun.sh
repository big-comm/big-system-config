#!/bin/bash
set -euo pipefail

# Keep the keyboard light on: many backlit keyboards wire the light to the
# Scroll Lock LED. Runs as root through pkexec.
#
# The kernel ties that LED to the Scroll Lock key state (trigger
# "kbd-scrolllock"), so pressing the key or switching VT turns the light off.
# Setting the trigger to "none" detaches it and keeps it on. A udev rule
# applies the same to every keyboard, including ones plugged in later and
# after a reboot.

action="${1:-}"

# Test-only overrides, ignored when running as root
ledsDir="/sys/class/leds"
rulesDir="/etc/udev/rules.d"
if [[ $EUID -ne 0 ]]; then
  ledsDir="${BIGLINUX_LEDS_DIR:-$ledsDir}"
  rulesDir="${BIGLINUX_UDEV_RULES_DIR:-$rulesDir}"
fi
ruleFile="$rulesDir/99-biglinux-keyboard-led.rules"

# Applies to the LEDs present now; the udev rule covers the ones to come
apply_now() {
  local trigger="$1" brightness="$2" led failed=0
  shopt -s nullglob
  for led in "$ledsDir"/*::scrolllock; do
    if ! printf '%s\n' "$trigger" > "$led/trigger"; then
      failed=1
      continue
    fi
    if [[ -n "$brightness" ]]; then
      # max_brightness is 1 for input LEDs, but do not assume it
      cat "$led/max_brightness" > "$led/brightness" || failed=1
    fi
  done
  shopt -u nullglob
  return "$failed"
}

case "$action" in
  enable)
    install -d -m 0755 "$rulesDir"
    tmp="$(mktemp "$rulesDir/.99-biglinux-keyboard-led.XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    # The kernel clamps brightness to max_brightness
    printf '%s\n' \
      '# Managed by biglinux-settings: keep the keyboard light (Scroll Lock LED) on' \
      'ACTION=="add", SUBSYSTEM=="leds", KERNEL=="*::scrolllock", ATTR{trigger}="none", ATTR{brightness}="255"' \
      > "$tmp"
    chmod 0644 "$tmp"
    mv -f "$tmp" "$ruleFile"
    trap - EXIT
    apply_now none max
    ;;
  disable)
    rm -f "$ruleFile"
    # Hand the LED back to the Scroll Lock key
    apply_now kbd-scrolllock ""
    ;;
  *)
    echo "Usage: $0 enable|disable" >&2
    exit 2
    ;;
esac
