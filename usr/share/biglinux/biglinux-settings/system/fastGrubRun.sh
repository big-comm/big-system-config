#!/bin/bash

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# Assign the received arguments to variables with clear names
timeout="$1"

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

# Print the value of the last active GRUB_TIMEOUT= line, without quotes
current_timeout() {
  local value
  value="$(grep -E '^[[:space:]]*GRUB_TIMEOUT=' "$grub_file" 2>/dev/null | tail -n 1)"
  value="${value#*=}"
  printf '%s\n' "${value//[\"\'[:space:]]/}"
}

# Executes the root tasks.
updateGrubTask() {
  local backup tmp
  if [[ ! "$timeout" =~ ^[0-9]+$ ]]; then
    echo "Usage: $0 <timeout in seconds>" >&2
    return 2
  fi
  [[ -f "$grub_file" ]] || return 1
  [[ "$(current_timeout)" == "$timeout" ]] && return 0

  backup="$(mktemp)" || return 1
  cp -- "$grub_file" "$backup" || { rm -f "$backup"; return 1; }

  # Replace the last active GRUB_TIMEOUT= line, or append one
  tmp="$(mktemp)" || { rm -f "$backup"; return 1; }
  if grep -qE '^[[:space:]]*GRUB_TIMEOUT=' "$grub_file"; then
    grub_line="GRUB_TIMEOUT=$timeout" awk '
      { lines[NR] = $0 }
      /^[[:space:]]*GRUB_TIMEOUT=/ { last = NR }
      END { for (i = 1; i <= NR; i++) print (i == last ? ENVIRON["grub_line"] : lines[i]) }
    ' "$grub_file" > "$tmp"
  else
    { cat "$grub_file"; [[ -s "$grub_file" && -n "$(tail -c 1 "$grub_file")" ]] && echo
      echo "GRUB_TIMEOUT=$timeout"; } > "$tmp"
  fi
  # Write through the existing file to keep its permissions and symlinks
  cat "$tmp" > "$grub_file"
  rm -f "$tmp"

  # Make sure the edit really did what was asked before regenerating grub.cfg,
  # and put the old file back if anything goes wrong.
  if [[ "$(current_timeout)" != "$timeout" ]] || ! run_update_grub; then
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
