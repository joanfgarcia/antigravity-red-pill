#!/usr/bin/env bash
# Instala las unidades de usuario de Forge/Loom en ~/.config/systemd/user.
# No las habilita por defecto: usa --enable para arrancarlas al login.
set -euo pipefail

ROOT="${REDPILL_DIR:-$HOME/Documents/IA/sharing}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
ENABLE=0
for arg in "$@"; do
	[ "$arg" = "--enable" ] && ENABLE=1
done

for unit in redpill-forge.service redpill-loom.service; do
	install -D -m 0644 "$ROOT/systemd/$unit" "$UNIT_DIR/$unit"
	echo "[OK] instalada $UNIT_DIR/$unit"
done

systemctl --user daemon-reload
if [ "$ENABLE" = "1" ]; then
	systemctl --user enable --now redpill-forge.service redpill-loom.service
	echo "[OK] Forge/Loom habilitados"
else
	echo "[i] no habilitados; arranca con: systemctl --user start redpill-forge redpill-loom"
fi
