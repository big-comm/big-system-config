#!/bin/bash

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# check current status
if [ "$1" == "check" ]; then
  if ([[ "$XDG_CURRENT_DESKTOP" == *"KDE"* ]] || [[ "$XDG_CURRENT_DESKTOP" == *"Plasma"* ]]) && command -v qdbus6 >/dev/null 2>&1;then
    if [[ -n "$(qdbus6 org.kde.KWin /Effects org.kde.kwin.Effects.loadedEffects)" ]]; then
      echo "false"
    else
      echo "true"
    fi
  else
    echo "unsupported"
  fi

# change the state
elif [ "$1" == "toggle" ]; then
  state="$2"
  exitCode=0
  if ([[ "$XDG_CURRENT_DESKTOP" == *"KDE"* ]] || [[ "$XDG_CURRENT_DESKTOP" == *"Plasma"* ]]) && command -v qdbus6 >/dev/null 2>&1;then
    if [ "$state" == "true" ]; then
      # qdbus6 prints one effect per line
      mapfile -t effects < <(qdbus6 org.kde.KWin /Effects org.kde.kwin.Effects.loadedEffects)
      # Nothing loaded: keep the list saved by the previous disable
      if [[ ${#effects[@]} -gt 0 ]]; then
        mkdir -p "$HOME/.config/biglinux-settings"
        printf '%s\n' "${effects[@]}" > "$HOME/.config/biglinux-settings/effectsEnable"
      fi
      for effect in "${effects[@]}"; do
        [[ -n "$effect" ]] || continue
        kwriteconfig6 --file kwinrc --group Plugins --key "${effect}Enabled" false || exitCode=1
        qdbus6 org.kde.KWin /Effects org.kde.kwin.Effects.unloadEffect "$effect" >/dev/null || exitCode=1
      done
    else
      effects=()
      if [[ -r "$HOME/.config/biglinux-settings/effectsEnable" ]]; then
        mapfile -t effects < "$HOME/.config/biglinux-settings/effectsEnable"
      fi
      for effect in "${effects[@]}"; do
        [[ -n "$effect" ]] || continue
        kwriteconfig6 --file kwinrc --group Plugins --key "${effect}Enabled" true || exitCode=1
        qdbus6 org.kde.KWin /Effects org.kde.kwin.Effects.loadEffect "$effect" >/dev/null || exitCode=1
      done
    fi
  else
    exitCode=1
  fi
  exit $exitCode
fi
