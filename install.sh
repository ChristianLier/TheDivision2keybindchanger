#!/usr/bin/env bash
# Installs Division 2 Keybinder for the current user (no sudo needed unless
# GTK bindings are missing). Run:  ./install.sh      or  ./install.sh --uninstall
set -euo pipefail

APP_DIR="$HOME/.local/share/division2-keybinder"
BIN="$HOME/.local/bin/division2-keybinder"
DESKTOP="$HOME/.local/share/applications/division2-keybinder.desktop"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$BIN" "$DESKTOP"
    rm -rf "$APP_DIR"
    echo "Removed. Your profiles and backups are kept in ~/.config/division2-keybinder"
    exit 0
fi

if ! python3 -c 'import gi; gi.require_version("Gtk","3.0"); from gi.repository import Gtk' 2>/dev/null; then
    echo "GTK3 Python bindings are missing. Installing python3-gi and gir1.2-gtk-3.0 (needs sudo)…"
    sudo apt install -y python3-gi gir1.2-gtk-3.0
fi

mkdir -p "$APP_DIR" "$(dirname "$BIN")" "$(dirname "$DESKTOP")"
install -m 755 "$SRC/division2_keybinder.py" "$APP_DIR/division2_keybinder.py"

cat > "$BIN" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/division2_keybinder.py" "\$@"
EOF
chmod 755 "$BIN"

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Division 2 Keybinder
Comment=Edit The Division 2 key bindings (Steam / Proton)
Exec="$BIN"
Icon=input-keyboard
Terminal=false
Categories=Game;Utility;
Keywords=division;keybind;keyboard;steam;proton;
EOF

command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESKTOP")" || true
echo "Installed. Find “Division 2 Keybinder” in the Mint menu, or run: division2-keybinder"
