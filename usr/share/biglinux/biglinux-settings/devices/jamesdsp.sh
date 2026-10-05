#!/bin/bash

# Turn JamesDSP autostart on or off.
#
# This used to also enable/disable jamesdsp-autostart.service, a user unit that
# duplicated the app's own autostart (~/.config/autostart/jdsp-gui.desktop, rewritten
# by JamesDSP whenever the option is toggled in its GUI). Both fired at login and the
# loser failed the D-Bus single-instance check, looping on Restart=on-failure until
# one of the short-lived instances tore down the PipeWire filter and left
# jamesdsp_sink with no route to the real sink. The unit is gone; the shared helper
# from biglinux-improve-compatibility drives the upstream mechanism instead.
setAutostart() {
  if [ -x /usr/bin/biglinux-jamesdsp-autostart ]; then
    /usr/bin/biglinux-jamesdsp-autostart "$1"
    return $?
  fi

  # Fallback when biglinux-improve-compatibility is absent: keep the flag consistent.
  # The config file may not exist yet right after installing JamesDSP, and that is not
  # a failure to report back to the panel.
  [ -e "$jamesdsp_conf" ] || return 0

  if [ "$1" = "enable" ]; then
    sed -i 's|AutoStartEnabled=false|AutoStartEnabled=true|g' "$jamesdsp_conf" 2>/dev/null
  else
    sed -i 's|AutoStartEnabled=true|AutoStartEnabled=false|g' "$jamesdsp_conf" 2>/dev/null
  fi
}

# check current status
if [ "$1" == "check" ]; then
  if pacman -Q jamesdsp &>/dev/null && \
     grep -q 'AutoStartEnabled=true' "$HOME/.config/jamesdsp/application.conf" 2>/dev/null; then
    echo "true"
  else
    echo "false"
  fi

# change the state
elif [ "$1" == "toggle" ]; then
  state="$2"
  jamesdsp_conf="$HOME/.config/jamesdsp/application.conf"
  if [ "$state" == "true" ]; then
    if ! pacman -Q jamesdsp &>/dev/null; then
      pkexec /usr/share/biglinux/biglinux-settings/devices/jamesdspRun.sh "install" "$USER" "$DISPLAY" "$XAUTHORITY" "$DBUS_SESSION_BUS_ADDRESS" "$LANG" "$LANGUAGE" || exit $?
    fi
    mkdir -p "$HOME/.config/jamesdsp/presets"
    # Keep the user's own tuning of the preset
    if [ ! -e "$HOME/.config/jamesdsp/presets/big-jamesdsp.conf" ]; then
      cp '/etc/skel/.config/jamesdsp/presets/big-jamesdsp.conf' "$HOME/.config/jamesdsp/presets/big-jamesdsp.conf"
    fi
    jamesdsp --set master_enable=true
    setAutostart enable
    exitCode=$?
  else
    jamesdsp --set master_enable=false
    setAutostart disable
    exitCode=$?
  fi
  exit $exitCode
fi
