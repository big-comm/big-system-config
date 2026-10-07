#!/bin/bash
set -euo pipefail

action="${1:-}"
dropInDir="/etc/UPower/UPower.conf.d"
dropInFile="$dropInDir/90-biglinux-suspend-at-20.conf"

if [[ ! -x /usr/lib/upowerd && ! -x /usr/libexec/upowerd ]]; then
  echo "UPower is not installed" >&2
  exit 1
fi

case "$action" in
  enable)
    install -d -m 0755 "$dropInDir"
    temporary="$(mktemp "$dropInDir/.90-biglinux-suspend-at-20.XXXXXX")"
    trap 'rm -f "$temporary"' EXIT
    printf '%s\n' \
      '[UPower]' \
      'UsePercentageForPolicy=true' \
      'PercentageLow=25' \
      'PercentageCritical=22' \
      'PercentageAction=20' \
      'CriticalPowerAction=Suspend' \
      'AllowRiskyCriticalPowerAction=true' > "$temporary"
    chmod 0644 "$temporary"
    mv -f "$temporary" "$dropInFile"
    trap - EXIT
    ;;
  disable)
    rm -f "$dropInFile"
    ;;
  *)
    echo "Invalid action: $action" >&2
    exit 2
    ;;
esac

if ! systemctl try-restart upower.service; then
  if [[ "$action" == "enable" ]]; then
    rm -f "$dropInFile"
    exit 1
  fi
  # The drop-in is already gone, so the policy is off for UPower's next start;
  # reporting failure here would leave the caller's idle policy half-restored.
  echo "Warning: could not restart upower.service; the change applies on its next start" >&2
fi
