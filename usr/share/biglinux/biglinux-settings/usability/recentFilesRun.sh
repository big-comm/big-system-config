#!/bin/bash

#Translation
export TEXTDOMAINDIR="/usr/share/locale"
export TEXTDOMAIN=biglinux-settings

# Assign the received arguments to variables with clear names
function="$1"

# Configuration commands
balooCMD="balooctl6"
kwriteConfig="kwriteconfig6"

# Configuration files
xbelFile="$HOME/.local/share/recently-used.xbel"
xbelUserFile="$HOME/.local/share/user-places.xbel"
kactivitymanagerdFile="$HOME/.config/kactivitymanagerd-pluginsrc"
kactivitymanagerdDir="$HOME/.local/share/kactivitymanagerd/resources"

# Executes tasks.
updateTask() {
  if [[ "$function" == "enable" ]]; then
    # Respect the "Disable Baloo indexer" switch: only bring Baloo back if it was on
    balooWasEnabled=false
    $balooCMD status > /dev/null 2>&1 && balooWasEnabled=true
    $balooCMD suspend > /dev/null 2>&1
    $balooCMD disable > /dev/null 2>&1
    killall baloo_file dolphin kactivitymanagerd kioworker kiod6 > /dev/null 2>&1
    systemctl --user stop plasma-kactivitymanagerd.service > /dev/null 2>&1

    # Remove off-the-record activities line
    sed -i '/off-the-record-activities/d' "$kactivitymanagerdFile"

    # Configure activity tracking
    $kwriteConfig --file kactivitymanagerd-pluginsrc --group "Plugin-org.kde.ActivityManager.Resources.Scoring" --key "what-to-remember" "0"
    $kwriteConfig --file kactivitymanagerd-pluginsrc --group "Plugin-org.kde.ActivityManager.Resources.Scoring" --key "enabled" "true"

    # Configure recent documents
    $kwriteConfig --file kdeglobals --group RecentDocuments --key UseRecent true
    $kwriteConfig --file kdeglobals --group RecentDocuments --key MaxEntries 50

    # Configure kioslave for recent files
    $kwriteConfig --file kioslaverc --group "recentlyused" --key "MaxItems" "100"
    $kwriteConfig --file kioslaverc --group "recentlyused" --key "LocationsEnabled" "true"
    $kwriteConfig --file kioslaverc --group "recentlyused" --key "FilesEnabled" "true"

    # Clear and recreate database
    rm -rf "$kactivitymanagerdDir"
    mkdir -p "$kactivitymanagerdDir"

    # Recreate recently-used.xbel
    [ -f "$xbelFile" ] && cp "$xbelFile" "$xbelFile.bak"
    echo '<?xml version="1.0" encoding="UTF-8"?>
  <xbel version="1.0"
  xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks"
  xmlns:mime="http://www.freedesktop.org/standards/shared-mime-info">
  </xbel>' > "$xbelFile"

    # unHide Recents
   sed -i 's/<GroupState-RecentlySaved-IsHidden>true<\/GroupState-RecentlySaved-IsHidden>/<GroupState-RecentlySaved-IsHidden>false<\/GroupState-RecentlySaved-IsHidden>/' "$xbelUserFile"

    chmod 644 "$xbelFile"

    # Restart services
    systemctl --user start plasma-kactivitymanagerd.service > /dev/null 2>&1
    sleep 2

    if [[ "$balooWasEnabled" == "true" ]]; then
      $balooCMD enable > /dev/null 2>&1
      $balooCMD resume > /dev/null 2>&1
    fi

    systemctl --user restart plasma-kactivitymanagerd.service > /dev/null 2>&1
    killall kiod6 > /dev/null 2>&1

    sleep 1
  else
    # Stop services
    killall dolphin kactivitymanagerd kioworker kiod6 > /dev/null 2>&1
    systemctl --user stop plasma-kactivitymanagerd.service > /dev/null 2>&1

    # Disable activity tracking
    $kwriteConfig --file kactivitymanagerd-pluginsrc --group "Plugin-org.kde.ActivityManager.Resources.Scoring" --key "what-to-remember" "2"
    $kwriteConfig --file kactivitymanagerd-pluginsrc --group "Plugin-org.kde.ActivityManager.Resources.Scoring" --key "enabled" "false"

    # Disable recent documents
    $kwriteConfig --file kdeglobals --group RecentDocuments --key UseRecent false

    # Disable kioslave for recent files
    $kwriteConfig --file kioslaverc --group "recentlyused" --key "LocationsEnabled" "false"
    $kwriteConfig --file kioslaverc --group "recentlyused" --key "FilesEnabled" "false"

    # Clear database
    rm -rf "$kactivitymanagerdDir"

    # Clear recently-used.xbel
    echo '<?xml version="1.0" encoding="UTF-8"?>
  <xbel version="1.0"
    xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks"
    xmlns:mime="http://www.freedesktop.org/standards/shared-mime-info">
  </xbel>' > "$xbelFile"

    # Hide recents
    sed -i 's/<GroupState-RecentlySaved-IsHidden>false<\/GroupState-RecentlySaved-IsHidden>/<GroupState-RecentlySaved-IsHidden>true<\/GroupState-RecentlySaved-IsHidden>/' "$xbelUserFile"

    chmod 644 "$xbelFile"

    # Restart services
    systemctl --user start plasma-kactivitymanagerd.service > /dev/null 2>&1
    killall kiod6 > /dev/null 2>&1

    sleep 1
  fi
  return 0
}
updateTask

exitCode=$?

# Exits the script with the correct exit code
exit $exitCode
