#!/bin/bash
set -euo pipefail

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# check current status
if [ "${1:-}" == "check" ]; then
  if [[ -f "$HOME/ComfyUI/.biglinux-settings-managed" && -x "$HOME/ComfyUI/bin/python" && -f "$HOME/ComfyUI/main.py" ]]; then
    echo "true"
  else
    echo "false"
  fi

# change the state
elif [ "${1:-}" == "toggle" ]; then
  state="${2:-}"
  [[ "$state" == "true" || "$state" == "false" ]] || exit 2
  if [ "$state" == "true" ]; then
    vgaList=$(lspci | grep -iE "VGA|3D|Display")
    if [[ -z "$(echo $vgaList | grep -Ei '(nvidia|radeon|amd|\bati)')" ]]; then
      gettext "AMD/Nvidia GPU not found!" >&2
      echo >&2
      exit 1
    fi

    # install depends as root
    if ! pacman -Q python-pip &>/dev/null || ! pacman -Q git &>/dev/null; then
      pkexec /usr/share/biglinux/biglinux-settings/ai/comfyUIDepends.sh "install" "$USER" "${DISPLAY:-}" "${XAUTHORITY:-}" "${DBUS_SESSION_BUS_ADDRESS:-}" "${LANG:-}" "${LANGUAGE:-}"
    fi
    # install comfyUI as user
    /usr/share/biglinux/biglinux-settings/ai/comfyUIInstall.sh "install"
    exitCode=$?
  else
    /usr/share/biglinux/biglinux-settings/ai/comfyUIInstall.sh "uninstall"
    exitCode=$?
  fi
  exit "$exitCode"
else
  exit 2
fi
