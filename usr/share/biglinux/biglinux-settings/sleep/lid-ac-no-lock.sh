#!/bin/bash
set -euo pipefail

scriptDir="$(dirname "$(readlink -f "$0")")"
exec "$scriptDir/screen_lock_policy.py" "${1:-}" "${2:-}"
