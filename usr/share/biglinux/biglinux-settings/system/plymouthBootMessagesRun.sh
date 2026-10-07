#!/bin/bash

state="$1"
configDir="/etc/biglinux"
themeScript="/usr/share/plymouth/themes/community/animated-boot.script"
presetsDir="/etc/mkinitcpio.d"
mkinitcpioConf="/etc/mkinitcpio.conf"
# Test-only overrides, ignored when running as root
if [[ $EUID -ne 0 ]]; then
  configDir="${BIGLINUX_PLYMOUTH_CONFIG_DIR:-$configDir}"
  themeScript="${BIGLINUX_PLYMOUTH_THEME_SCRIPT:-$themeScript}"
  presetsDir="${BIGLINUX_MKINITCPIO_PRESETS:-$presetsDir}"
  mkinitcpioConf="${BIGLINUX_MKINITCPIO_CONF:-$mkinitcpioConf}"
fi
configFile="$configDir/plymouth-community.conf"

_remove_missing_initcpio_hook() {
  local missing_hook="$1"
  local conf="$mkinitcpioConf"
  local hooks_line hooks hook_item found new_hooks

  if [ ! -f "$conf" ]; then
    return 0
  fi

  if [ -e "/usr/lib/initcpio/hooks/$missing_hook" ] || [ -e "/usr/lib/initcpio/install/$missing_hook" ]; then
    return 0
  fi

  hooks_line="$(grep -E '^[[:space:]]*HOOKS=\(' "$conf" | tail -n1)"
  if [ -z "$hooks_line" ]; then
    return 0
  fi

  hooks="${hooks_line#*\(}"
  hooks="${hooks%\)*}"
  found=0
  new_hooks=()

  for hook_item in $hooks; do
    if [ "$hook_item" = "$missing_hook" ]; then
      found=1
      continue
    fi
    new_hooks+=("$hook_item")
  done

  if [ "$found" -eq 0 ]; then
    return 0
  fi

  cp -a -- "$conf" "${conf}.biglinux-settings.bak"
  sed --follow-symlinks -i \
    "s|^[[:space:]]*HOOKS=.*|HOOKS=(${new_hooks[*]})|" \
    "$conf"
  printf 'Removed missing mkinitcpio hook from %s: %s\n' "$conf" "$missing_hook" >&2
}

# The boot splash runs from the initramfs, which carries its own copy of the
# theme script: check that the copy in the image matches the edited one.
_initramfs_has_current_theme() {
  local image="$1" tmp inner rc=0
  command -v lsinitcpio >/dev/null 2>&1 || return 0
  [ -f "$themeScript" ] && [ -f "$image" ] || return 0
  tmp="$(mktemp -d)" || return 0
  (cd "$tmp" && lsinitcpio -x "$image" >/dev/null 2>&1)
  inner="$tmp/usr/share/plymouth/themes/community/animated-boot.script"
  # An image without the theme has no splash to show messages on
  if [ -f "$inner" ] && ! cmp -s "$inner" "$themeScript"; then
    rc=1
  fi
  rm -rf -- "$tmp"
  return "$rc"
}

# Rebuild the initramfs of EVERY installed kernel: each one boots with its own
# copy of the theme, so a single stale image brings the messages back when
# that kernel is chosen. Any failure is reported, naming the kernels.
_rebuild_initramfs() {
  if ! command -v mkinitcpio >/dev/null 2>&1; then
    return 0
  fi

  local preset preset_name kver image
  local presets=() failed=()

  shopt -s nullglob
  presets=("$presetsDir"/*.preset)
  shopt -u nullglob

  if [ "${#presets[@]}" -eq 0 ]; then
    mkinitcpio -P
    return $?
  fi

  for preset in "${presets[@]}"; do
    preset_name="$(basename "$preset" .preset)"
    kver="$(
      unset ALL_kver default_kver
      # shellcheck disable=SC1090
      . "$preset" 2>/dev/null
      printf '%s' "${default_kver:-$ALL_kver}"
    )"
    image="$(
      unset default_image
      # shellcheck disable=SC1090
      . "$preset" 2>/dev/null
      # shellcheck disable=SC2154  # set by the preset
      printf '%s' "$default_image"
    )"

    if [ -n "$kver" ] && [ ! -r "$kver" ]; then
      # Leftover preset of a removed kernel: nothing boots from it
      printf 'Skipping mkinitcpio preset %s: kernel image is not readable: %s\n' "$preset_name" "$kver" >&2
      continue
    fi

    if ! mkinitcpio -p "$preset_name"; then
      failed+=("$preset_name")
    elif [ -n "$image" ] && ! _initramfs_has_current_theme "$image"; then
      failed+=("$preset_name (boot splash theme not updated)")
    fi
  done

  if [ "${#failed[@]}" -gt 0 ]; then
    printf 'Could not update the boot splash for: %s\n' "${failed[*]}" >&2
    return 1
  fi
  return 0
}

if [ "$state" != "true" ] && [ "$state" != "false" ]; then
  exit 1
fi

mkdir -p "$configDir"

if [ -f "$configFile" ]; then
  if grep -qE '^[[:space:]]*SHOW_BOOT_MESSAGES[[:space:]]*=' "$configFile"; then
    sed -i "s/^[[:space:]]*SHOW_BOOT_MESSAGES[[:space:]]*=.*/SHOW_BOOT_MESSAGES=$state/" "$configFile"
  else
    printf '\nSHOW_BOOT_MESSAGES=%s\n' "$state" >> "$configFile"
  fi
else
  {
    printf '# BigCommunity Plymouth settings\n'
    printf 'SHOW_BOOT_MESSAGES=%s\n' "$state"
  } > "$configFile"
fi

chmod 0644 "$configFile"

if [ -f "$themeScript" ]; then
  if [ "$state" == "true" ]; then
    sed -i \
      -e 's|^[[:space:]]*#[[:space:]]*\(Plymouth\.SetDisplayMessageFunction.*\)|\1|' \
      -e 's|^[[:space:]]*#[[:space:]]*\(Plymouth\.SetHideMessageFunction.*\)|\1|' \
      -e 's|^[[:space:]]*#[[:space:]]*\(Plymouth\.SetUpdateStatusFunction.*\)|\1|' \
      "$themeScript"
  else
    sed -i \
      -e 's|^[[:space:]]*\(Plymouth\.SetDisplayMessageFunction.*\)|# \1|' \
      -e 's|^[[:space:]]*\(Plymouth\.SetHideMessageFunction.*\)|# \1|' \
      -e 's|^[[:space:]]*\(Plymouth\.SetUpdateStatusFunction.*\)|# \1|' \
      "$themeScript"
  fi
fi

if command -v plymouth-set-default-theme >/dev/null 2>&1; then
  _remove_missing_initcpio_hook "bootsplash-biglinux"
  plymouth-set-default-theme community && _rebuild_initramfs
  exit $?
elif command -v mkinitcpio >/dev/null 2>&1; then
  _remove_missing_initcpio_hook "bootsplash-biglinux"
  _rebuild_initramfs
  exit $?
fi
