#!/bin/bash
set -euo pipefail

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# Assign the received arguments to variables with clear names
function="${1:-}"
installDir="$HOME/ComfyUI"
markerFile="$installDir/.biglinux-settings-managed"

# Executes tasks.
case "$function" in
  install)
    if [[ -e "$installDir" ]]; then
      echo "$installDir already exists and was not created by BigLinux Settings" >&2
      exit 1
    fi

    tempDir="$(mktemp -d "$HOME/.ComfyUI-install.XXXXXX")"
    # Directory this run created at the final location; removed again if the
    # install does not finish (it never has the management marker then).
    stagedDir=""
    cleanup() {
      rm -rf -- "$tempDir"
      if [[ -n "$stagedDir" && ! -f "$stagedDir/.biglinux-settings-managed" ]]; then
        rm -rf -- "$stagedDir"
      fi
    }
    trap cleanup EXIT
    metadataFile="$tempDir/release.json"
    curl --fail --silent --show-error --location \
      https://api.github.com/repos/Comfy-Org/ComfyUI/releases/latest \
      --output "$metadataFile"
    releaseTag="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["tag_name"])' "$metadataFile")"
    if [[ ! "$releaseTag" =~ ^v?[0-9][a-zA-Z0-9._-]*$ ]]; then
      echo "Invalid ComfyUI release tag: $releaseTag" >&2
      exit 1
    fi

    repoDir="$tempDir/repo"
    git clone --depth 1 --branch "$releaseTag" https://github.com/Comfy-Org/ComfyUI.git "$repoDir"

    # The venv must be created at its final path: venv and pip hard-code the
    # absolute path in bin/activate and in the shebang of every bin/ script,
    # so a venv built in the temp dir and moved afterwards is broken.
    # `mv -T` refuses to move into a directory that appeared in the meantime.
    mv -T -- "$repoDir" "$installDir"
    stagedDir="$installDir"
    repoDir="$installDir"
    python -m venv "$repoDir"

    vgaList="$(lspci | grep -iE 'VGA|3D|Display' || true)"
    if grep -Eiq '(radeon|amd|\bati)' <<< "$vgaList"; then
      gpu="amd"
      "$repoDir/bin/pip" install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.1
    elif grep -iq nvidia <<< "$vgaList"; then
      gpu="nvidia"
      "$repoDir/bin/pip" install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu130
    else
      echo "AMD/Nvidia GPU not found" >&2
      exit 1
    fi
    "$repoDir/bin/pip" install --requirement "$repoDir/requirements.txt"

    commit="$(git -C "$repoDir" rev-parse HEAD)"
    # Writing the marker last is what marks the install as complete.
    printf 'release=%s\ncommit=%s\ngpu=%s\n' "$releaseTag" "$commit" "$gpu" > "$repoDir/.biglinux-settings-managed"
    ;;
  uninstall)
    if [[ ! -f "$markerFile" ]]; then
      echo "$installDir is not managed by BigLinux Settings; refusing to remove it" >&2
      exit 1
    fi
    /usr/share/biglinux/biglinux-settings/ai/comfyUIRun.sh toggle false || true
    rm -rf -- "$installDir"
    ;;
  *)
    echo "Invalid action: $function" >&2
    exit 2
    ;;
esac
