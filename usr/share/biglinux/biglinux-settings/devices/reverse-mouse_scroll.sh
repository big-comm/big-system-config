#!/bin/bash

# Config File
kcminputrcFile="$HOME/.config/kcminputrc"

# check current status
if [ "$1" == "check" ]; then
  if ([[ "$XDG_CURRENT_DESKTOP" == *"KDE"* ]] || [[ "$XDG_CURRENT_DESKTOP" == *"Plasma"* ]]) && command -v kreadconfig6 >/dev/null 2>&1;then
    if [[ "$(LANG=C LANGUAGE=C kreadconfig6 --file "$kcminputrcFile" --group "Mouse" --key "NaturalScroll")" == "true" ]];then
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
      kwriteconfig6 --file "$kcminputrcFile" --group "Mouse" --key "NaturalScroll" "true"
      exitCode=$?

      devices=$(qdbus6 org.kde.KWin | grep "/org/kde/KWin/InputDevice/event")
      for device in $devices; do
        qdbus6 org.kde.KWin "$device" org.kde.KWin.InputDevice.naturalScroll true &> /dev/null
      done
    else
      kwriteconfig6 --file "$kcminputrcFile" --group "Mouse" --key "NaturalScroll" "false"
      exitCode=$?

      devices=$(qdbus6 org.kde.KWin | grep "/org/kde/KWin/InputDevice/event")
      for device in $devices; do
        qdbus6 org.kde.KWin "$device" org.kde.KWin.InputDevice.naturalScroll false &> /dev/null
      done
    fi
  else
    exitCode=1
  fi
  exit $exitCode
fi
