#!/bin/bash

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# Assign the received arguments to variables with clear names
function="$1"
parameters=(mitigations=off)

# BIGLINUX_GRUB_FILE and BIGLINUX_GRUB_UPDATE exist only for the test suite and
# are ignored when running as root, so they can never redirect a real edit or
# run a command with root privileges, whatever way the script is started.
grub_file="/etc/default/grub"
grub_update_override=""
if [[ $EUID -ne 0 ]]; then
  grub_file="${BIGLINUX_GRUB_FILE:-$grub_file}"
  grub_update_override="${BIGLINUX_GRUB_UPDATE:-}"
fi

run_update_grub() {
  if [[ -n "$grub_update_override" ]];then
    "$grub_update_override"
  elif [[ -e "/usr/bin/update-grub" ]];then
    /usr/bin/update-grub
  elif [[ -e "/usr/sbin/update-grub" ]];then
    /usr/sbin/update-grub
  elif [[ -e "/usr/bin/grub-mkconfig" ]];then
    /usr/bin/grub-mkconfig -o /boot/grub/grub.cfg
  elif [[ -e "/usr/sbin/grub-mkconfig" ]];then
    /usr/sbin/grub-mkconfig -o /boot/grub/grub.cfg
  elif [[ -e "/usr/bin/grub2-mkconfig" ]];then
    /usr/bin/grub2-mkconfig -o /boot/grub2/grub.cfg
  elif [[ -e "/usr/sbin/grub2-mkconfig" ]];then
    /usr/sbin/grub2-mkconfig -o /boot/grub2/grub.cfg
  else
    return 1
  fi
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

# Replace the last active KEY= line with KEY="value" (keeping single quotes if
# they were used), or append the line when the key is missing.
grub_set() {
  local key="$1" value="$2" quote='"' line tmp
  line="$(grep -E "^[[:space:]]*$key=" "$grub_file" | tail -n 1)"
  [[ "${line#*=}" == \'* ]] && quote="'"
  tmp="$(mktemp)" || return 1
  if [[ -n "$line" ]]; then
    grub_line="$key=$quote$value$quote" grub_key="$key" awk '
      { lines[NR] = $0 }
      $0 ~ "^[[:space:]]*" ENVIRON["grub_key"] "=" { last = NR }
      END { for (i = 1; i <= NR; i++) print (i == last ? ENVIRON["grub_line"] : lines[i]) }
    ' "$grub_file" > "$tmp"
  else
    { cat "$grub_file"; [[ -s "$grub_file" && -n "$(tail -c 1 "$grub_file")" ]] && echo
      printf '%s=%s%s%s\n' "$key" "$quote" "$value" "$quote"; } > "$tmp"
  fi
  # Write through the existing file to keep its permissions and symlinks
  cat "$tmp" > "$grub_file"
  local rc=$?
  rm -f "$tmp"
  return $rc
}

# Add tokens that are missing, keeping the others untouched
add_tokens() {
  local key="$1" token words
  shift
  read -ra words <<< "$(grub_value "$key")"
  for token in "$@"; do
    [[ " ${words[*]} " == *" $token "* ]] || words+=("$token")
  done
  grub_set "$key" "${words[*]}"
}

# Remove every occurrence of each token, wherever it is
remove_tokens() {
  local key="$1" token word words kept=()
  shift
  grub_value "$key" > /dev/null || return 0
  read -ra words <<< "$(grub_value "$key")"
  for word in "${words[@]}"; do
    for token in "$@"; do
      [[ "$word" == "$token" ]] && continue 2
    done
    kept+=("$word")
  done
  grub_set "$key" "${kept[*]}"
}

# Count how many of the tokens are in the kernel command line
count_tokens() {
  local words token count=0
  read -ra words <<< "$(grub_value GRUB_CMDLINE_LINUX) $(grub_value GRUB_CMDLINE_LINUX_DEFAULT)"
  for token in "$@"; do
    [[ " ${words[*]} " == *" $token "* ]] && count=$((count + 1))
  done
  echo "$count"
}

# Executes the root tasks.
updateGrubTask() {
  local wanted backup
  case "$function" in
    enable) wanted=${#parameters[@]} ;;
    disable) wanted=0 ;;
    *) echo "Usage: $0 enable|disable" >&2; return 2 ;;
  esac
  [[ -f "$grub_file" ]] || return 1

  if [[ "$(count_tokens "${parameters[@]}")" == "$wanted" ]]; then
    if [[ "$function" == "enable" ]]; then
      gettext "Already enabled. No changes made."
      echo
    fi
    return 0
  fi

  backup="$(mktemp)" || return 1
  cp -- "$grub_file" "$backup" || { rm -f "$backup"; return 1; }

  if [[ "$function" == "enable" ]]; then
    if grub_value GRUB_CMDLINE_LINUX_DEFAULT > /dev/null; then
      add_tokens GRUB_CMDLINE_LINUX_DEFAULT "${parameters[@]}"
    elif grub_value GRUB_CMDLINE_LINUX > /dev/null; then
      add_tokens GRUB_CMDLINE_LINUX "${parameters[@]}"
    else
      add_tokens GRUB_CMDLINE_LINUX_DEFAULT "${parameters[@]}"
    fi
  else
    remove_tokens GRUB_CMDLINE_LINUX_DEFAULT "${parameters[@]}"
    remove_tokens GRUB_CMDLINE_LINUX "${parameters[@]}"
  fi

  # Make sure the edit really did what was asked before regenerating grub.cfg,
  # and put the old file back if anything goes wrong.
  if [[ "$(count_tokens "${parameters[@]}")" != "$wanted" ]] || ! run_update_grub; then
    cat "$backup" > "$grub_file"
    rm -f "$backup"
    return 1
  fi
  rm -f "$backup"
}
updateGrubTask
exitCode=$?

# Exits the script with the correct exit code
exit $exitCode
