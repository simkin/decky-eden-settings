#!/usr/bin/env bash
# Dev helper: build (in the fedora distrobox) and copy the plugin into Decky's plugin folder, then restart Decky.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${DEST:-$HOME/homebrew/plugins/EdenSettings}"
if [ "${NO_BUILD:-}" != 1 ]; then distrobox enter fedora -- bash -lc "cd '$SRC' && pnpm build"; fi
sudo -n mkdir -p "$DEST"
sudo -n rm -rf "$DEST/dist" "$DEST/py_modules" "$DEST/main.py"
sudo -n cp -r "$SRC/dist" "$SRC/py_modules" "$SRC/main.py" "$SRC/plugin.json" "$SRC/package.json" "$SRC/LICENSE" "$DEST/"
sudo -n find "$DEST" -name __pycache__ -prune -exec rm -rf {} +
sudo -n systemctl restart plugin_loader
