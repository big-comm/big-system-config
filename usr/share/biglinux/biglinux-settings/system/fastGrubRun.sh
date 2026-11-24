#!/bin/bash
# Root helper: sets GRUB_TIMEOUT in /etc/default/grub and regenerates grub.cfg,
# putting the previous file back when either step fails.

# shellcheck source=../grub-default.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../grub-default.sh"

timeout="${1:-}"
if [[ ! "$timeout" =~ ^[0-9]+$ ]]; then
  echo "Usage: $0 <timeout in seconds>" >&2
  exit 2
fi
[[ -f "$grub_file" ]] || exit 1
grub_lock || exit 1
[[ "$(grub_value GRUB_TIMEOUT)" == "$timeout" ]] && exit 0

backup="$(mktemp)" || exit 1
trap 'rm -f -- "$backup"' EXIT
cp -- "$grub_file" "$backup" || exit 1

if ! grub_replace_line GRUB_TIMEOUT "GRUB_TIMEOUT=$timeout" ||
  [[ "$(grub_value GRUB_TIMEOUT)" != "$timeout" ]] || ! run_update_grub; then
  grub_write "$backup"
  exit 1
fi
