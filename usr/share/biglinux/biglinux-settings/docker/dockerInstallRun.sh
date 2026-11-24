#!/bin/bash
set -euo pipefail

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# Assign the received arguments to variables with clear names
function="${1:-}"
package="${2:-}"
originalUser="${5:-}"

# Executes the root tasks.
if [[ ! "$package" =~ ^biglinux-docker-[a-zA-Z0-9@+._-]+$ ]]; then
  echo "Invalid package: $package" >&2
  exit 2
fi

case "$function" in
  install)
    if ! id "$originalUser" >/dev/null 2>&1; then
      echo "Invalid user: $originalUser" >&2
      exit 2
    fi
    pacman -Syu --needed --noconfirm "$package"
    userHome="$(getent passwd "$originalUser" | cut -d: -f6)"
    dockerDir="${userHome}/Docker"
    if [[ -d "$dockerDir" ]]; then
      chown "$originalUser:" "$dockerDir"
    fi
    ;;
  remove)
    pacman -Rs --noconfirm "$package"
    ;;
  *)
    echo "Invalid action: $function" >&2
    exit 2
    ;;
esac
