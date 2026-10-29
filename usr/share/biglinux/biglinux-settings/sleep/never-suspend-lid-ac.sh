#!/bin/bash
set -euo pipefail

scriptDir="$(dirname "$(readlink -f "$0")")"
if [[ "${1:-}" == toggle && "${2:-}" == false ]]; then
  "$scriptDir/lid_policy.py" toggle ac false
  # The "don't lock the screen" sub-option only makes sense with the lid
  # policy on; bring the lock back so it is not left off while hidden.
  exec "$scriptDir/screen_lock_policy.py" toggle false
fi
exec "$scriptDir/lid_policy.py" "${1:-}" ac "${2:-}"
