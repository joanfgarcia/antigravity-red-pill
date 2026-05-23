#!/bin/bash
set -euo pipefail

# 🛰️ Red Pill Sovereign Upgrade Tool (v7.1.0)
# This script automates the synchronization and migration of the Bünker.

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo -e "${BLUE}--- Iniciando Sincronización Soberana (Upgrade) ---${NC}"

cd "$REPO_ROOT"

# 1. Code Sync
if [ -d ".git" ]; then
	echo -e "${YELLOW}Detectado repositorio Git. Sincronizando con el origen...${NC}"
	git fetch origin
	# Check current branch
	CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
	echo -e "Rama actual: ${GREEN}$CURRENT_BRANCH${NC}"
	
	# Ask for confirmation before pull if NOT in auto mode
	AUTO_MODE=false
	if [[ "${1:-}" == "--auto" ]]; then AUTO_MODE=true; fi
	
	if [ "$AUTO_MODE" = "false" ]; then
		read -p "¿Deseas ejecutar 'git pull' ahora? (y/N): " SHOULD_PULL
		if [[ "$SHOULD_PULL" =~ ^[Yy]$ ]]; then
			git pull origin "$CURRENT_BRANCH"
		fi
	else
		git pull origin "$CURRENT_BRANCH"
	fi
else
	echo -e "${BLUE}[INFO] No se detectó repositorio Git. Omitiendo sync de código.${NC}"
fi

# 2. WORKSPACE_ROOT & Environment Check
if [ -f "$HOME/.config/red-pill/.env" ]; then
	set -a
	source "$HOME/.config/red-pill/.env"
	set +a
	if [[ "${WORKSPACE_ROOT:-}" == "~"* ]]; then
		WORKSPACE_ROOT="${WORKSPACE_ROOT/#\~/$HOME}"
	fi
fi

# 3. Rogue Tilde Cleanup
if [ -d "$REPO_ROOT/~" ]; then
	echo -e "${YELLOW}Detectado árbol ~/ literal en el repo (Bug v6.3.3). Limpiando...${NC}"
	rm -rf "$REPO_ROOT/~"
	echo -e "${GREEN}✓ Directorio espurio ~/ eliminado.${NC}"
fi

# 4. Dependency & Migration ignition
if command -v uv &> /dev/null; then
	echo -e "${BLUE}Igniciando migración de datos y timers...${NC}"
	
	# Sanitize engrams
	uv run red-pill sanitize --dry-run || true
	
	# Reinstall timers (handles XDG data dir creation and path changes)
	uv run python scripts/schedule_pulse.py --interval-hours 1
	
	# Thread Weaving (idempotent)
	uv run python scripts/thread_weave_migrate.py
	
	# Version Sync Engram (Manual prompt for now, but ensured by guidance)
	echo -e "${GREEN}✓ Estructura interna actualizada.${NC}"

	# Sync skills to ~/.agent/skills/ and re-symlink to IDE
	AGENT_DIR="${HOME}/.agent"
	GEMINI_SKILLS="${HOME}/.gemini/antigravity/skills"
	if [ -d "$REPO_ROOT/skills" ]; then
		echo -e "${BLUE}Sincronizando Skills soberanos (IDE-Agnostic)...${NC}"
		mkdir -p "$AGENT_DIR/skills"
		for skill_dir in "$REPO_ROOT/skills/"*/; do
			skill_name=$(basename "$skill_dir")
			[[ "$skill_name" == "memory_manager_template" ]] && continue
			cp -r "$skill_dir" "$AGENT_DIR/skills/$skill_name"
			if [ -d "$GEMINI_SKILLS" ]; then
				rm -rf "$GEMINI_SKILLS/$skill_name" 2>/dev/null || true
				ln -s "$AGENT_DIR/skills/$skill_name" "$GEMINI_SKILLS/$skill_name"
			fi
		done
		echo -e "${GREEN}✓ Skills sincronizados en ~/.agent/skills/.${NC}"
	fi

	# 5. Neon-Link Service Migration (v0.4.0 watchdog)
	# Restart neon-link to pick up sd_notify/WatchdogSec changes
	if systemctl --user is-active neon-link.service &>/dev/null; then
		echo -e "${BLUE}Reiniciando Neon-Link (v0.4.0 watchdog migration)...${NC}"
		systemctl --user restart neon-link.service
		echo -e "${GREEN}✓ Neon-Link reiniciado con WatchdogSec habilitado.${NC}"
	fi

	# 6. Detect and disable legacy neon-link services
	for LEGACY_SVC in redpill-neonlink.service; do
		if systemctl --user is-enabled "$LEGACY_SVC" &>/dev/null; then
			echo -e "${YELLOW}Deshabilitando servicio legacy: $LEGACY_SVC${NC}"
			systemctl --user stop "$LEGACY_SVC" 2>/dev/null || true
			systemctl --user disable "$LEGACY_SVC" 2>/dev/null || true
			echo -e "${GREEN}✓ $LEGACY_SVC deshabilitado.${NC}"
		fi
	done
else
	echo -e "${RED}[ERROR] 'uv' no encontrado. Por favor, instala astral/uv para completar el upgrade.${NC}"
fi

echo -e "\n${GREEN}Upgrade Finalizado con éxito.${NC}"
echo -e "Por favor, ${YELLOW}reinicia tu Servidor MCP${NC} en el IDE para cargar los nuevos módulos v7.1.0."
echo -e "${BLUE}------------------------------------------------------------------${NC}"
