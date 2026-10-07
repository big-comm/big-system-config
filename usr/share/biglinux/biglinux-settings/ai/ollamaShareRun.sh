#!/bin/bash
set -euo pipefail

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# Assign the received arguments to variables with clear names
function="${1:-}"
# Overridable only for the test suite, and never when running as root.
dropInDir="/etc/systemd/system/ollama.service.d"
if [[ $EUID -ne 0 ]]; then
  dropInDir="${BIGLINUX_SETTINGS_OLLAMA_DROPIN_DIR:-$dropInDir}"
fi
dropInFile="${dropInDir}/90-biglinux-network.conf"

unit_exists() {
  systemctl cat ollama.service >/dev/null 2>&1
}

# Executes the root tasks.
case "$function" in
  install)
    # Refuse before writing anything: a drop-in for a unit that does not exist
    # would just be left behind.
    if ! unit_exists; then
      echo "ollama.service not found; install Ollama first" >&2
      exit 1
    fi
    install -d -m 0755 "$dropInDir"
    tmpFile="$(mktemp "${dropInDir}/.90-biglinux-network.XXXXXX")"
    trap 'rm -f "$tmpFile"' EXIT
    printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0"\n' > "$tmpFile"
    chmod 0644 "$tmpFile"
    mv -f "$tmpFile" "$dropInFile"
    trap - EXIT
    ;;
  uninstall)
    rm -f "$dropInFile"
    rmdir "$dropInDir" 2>/dev/null || true
    ;;
  *)
    echo "Invalid action: $function" >&2
    exit 2
    ;;
esac

systemctl daemon-reload
# Apply the new environment only if Ollama is running; never start a stopped
# service just because sharing was toggled.
if unit_exists; then
  systemctl try-restart ollama.service
fi
