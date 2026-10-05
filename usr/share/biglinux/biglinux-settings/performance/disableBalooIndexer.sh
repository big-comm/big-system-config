#!/bin/bash

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# check current status
if [ "$1" == "check" ]; then
  if [[ "$XDG_CURRENT_DESKTOP" == *"KDE"* ]] || [[ "$XDG_CURRENT_DESKTOP" == *"Plasma"* ]];then
    if balooctl6 status &>/dev/null;then
      echo "false"
    else
      echo "true"
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
      balooctl6 disable &>/dev/null
      exitCode=$?
    else
      balooctl6 enable &>/dev/null
      exitCode=$?
    fi
  else
    exitCode=1
  fi
  exit $exitCode
fi
