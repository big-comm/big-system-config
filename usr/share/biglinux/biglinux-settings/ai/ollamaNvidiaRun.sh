#!/bin/bash

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# Assign the received arguments to variables with clear names
function="$1"
package="ollama-cuda"

# Note on the Ollama variants: in the Arch repositories ollama-cuda,
# ollama-rocm and ollama-vulkan are add-on backends that depend on the base
# "ollama" package (which ships ollama.service); none of them conflicts with
# another, so no conflict resolution (e.g. --ask 4) is needed here.

# Executes the root tasks. Every step is checked: a failed pacman must not be
# hidden by a successful systemctl (or vice versa).
updateTask() {
  if [[ "$function" == "install" ]]; then
    pacman -Syu --needed --noconfirm "$package" || return 1
    systemctl enable --now ollama.service || return 1
  elif [[ "$function" == "uninstall" ]]; then
    # Nothing to do if the package is already gone.
    pacman -Q "$package" &>/dev/null || return 0
    systemctl disable --now ollama.service || return 1
    if ! pacman -Rcs --noconfirm "$package"; then
      # Removal failed: put the service back as it was.
      systemctl enable --now ollama.service
      return 1
    fi
    # Another variant (or an explicitly installed ollama) may still be
    # installed; keep the service running for it.
    if pacman -Q ollama &>/dev/null; then
      systemctl enable --now ollama.service || return 1
    fi
  else
    echo "Invalid action: $function" >&2
    return 2
  fi
  return 0
}
updateTask
exitCode=$?

# Exits the script with the correct exit code
exit $exitCode
