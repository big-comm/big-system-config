#!/bin/bash
set -euo pipefail
# backlight.sh — Toggle the backlight handler in biglinux-sleep.
# Saves/restores screen brightness and keyboard LEDs on suspend.

# BIGLINUX_SLEEP_CONF only exists for the test suite and is ignored when
# running as root, so it can never redirect the privileged write.
CONF="/etc/biglinux/sleep.conf"
if [[ $EUID -ne 0 ]]; then
    CONF="${BIGLINUX_SLEEP_CONF:-$CONF}"
fi
KEY="backlight"

_require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        exec pkexec "$(readlink -f "$0")" "$@"
    fi
}

# Print the last value of $KEY inside [handlers], like configparser reads it:
# case-insensitive key, "=" or ":", spaces allowed, inline "#"/";" comments.
_read_value() {
    awk -v key="$KEY" '
        /^[[:space:]]*\[/ {
            line = $0
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            inSection = (line == "[handlers]")
            next
        }
        inSection {
            line = $0
            sub(/^[[:space:]]+/, "", line)
            split(line, parts, /[=:]/)
            name = parts[1]
            gsub(/[[:space:]]+$/, "", name)
            if (tolower(name) != key || line !~ /[=:]/) next
            value = substr(line, length(parts[1]) + 2)
            sub(/[[:space:]]+[#;].*$/, "", value)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            found = tolower(value)
        }
        END { print found }
    ' "$CONF" 2>/dev/null || true
}

# Rewrite $KEY inside [handlers] only, adding the key or the section if
# missing. Other sections and keys are copied unchanged.
_write_value() {
    local state="$1" temporary
    temporary="$(mktemp "$(dirname "$CONF")/.sleep.conf.XXXXXX")"
    trap 'rm -f "$temporary"' EXIT
    if [ -f "$CONF" ]; then
        cat "$CONF"
    fi | awk -v key="$KEY" -v state="$state" '
        function flush() {
            if (inSection && !written) { print key "=" state; written = 1 }
        }
        /^[[:space:]]*\[/ {
            line = $0
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            flush()
            inSection = (line == "[handlers]")
            if (inSection) seen = 1
            print
            next
        }
        inSection {
            line = $0
            sub(/^[[:space:]]+/, "", line)
            split(line, parts, /[=:]/)
            name = parts[1]
            gsub(/[[:space:]]+$/, "", name)
            if (line ~ /[=:]/ && tolower(name) == key) {
                if (!written) { print key "=" state; written = 1 }
                next
            }
        }
        { print }
        END {
            flush()
            if (!seen) { print "[handlers]"; print key "=" state }
        }
    ' > "$temporary"
    if [ -f "$CONF" ]; then
        chmod --reference="$CONF" "$temporary"
    else
        chmod 0644 "$temporary"
    fi
    mv -f "$temporary" "$CONF"
    trap - EXIT
}

if [ "${1:-}" == "check" ]; then
    case "$(_read_value)" in
        1 | yes | true | on) echo "true" ;;
        *) echo "false" ;;
    esac

elif [ "${1:-}" == "toggle" ]; then
    _require_root "$@"
    state="${2:-}"
    [[ "$state" == "true" || "$state" == "false" ]] || exit 2
    mkdir -p "$(dirname "$CONF")"
    # backlight.sh and wifi-d3cold.sh edit the same file: serialize them.
    # Lock the directory, which survives the atomic rename of the file.
    exec 9<"$(dirname "$CONF")"
    flock 9
    _write_value "$state"
else
    exit 2
fi
