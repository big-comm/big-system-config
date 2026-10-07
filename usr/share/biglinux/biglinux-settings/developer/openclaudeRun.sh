#!/bin/bash

# Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# Arguments
function="$1"

installTask() {
  if [[ "$function" == "install" ]]; then
    # Ensure required system dependencies
    pacman -Syu --needed --noconfirm nodejs npm ripgrep
    depStatus=$?
    if [ "$depStatus" -ne 0 ]; then
      exitCode=$depStatus
      return
    fi
    # Install OpenClaude globally via npm. This runs as root, so lifecycle
    # scripts are disabled: neither @gitlawb/openclaude nor its dependency tree
    # needs one (checked on 0.31.0; @vscode/ripgrep >= 1.18 ships its binary in
    # per-platform optional packages instead of downloading it in postinstall).
    npm install -g --ignore-scripts @gitlawb/openclaude
    exitCode=$?
  else
    npm uninstall -g @gitlawb/openclaude
    exitCode=$?
  fi
}
installTask

exit $exitCode
