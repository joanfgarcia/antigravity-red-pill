#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IA_DIR="${ANTIGRAVITY_IA_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

confirm() {
	read -p "$1 (s/n): " choice
	[[ "$choice" =~ ^[Ss]$ ]]
}

if confirm "Backup premortem?"; then
	if command -v uv &> /dev/null; then
		(cd "$IA_DIR/sharing" && uv run red-pill soul backup)
	fi
fi

if confirm "Desmantelar Qdrant?"; then
	systemctl --user stop qdrant.service || true
	rm -f "$HOME/.config/containers/systemd/qdrant.container"
	systemctl --user daemon-reload
fi

if confirm "Borrar Identidad (~/.gemini/antigravity)?"; then
	rm -rf "$HOME/.gemini/antigravity"
fi

if confirm "Borrar Reglas Globales (~/.gemini/GEMINI.md)?"; then
	rm -f "$HOME/.gemini/GEMINI.md"
fi

if confirm "Borrado total ($IA_DIR)?"; then
	rm -rf "$IA_DIR"
fi
