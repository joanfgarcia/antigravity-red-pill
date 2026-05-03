#!/bin/bash
set -euo pipefail

# 🛰️ Red Pill Sovereign Upgrade Tool (v6.8.0)
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
if [ -f ".env" ]; then
	set -a
	source .env
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
	
	# Reinstall timers (handles storage/queue creation and path changes)
	uv run python scripts/schedule_pulse.py --interval-hours 1
	
	# Thread Weaving (idempotent)
	uv run python scripts/thread_weave_migrate.py
	
	# Version Sync Engram (Manual prompt for now, but ensured by guidance)
	echo -e "${GREEN}✓ Estructura interna actualizada.${NC}"
else
	echo -e "${RED}[ERROR] 'uv' no encontrado. Por favor, instala astral/uv para completar el upgrade.${NC}"
fi

echo -e "\n${GREEN}Upgrade Finalizado con éxito.${NC}"
echo -e "Por favor, ${YELLOW}reinicia tu Servidor MCP${NC} en el IDE para cargar los nuevos módulos v6.8.0."
echo -e "${BLUE}------------------------------------------------------------------${NC}"
