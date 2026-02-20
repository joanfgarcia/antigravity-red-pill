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
	[ -f "$IA_DIR/scripts/backup_soul.sh" ] && bash "$IA_DIR/scripts/backup_soul.sh"
fi

if confirm "Desmantelar Qdrant?"; then
	systemctl --user stop qdrant.service || true
	rm -f "$HOME/.config/containers/systemd/qdrant.container"
	systemctl --user daemon-reload
fi

if confirm "Borrar Identidad (~/.gemini/antigravity)?"; then
	rm -rf "$HOME/.gemini/antigravity"
fi

if confirm "Borrar Sincronización (~/.agent/rules/identity_sync.md)?"; then
	rm -f "$HOME/.agent/rules/identity_sync.md"
fi

if confirm "Borrado total ($IA_DIR)?"; then
	rm -rf "$IA_DIR"
fi
