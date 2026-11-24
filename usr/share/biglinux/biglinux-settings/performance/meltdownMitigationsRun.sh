#!/bin/bash
# Root helper: adds (enable) or removes (disable) the kernel parameters in
# /etc/default/grub and regenerates grub.cfg.

# shellcheck source=../grub-default.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../grub-default.sh"

grub_toggle_tokens "${1:-}" mitigations=off
