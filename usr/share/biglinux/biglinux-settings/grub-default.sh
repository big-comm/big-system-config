# shellcheck shell=bash
# Shared by the scripts that read or edit /etc/default/grub. Source it; it
# defines functions and two variables, and runs nothing.

# BIGLINUX_GRUB_FILE and BIGLINUX_GRUB_UPDATE exist only for the test suite and
# are ignored when running as root, so they can never redirect a real edit or
# run a command with root privileges, whatever way the script is started.
grub_file="/etc/default/grub"
grub_update_override=""
grub_lock_file="/run/biglinux-settings-grub.lock"
if [[ $EUID -ne 0 ]]; then
  grub_file="${BIGLINUX_GRUB_FILE:-$grub_file}"
  grub_update_override="${BIGLINUX_GRUB_UPDATE:-}"
  grub_lock_file="$grub_file.lock"
fi

# Hold the edit lock until the script exits. Each edit reads the whole file and
# may restore a backup of it, which would undo an edit made in between. The lock
# file is created 0600 so no other user can hold it and stall the root helpers.
grub_lock() {
  local mask
  mask="$(umask)"
  umask 077
  exec {grub_lock_fd}>>"$grub_lock_file" || { umask "$mask"; return 1; }
  umask "$mask"
  flock "$grub_lock_fd"
}

# Print the value of the last active KEY= line (grub sources the file, so the
# last assignment wins). Commented lines are ignored; double, single and no
# quotes are accepted. Returns 1 when there is no such line.
grub_value() {
  local line value
  line="$(grep -E "^[[:space:]]*$1=" "$grub_file" 2>/dev/null | tail -n 1)"
  [[ -n "$line" ]] || return 1
  value="${line#*=}"
  case "$value" in
    \"*) value="${value#\"}"; value="${value%%\"*}" ;;
    \'*) value="${value#\'}"; value="${value%%\'*}" ;;
    *) value="${value%%[[:space:]]*}" ;;
  esac
  printf '%s\n' "$value"
}

# Count how many of the given tokens are on the kernel command line.
grub_count_tokens() {
  local words token count=0
  read -ra words <<< "$(grub_value GRUB_CMDLINE_LINUX) $(grub_value GRUB_CMDLINE_LINUX_DEFAULT)"
  for token in "$@"; do
    [[ " ${words[*]} " == *" $token "* ]] && count=$((count + 1))
  done
  printf '%s\n' "$count"
}

# Replace the grub file with the contents of FILE. The new file is written next
# to the target, flushed to disk and renamed over it, so neither an interrupted
# write nor a crash leaves a truncated file; a symlinked grub file keeps its
# link, owner and mode.
grub_write() {
  local target tmp
  target="$(readlink -f -- "$grub_file")" || return 1
  tmp="$(mktemp "${target%/*}/.grub.XXXXXX")" || return 1
  if cat -- "$1" > "$tmp" &&
    sync -- "$tmp" &&
    chmod --reference="$target" -- "$tmp" &&
    chown --reference="$target" -- "$tmp" &&
    mv -f -- "$tmp" "$target"; then
    return 0
  fi
  rm -f -- "$tmp"
  return 1
}

# Replace the last active KEY= line with LINE, or append LINE when the key is
# missing.
grub_replace_line() {
  local key="$1" line="$2" tmp rc
  tmp="$(mktemp)" || return 1
  if grep -qE "^[[:space:]]*$key=" "$grub_file"; then
    grub_line="$line" grub_key="$key" awk '
      { lines[NR] = $0 }
      $0 ~ "^[[:space:]]*" ENVIRON["grub_key"] "=" { last = NR }
      END { for (i = 1; i <= NR; i++) print (i == last ? ENVIRON["grub_line"] : lines[i]) }
    ' "$grub_file" > "$tmp"
  else
    (
      cat -- "$grub_file" || exit
      [[ -s "$grub_file" && -n "$(tail -c 1 "$grub_file")" ]] && echo
      printf '%s\n' "$line"
    ) > "$tmp"
  fi || { rm -f -- "$tmp"; return 1; }
  grub_write "$tmp"
  rc=$?
  rm -f -- "$tmp"
  return $rc
}

# Set KEY="value", keeping single quotes if the current line uses them.
grub_set() {
  local key="$1" value="$2" quote='"' line
  line="$(grep -E "^[[:space:]]*$key=" "$grub_file" | tail -n 1)"
  [[ "${line#*=}" == \'* ]] && quote="'"
  grub_replace_line "$key" "$key=$quote$value$quote"
}

# Add (enable) or remove (disable) kernel parameters and regenerate grub.cfg.
# The previous grub file comes back when the edit or the regeneration fails.
grub_toggle_tokens() {
  local action="$1" wanted key backup token word words kept edited=0
  shift
  case "$action" in
    enable) wanted=$# ;;
    disable) wanted=0 ;;
    *) echo "Usage: $0 enable|disable" >&2; return 2 ;;
  esac
  [[ -f "$grub_file" ]] || return 1
  grub_lock || return 1
  [[ "$(grub_count_tokens "$@")" == "$wanted" ]] && return 0

  backup="$(mktemp)" || return 1
  cp -- "$grub_file" "$backup" || { rm -f -- "$backup"; return 1; }

  if [[ "$action" == enable ]]; then
    key=GRUB_CMDLINE_LINUX_DEFAULT
    if ! grub_value "$key" > /dev/null && grub_value GRUB_CMDLINE_LINUX > /dev/null; then
      key=GRUB_CMDLINE_LINUX
    fi
    read -ra words <<< "$(grub_value "$key")"
    for token in "$@"; do
      [[ " ${words[*]} " == *" $token "* ]] || words+=("$token")
    done
    grub_set "$key" "${words[*]}" || edited=1
  else
    for key in GRUB_CMDLINE_LINUX_DEFAULT GRUB_CMDLINE_LINUX; do
      grub_value "$key" > /dev/null || continue
      read -ra words <<< "$(grub_value "$key")"
      kept=()
      for word in "${words[@]}"; do
        for token in "$@"; do
          [[ "$word" == "$token" ]] && continue 2
        done
        kept+=("$word")
      done
      grub_set "$key" "${kept[*]}" || edited=1
    done
  fi

  # Make sure the edit really did what was asked before regenerating grub.cfg.
  if (( edited )) || [[ "$(grub_count_tokens "$@")" != "$wanted" ]] || ! run_update_grub; then
    grub_write "$backup"
    rm -f -- "$backup"
    return 1
  fi
  rm -f -- "$backup"
}

run_update_grub() {
  if [[ -n "$grub_update_override" ]]; then
    "$grub_update_override"
  elif command -v update-grub &>/dev/null; then
    update-grub
  elif command -v grub-mkconfig &>/dev/null; then
    grub-mkconfig -o /boot/grub/grub.cfg
  else
    echo "update-grub/grub-mkconfig not found" >&2
    return 1
  fi
}
