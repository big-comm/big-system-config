#!/bin/bash
set -euo pipefail

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# check current status
if [ "${1:-}" == "check" ]; then
  if [[ -d "$HOME/.local/share/krita/pykrita/ai_diffusion" ]] && pacman -Q krita &>/dev/null; then
    echo "true"
  else
    echo "false"
  fi

# change the state
elif [ "${1:-}" == "toggle" ]; then
  state="${2:-}"
  [[ "$state" == "true" || "$state" == "false" ]] || exit 2
  if [ "$state" == "true" ]; then
    if ! pacman -Q krita &>/dev/null || ! command -v 7z >/dev/null 2>&1; then
      pkexec /usr/share/biglinux/biglinux-settings/ai/kritaRun.sh install
    fi
    killall krita 2>/dev/null || true

    metadataFile="$(mktemp)"
    archiveFile="$(mktemp --suffix=.zip)"
    trap 'rm -f "$metadataFile" "$archiveFile"' EXIT
    curl --proto '=https' --proto-redir '=https' --fail --silent --show-error --location \
      https://api.github.com/repos/Acly/krita-ai-diffusion/releases/latest \
      --output "$metadataFile"
    mapfile -t assetData < <(python3 - "$metadataFile" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    release = json.load(stream)
for asset in release.get("assets", []):
    if asset.get("name", "").endswith(".zip"):
        print(asset.get("browser_download_url", ""))
        print(asset.get("digest", ""))
        break
PY
    )
    diffusionUrl="${assetData[0]:-}"
    diffusionDigest="${assetData[1]:-}"
    if [[ ! "$diffusionUrl" =~ ^https://github\.com/Acly/krita-ai-diffusion/releases/download/ ]] ||
       [[ ! "$diffusionDigest" =~ ^sha256:[0-9a-fA-F]{64}$ ]]; then
      echo "Release asset or SHA-256 digest is unavailable" >&2
      exit 1
    fi
    curl --proto '=https' --proto-redir '=https' --fail --show-error --location "$diffusionUrl" --output "$archiveFile"
    printf '%s  %s\n' "${diffusionDigest#sha256:}" "$archiveFile" | sha256sum --check --status

    pluginDir="$HOME/.local/share/krita/pykrita"
    actionDir="$HOME/.local/share/krita/actions"
    mkdir -p "$pluginDir" "$actionDir"
    7z x -y "$archiveFile" "-o${pluginDir}"
    cp "$pluginDir/ai_diffusion/ai_diffusion.action" "$actionDir/"
    kwriteconfig6 --file kritarc --group "python" --key "enable_ai_diffusion" "true"
  else
    killall krita 2>/dev/null || true
    rm -rf -- "$HOME/.local/share/krita/pykrita/ai_diffusion"
    rm -f -- "$HOME/.local/share/krita/pykrita/ai_diffusion.desktop"
    rm -f -- "$HOME/.local/share/krita/actions/ai_diffusion.action"
    kwriteconfig6 --file kritarc --group "python" --key "enable_ai_diffusion" "false"
  fi
else
  exit 2
fi
