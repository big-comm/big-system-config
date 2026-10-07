#!/bin/bash
set -euo pipefail

is_plasma() {
  [[ "${XDG_CURRENT_DESKTOP:-}" == *"KDE"* || "${XDG_CURRENT_DESKTOP:-}" == *"Plasma"* ]]
}

# check current status
if [ "${1:-}" == "check" ]; then
  if is_plasma && command -v qdbus6 >/dev/null 2>&1 && command -v kpackagetool6 >/dev/null 2>&1;then
    if grep -q "plugin=ChatAI-Plasmoid" "$HOME/.config/plasma-org.kde.plasma.desktop-appletsrc"; then
      echo "true"
    else
      echo "false"
    fi
  else
    echo "unsupported"
  fi

# change the state
elif [ "${1:-}" == "toggle" ]; then
  state="${2:-}"
  [[ "$state" == "true" || "$state" == "false" ]] || exit 2
  if is_plasma && command -v qdbus6 >/dev/null 2>&1 && command -v kpackagetool6 >/dev/null 2>&1;then
    if [ "$state" == "true" ]; then
      # check and download chatai
      if ! kpackagetool6 -t Plasma/Applet -l 2>/dev/null | grep -q "ChatAI-Plasmoid"; then
        metadataFile="$(mktemp)"
        archiveFile="$(mktemp --suffix=.tar.gz)"
        trap 'rm -f "$metadataFile" "$archiveFile"' EXIT
        curl --proto '=https' --proto-redir '=https' --fail --silent --show-error --location \
          https://api.github.com/repos/DenysMb/ChatAI-Plasmoid/releases/latest \
          --output "$metadataFile"
        mapfile -t assetData < <(python3 - "$metadataFile" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    release = json.load(stream)
for asset in release.get("assets", []):
    if asset.get("name", "").endswith(".tar.gz"):
        print(asset.get("browser_download_url", ""))
        print(asset.get("digest", ""))
        break
PY
        )
        archiveUrl="${assetData[0]:-}"
        archiveDigest="${assetData[1]:-}"
        if [[ ! "$archiveUrl" =~ ^https://github\.com/DenysMb/ChatAI-Plasmoid/releases/download/ ]] ||
           [[ ! "$archiveDigest" =~ ^sha256:[0-9a-fA-F]{64}$ ]]; then
          echo "Invalid ChatAI release asset or SHA-256 digest" >&2
          exit 1
        fi
        curl --proto '=https' --proto-redir '=https' --fail --show-error --location "$archiveUrl" --output "$archiveFile"
        printf '%s  %s\n' "${archiveDigest#sha256:}" "$archiveFile" | sha256sum --check --status
        kpackagetool6 -t Plasma/Applet -i "$archiveFile"
      fi
      # Unlock desktop editing mode
      qdbus6 org.kde.plasmashell /PlasmaShell evaluateScript "lockCorona(false)"
      qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "
              var allPanels = panels();
              for (var i = 0; i < allPanels.length; i++) {
                  allPanels[i].addWidget('ChatAI-Plasmoid');
              }"
      # Lock desktop editing mode again
      qdbus6 org.kde.plasmashell /PlasmaShell evaluateScript "lockCorona(true)"
    else
      ## remove chatai
      # Unlock desktop editing mode
      qdbus6 org.kde.plasmashell /PlasmaShell evaluateScript "lockCorona(false)"
      # remove widget from panel
      qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "
          panelIds.forEach(pId => {
              let p = panelById(pId);
              p.widgetIds.forEach(wId => {
                  let w = p.widgetById(wId);
                  if (w.type === 'ChatAI-Plasmoid') {
                      w.remove();
                  }
              });
          });"
      # Lock desktop editing mode again
      qdbus6 org.kde.plasmashell /PlasmaShell evaluateScript "lockCorona(true)"
      kpackagetool6 -t Plasma/Applet -r ChatAI-Plasmoid
    fi
  else
    echo "Unsupported desktop environment" >&2
    exit 1
  fi
else
  exit 2
fi
