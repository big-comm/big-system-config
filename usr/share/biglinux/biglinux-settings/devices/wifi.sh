#!/bin/bash

# check current status
if [ "$1" == "check" ];then
  # Query nmcli once; anything other than enabled/disabled (nmcli missing,
  # NetworkManager not running, no Wi-Fi radio) means unsupported.
  if command -v nmcli &>/dev/null && radio="$(LANG=C LANGUAGE=C nmcli radio wifi 2>/dev/null)"; then
    case "$radio" in
      enabled) echo "true" ;;
      disabled) echo "false" ;;
      *) echo "unsupported" ;;
    esac
  else
    echo "unsupported"
  fi

# change the state
elif [ "$1" == "toggle" ];then
  state="$2"
  if [ "$state" == "true" ];then
    nmcli radio wifi on
    exitCode=$?
  else
    nmcli radio wifi off
    exitCode=$?
  fi
  exit $exitCode
fi
