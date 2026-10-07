#!/bin/bash
set -euo pipefail

dropInDir="/etc/systemd/logind.conf.d"
dropInFile="$dropInDir/90-biglinux-lid-policy.conf"
legacyFile="$dropInDir/biglinux-lid-suspend.conf"
lockFile="/run/lock/biglinux-lid-policy.lock"

property_for_source() {
  case "$1" in
    ac) printf '%s\n' HandleLidSwitchExternalPower ;;
    battery) printf '%s\n' HandleLidSwitch ;;
    *) return 2 ;;
  esac
}

managed_state() {
  local property
  property="$(property_for_source "$1")"
  [[ -r "$dropInFile" ]] && grep -Fxq "$property=ignore" "$dropInFile"
}

effective_state() {
  local property value
  property="$(property_for_source "$1")"
  value="$(
    busctl get-property \
      org.freedesktop.login1 \
      /org/freedesktop/login1 \
      org.freedesktop.login1.Manager \
      "$property" 2>/dev/null
  )"
  [[ "$value" == 's "ignore"' ]]
}

# Print a logind lid action property ("" when unset or unreadable).
read_property() {
  local value
  value="$(
    busctl get-property \
      org.freedesktop.login1 \
      /org/freedesktop/login1 \
      org.freedesktop.login1.Manager \
      "$1" 2>/dev/null
  )" || value=""
  value="${value#s \"}"
  value="${value%\"}"
  if [[ "$value" =~ ^[a-z-]+$ ]]; then
    printf '%s\n' "$value"
  fi
  return 0
}

# Lid action on AC to write explicitly when only battery is managed.
# logind ignores an unset HandleLidSwitchExternalPower= and falls back to
# HandleLidSwitch=, so "HandleLidSwitch=ignore" alone would also stop the lid
# from suspending on AC. Keep what logind did on AC before; "ignore" may be our
# own previous setting, so it is not trusted and becomes logind's default.
ac_lid_action() {
  local value
  value="$(read_property HandleLidSwitchExternalPower)"
  [[ -n "$value" ]] || value="$(read_property HandleLidSwitch)"
  if [[ -z "$value" || "$value" == ignore ]]; then
    value=suspend
  fi
  printf '%s\n' "$value"
}

reload_logind() {
  systemctl kill --kill-whom=main --signal=HUP systemd-logind.service
}

wait_until_effective() {
  local source="$1"
  for _attempt in {1..20}; do
    if effective_state "$source"; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

write_policy() {
  local acEnabled="$1" batteryEnabled="$2" acAction="$3" temporary

  if [[ "$acEnabled" != true && "$batteryEnabled" != true ]]; then
    rm -f -- "$dropInFile"
    return
  fi

  install -d -m 0755 "$dropInDir"
  temporary="$(mktemp "$dropInDir/.90-biglinux-lid-policy.XXXXXX")"
  trap 'rm -f -- "$temporary"' RETURN
  {
    printf '%s\n' '[Login]'
    [[ "$batteryEnabled" == true ]] && printf '%s\n' 'HandleLidSwitch=ignore'
    if [[ "$acEnabled" == true ]]; then
      printf '%s\n' 'HandleLidSwitchExternalPower=ignore'
    else
      printf 'HandleLidSwitchExternalPower=%s\n' "$acAction"
    fi
    printf '%s\n' 'HandleLidSwitchDocked=ignore'
  } > "$temporary"
  chmod 0644 "$temporary"
  mv -f -- "$temporary" "$dropInFile"
  trap - RETURN
}

case "${1:-}" in
  check)
    sourceName="${2:-}"
    property_for_source "$sourceName" >/dev/null
    if managed_state "$sourceName" && effective_state "$sourceName"; then
      echo true
    else
      echo false
    fi
    ;;
  toggle)
    [[ "$(id -u)" -eq 0 ]] || exit 1
    exec 9>"$lockFile"
    flock 9
    sourceName="${2:-}"
    state="${3:-}"
    property_for_source "$sourceName" >/dev/null
    [[ "$state" == true || "$state" == false ]] || exit 2

    acEnabled=false
    batteryEnabled=false
    managed_state ac && acEnabled=true
    managed_state battery && batteryEnabled=true
    if [[ "$sourceName" == ac ]]; then
      acEnabled="$state"
    else
      batteryEnabled="$state"
    fi

    previousDropIn="$(mktemp)"
    previousLegacy="$(mktemp)"
    trap 'rm -f -- "$previousDropIn" "$previousLegacy"' EXIT
    [[ -f "$dropInFile" ]] && cp -a -- "$dropInFile" "$previousDropIn"
    [[ -f "$legacyFile" ]] && cp -a -- "$legacyFile" "$previousLegacy"
    hadDropIn=false
    hadLegacy=false
    [[ -s "$previousDropIn" ]] && hadDropIn=true
    [[ -s "$previousLegacy" ]] && hadLegacy=true

    acAction=suspend
    [[ "$acEnabled" == true ]] || acAction="$(ac_lid_action)"
    # The legacy file goes only once the new policy is in place: if writing
    # fails, set -e exits here with the previous configuration untouched.
    write_policy "$acEnabled" "$batteryEnabled" "$acAction"
    rm -f -- "$legacyFile"
    if ! reload_logind || { [[ "$state" == true ]] && ! wait_until_effective "$sourceName"; }; then
      if [[ "$hadDropIn" == true ]]; then
        cp -a -- "$previousDropIn" "$dropInFile"
      else
        rm -f -- "$dropInFile"
      fi
      if [[ "$hadLegacy" == true ]]; then
        cp -a -- "$previousLegacy" "$legacyFile"
      fi
      reload_logind || true
      exit 1
    fi
    ;;
  *)
    exit 2
    ;;
esac
