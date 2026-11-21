#!/bin/bash
# s2idle.sh — Toggle s2idle (freeze) as default suspend mode via kernel cmdline.
# This prevents ASUS EC GPE storm after resuming from S3 deep sleep.

# shellcheck source=../grub-default.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../grub-default.sh"
PARAM="mem_sleep_default=s2idle"

if [ "$1" == "check" ]; then
    if [[ "$(grub_count_tokens "$PARAM")" == 1 ]]; then
        echo "true"
    else
        echo "false"
    fi

elif [ "$1" == "toggle" ]; then
    case "$2" in
        true) action=enable ;;
        false) action=disable ;;
        *) exit 2 ;;
    esac
    if [ "$(id -u)" -ne 0 ]; then
        exec pkexec "$(readlink -f "$0")" "$@"
    fi
    grub_toggle_tokens "$action" "$PARAM"
fi
