#!/usr/bin/env bash
# Dev helper: make sure Steam's QAM is open, go to the Decky tab, open "Eden Settings" and take a screenshot
# ($1, default /tmp/qam.png). Needs Game Mode with Steam's CEF debugging port on 8080.
set -euo pipefail
T="$(dirname "$0")/cdp.py"
W=$(python3 "$T" eval QuickAccess 'document.body.innerText.length>0?500:0' | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["value"])')
if [ "$W" -lt 100 ]; then
  python3 "$T" eval SharedJSContext 'SteamUIStore.m_WindowStore.GamepadUIMainWindowInstance.OnQuickAccessButtonPressed(); "ok"' >/dev/null
  sleep 2
fi
python3 "$T" click QuickAccess 84 37; sleep 1                  # back arrow, in case a plugin is already open
python3 "$T" click QuickAccess 23 576; sleep 1          # the plug icon (Decky tab) in the QAM tab bar
python3 "$T" clicktext QuickAccess "Eden Settings" || true; sleep 2
python3 "$T" shot QuickAccess "${1:-/tmp/qam.png}"
