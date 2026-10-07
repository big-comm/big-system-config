#!/bin/bash

# check current status
if [ "$1" == "check" ]; then
  if ([[ "$XDG_CURRENT_DESKTOP" == *"KDE"* ]] || [[ "$XDG_CURRENT_DESKTOP" == *"Plasma"* ]]) && command -v kreadconfig6 >/dev/null 2>&1;then
    if [[ "$(LANG=C kreadconfig6 --file kwinrc --group Plugins --key kzonesEnabled)" == "true" ]] && pacman -Q kwin-scripts-kzones &>/dev/null; then
      echo "true"
    else
      echo "false"
    fi
  else
    echo "unsupported"
  fi

# change the state
elif [ "$1" == "toggle" ]; then
  state="$2"
  exitCode=0
  if [[ "$XDG_CURRENT_DESKTOP" == *"KDE"* ]] || [[ "$XDG_CURRENT_DESKTOP" == *"Plasma"* ]];then
    if [ "$state" == "true" ]; then
      if ! pacman -Q kwin-scripts-kzones &>/dev/null; then
        pkexec /usr/share/biglinux/biglinux-settings/usability/kzonesRun.sh "install" "$USER" "$DISPLAY" "$XAUTHORITY" "$DBUS_SESSION_BUS_ADDRESS" "$LANG" "$LANGUAGE" || exit $?
      fi
      kwriteconfig6 --file kwinrc --group Plugins --key kzonesEnabled true
      qdbus6 org.kde.KWin /KWin reconfigure
      exitCode=$?
    else
      kwriteconfig6 --file kwinrc --group Plugins --key kzonesEnabled false
      qdbus6 org.kde.KWin /KWin reconfigure
      exitCode=$?
    fi
  else
    exitCode=1
  fi
  exit $exitCode
fi
