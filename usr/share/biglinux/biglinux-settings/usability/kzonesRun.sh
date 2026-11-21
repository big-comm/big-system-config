#!/bin/bash

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# Assign the received arguments to variables with clear names
function="$1"

# Executes the root tasks.
updateKzonesTask() {
  if [[ "$function" == "install" ]]; then
    pacman -Syu --needed --noconfirm kwin-scripts-kzones
  fi
  exitCode=$?
}
updateKzonesTask

# Exits the script with the correct exit code
exit $exitCode
