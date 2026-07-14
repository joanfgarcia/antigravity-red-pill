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

if confirm "Desmantelar Bünker (Qdrant y Timers)?"; then
	systemctl --user stop qdrant.service redpill-pulse.timer redpill-telemetry.timer redpill-queue.timer || true
	systemctl --user disable qdrant.service redpill-pulse.timer redpill-telemetry.timer redpill-queue.timer || true
	rm -f "$HOME/.config/containers/systemd/qdrant.container"
	rm -f "$HOME/.config/systemd/user/redpill-"*".service"
	rm -f "$HOME/.config/systemd/user/redpill-"*".timer"
	systemctl --user daemon-reload
fi

if confirm "Borrar Identidad (~/.gemini/antigravity)?"; then
	rm -rf "$HOME/.gemini/antigravity"
fi

if confirm "Quitar el bloque red-pill (Sovereign Handshake/Agent_Core) de las anclas de IDE?"; then
	RP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
	if command -v uv &> /dev/null && [ -f "$RP_DIR/scripts/inject_anchor.py" ]; then
		(cd "$RP_DIR" && uv run python scripts/inject_anchor.py --remove --ide antigravity || true)
	else
		rm -f "$HOME/.gemini/GEMINI.md"
	fi
fi

if confirm "Borrado total ($IA_DIR)?"; then
	# Sentinel guard: refuse to rm -rf unless IA_DIR really is a red-pill install root.
	# Protects against ANTIGRAVITY_IA_DIR being empty/$HOME/'/'.
	if [ -f "$IA_DIR/red-pill/pyproject.toml" ] || [ -f "$IA_DIR/pyproject.toml" ]; then
		rm -rf "$IA_DIR"
	else
		echo -e "${RED}[ABORTADO] '$IA_DIR' no parece un install de red-pill (sin pyproject.toml centinela).${NC}"
		exit 1
	fi
fi
