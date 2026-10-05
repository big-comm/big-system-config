#!/bin/bash
# s2idle.sh — Toggle s2idle (freeze) as default suspend mode via kernel cmdline.
# This prevents ASUS EC GPE storm after resuming from S3 deep sleep.

# BIGLINUX_GRUB_FILE and BIGLINUX_GRUB_UPDATE exist only for the test suite and
# are ignored when running as root, so they can never redirect a real edit or
# run a command with root privileges, whatever way the script is started.
GRUB_FILE="/etc/default/grub"
GRUB_UPDATE_OVERRIDE=""
if [[ $EUID -ne 0 ]]; then
    GRUB_FILE="${BIGLINUX_GRUB_FILE:-$GRUB_FILE}"
    GRUB_UPDATE_OVERRIDE="${BIGLINUX_GRUB_UPDATE:-}"
fi
PARAM="mem_sleep_default=s2idle"

_require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        exec pkexec "$(readlink -f "$0")" "$@"
    fi
}

# Print the value of the last active KEY= line (grub sources the file, so the
# last assignment wins). Commented lines are ignored; double, single and no
# quotes are accepted. Returns 1 when there is no such line.
_grub_value() {
    local line value
    line="$(grep -E "^[[:space:]]*$1=" "$GRUB_FILE" 2>/dev/null | tail -n 1)"
    [[ -n "$line" ]] || return 1
    value="${line#*=}"
    case "$value" in
        \"*) value="${value#\"}"; value="${value%%\"*}" ;;
        \'*) value="${value#\'}"; value="${value%%\'*}" ;;
        *) value="${value%%[[:space:]]*}" ;;
    esac
    printf '%s\n' "$value"
}

# Replace the last active KEY= line with KEY="value" (keeping single quotes if
# they were used), or append the line when the key is missing.
_grub_set() {
    local key="$1" value="$2" quote='"' line tmp rc
    line="$(grep -E "^[[:space:]]*$key=" "$GRUB_FILE" | tail -n 1)"
    [[ "${line#*=}" == \'* ]] && quote="'"
    tmp="$(mktemp)" || return 1
    if [[ -n "$line" ]]; then
        grub_line="$key=$quote$value$quote" grub_key="$key" awk '
            { lines[NR] = $0 }
            $0 ~ "^[[:space:]]*" ENVIRON["grub_key"] "=" { last = NR }
            END { for (i = 1; i <= NR; i++) print (i == last ? ENVIRON["grub_line"] : lines[i]) }
        ' "$GRUB_FILE" > "$tmp"
    else
        { cat "$GRUB_FILE"; [[ -s "$GRUB_FILE" && -n "$(tail -c 1 "$GRUB_FILE")" ]] && echo
          printf '%s=%s%s%s\n' "$key" "$quote" "$value" "$quote"; } > "$tmp"
    fi
    # Write through the existing file to keep its permissions and symlinks
    cat "$tmp" > "$GRUB_FILE"
    rc=$?
    rm -f "$tmp"
    return $rc
}

# Rewrite KEY without PARAM, optionally adding it back once at the start
_grub_edit() {
    local key="$1" add="$2" word words kept=()
    [[ "$add" == "true" ]] && kept=("$PARAM")
    read -ra words <<< "$(_grub_value "$key")"
    for word in "${words[@]}"; do
        [[ "$word" == "$PARAM" ]] || kept+=("$word")
    done
    _grub_set "$key" "${kept[*]}"
}

_is_enabled() {
    local cmdline
    cmdline=" $(_grub_value GRUB_CMDLINE_LINUX) $(_grub_value GRUB_CMDLINE_LINUX_DEFAULT) "
    cmdline="${cmdline//[[:space:]]/ }"
    [[ "$cmdline" == *" $PARAM "* ]]
}

_run_update_grub() {
    if [[ -n "$GRUB_UPDATE_OVERRIDE" ]]; then
        "$GRUB_UPDATE_OVERRIDE"
    elif command -v update-grub &>/dev/null; then
        update-grub
    elif command -v grub-mkconfig &>/dev/null; then
        grub-mkconfig -o /boot/grub/grub.cfg
    else
        echo "update-grub/grub-mkconfig not found" >&2
        return 1
    fi
}

if [ "$1" == "check" ]; then
    if _is_enabled; then
        echo "true"
    else
        echo "false"
    fi

elif [ "$1" == "toggle" ]; then
    state="$2"
    [[ "$state" == "true" || "$state" == "false" ]] || exit 2
    _require_root "$@"
    [[ -f "$GRUB_FILE" ]] || exit 1

    if [[ "$state" == "true" ]] && _is_enabled; then
        exit 0
    elif [[ "$state" == "false" ]] && ! _is_enabled; then
        exit 0
    fi

    backup="$(mktemp)" || exit 1
    trap 'rm -f "$backup"' EXIT
    cp -- "$GRUB_FILE" "$backup" || exit 1

    if [[ "$state" == "true" ]]; then
        _grub_edit GRUB_CMDLINE_LINUX_DEFAULT true
    else
        _grub_value GRUB_CMDLINE_LINUX_DEFAULT >/dev/null && _grub_edit GRUB_CMDLINE_LINUX_DEFAULT false
        _grub_value GRUB_CMDLINE_LINUX >/dev/null && _grub_edit GRUB_CMDLINE_LINUX false
    fi

    # Make sure the edit really did what was asked before regenerating
    # grub.cfg, and put the old file back if anything goes wrong.
    if [[ "$state" == "true" ]]; then _is_enabled; else ! _is_enabled; fi
    edited=$?
    if [[ $edited -ne 0 ]] || ! _run_update_grub; then
        cat "$backup" > "$GRUB_FILE"
        exit 1
    fi
    exit 0
fi
