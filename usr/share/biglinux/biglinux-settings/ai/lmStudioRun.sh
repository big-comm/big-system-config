#!/bin/bash

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# Assign the received arguments to variables with clear names
function="$1"

# Executes the root tasks.
updateTask() {
  if [[ "$function" == "install" ]]; then
    pacman -Syu --needed --noconfirm lmstudio-bin
  else
    pacman -Rcs --noconfirm lmstudio-bin
  fi
  exitCode=$?
}
updateTask

# Exits the script with the correct exit code
exit $exitCode
