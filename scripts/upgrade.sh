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

function print_help {
	echo -e "${BLUE}🛰️ Red Pill Sovereign Upgrade Tool${NC}"
	echo -e "Uso: ./scripts/upgrade.sh --mode <dev|user> [opciones]"
	echo -e ""
	echo -e "Opciones:"
	echo -e "  ${GREEN}--mode dev${NC}           Actualización vía git pull origin (Perfil Core / Developer)"
	echo -e "  ${GREEN}--mode user${NC}          Actualización vía ZIP local y rsync (Perfil Titanium / Morpheus)"
	echo -e "  ${GREEN}--zip <path>${NC}         Ruta absoluta o relativa al archivo .zip (requerido si --mode user)"
	echo -e "  ${GREEN}--auto${NC}               Omitir confirmaciones interactivas"
	echo -e "  ${GREEN}--help${NC}               Mostrar esta ayuda"
	echo -e ""
}

MODE=""
ZIP_PATH=""
AUTO_MODE=false

while [[ "$#" -gt 0 ]]; do
	case $1 in
		--mode)
			if [[ -z "${2:-}" ]]; then
				echo -e "${RED}[ERROR] Falta el argumento para --mode${NC}"
				exit 1
			fi
			MODE="$2"
			shift
			;;
		--zip)
			if [[ -z "${2:-}" ]]; then
				echo -e "${RED}[ERROR] Falta el argumento para --zip${NC}"
				exit 1
			fi
			ZIP_PATH="$2"
			shift
			;;
		--auto)
			AUTO_MODE=true
			;;
		--help|-h)
			print_help
			exit 0
			;;
		*)
			echo -e "${RED}Parámetro desconocido: $1${NC}"
			print_help
			exit 1
			;;
	esac
	shift
done

if [[ -z "$MODE" ]]; then
	echo -e "${RED}[ERROR] Debes especificar un modo: --mode dev o --mode user${NC}"
	print_help
	exit 1
fi

if [[ "$MODE" != "dev" && "$MODE" != "user" ]]; then
	echo -e "${RED}[ERROR] Debes especificar un modo válido: --mode dev o --mode user${NC}"
	print_help
	exit 1
fi

if [[ "$MODE" == "user" && -z "$ZIP_PATH" ]]; then
	echo -e "${RED}[ERROR] El modo 'user' requiere especificar la ruta del ZIP: --zip <path>${NC}"
	print_help
	exit 1
fi

echo -e "${BLUE}--- Iniciando Sincronización Soberana (Upgrade) ---${NC}"
cd "$REPO_ROOT"

# 1. Code Sync
if [[ "$MODE" == "dev" ]]; then
	if [ -d ".git" ]; then
		echo -e "${YELLOW}Detectado repositorio Git. Sincronizando con el origen (Modo Dev)...${NC}"
		git fetch origin
		CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
		echo -e "Rama actual: ${GREEN}$CURRENT_BRANCH${NC}"
		
		if [ "$AUTO_MODE" = false ]; then
			read -p "¿Deseas ejecutar 'git pull' ahora? (y/N): " SHOULD_PULL
			if [[ "$SHOULD_PULL" =~ ^[Yy]$ ]]; then
				git pull origin "$CURRENT_BRANCH"
			fi
		else
			git pull origin "$CURRENT_BRANCH"
		fi
	else
		echo -e "${RED}[ERROR] No se detectó repositorio Git pero se especificó --mode dev.${NC}"
		exit 1
	fi
elif [[ "$MODE" == "user" ]]; then
	if [ ! -f "$ZIP_PATH" ]; then
		echo -e "${RED}[ERROR] No se encuentra el archivo ZIP en: $ZIP_PATH${NC}"
		exit 1
	fi
	
	TEMP_DIR="/tmp/rp-update-temp"
	echo -e "${BLUE}Extrayendo ZIP en directorio temporal ($TEMP_DIR)...${NC}"
	rm -rf "$TEMP_DIR"
	mkdir -p "$TEMP_DIR"
	unzip -q "$ZIP_PATH" -d "$TEMP_DIR/"
	
	# Find the actual root inside the extracted zip.
	# If the ZIP was packed with a single root directory (e.g. GitHub ZIP), we use that directory.
	# Otherwise, if there are files or multiple directories at the root, we use the temp directory.
	TOP_LEVEL_COUNT=$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 | wc -l)
	TOP_LEVEL_DIR_COUNT=$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l)
	if [ "$TOP_LEVEL_COUNT" -eq 1 ] && [ "$TOP_LEVEL_DIR_COUNT" -eq 1 ]; then
		EXTRACTED_ROOT=$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -type d)
	else
		EXTRACTED_ROOT="$TEMP_DIR"
	fi
	
	echo -e "${YELLOW}Sincronizando código local con el contenido del ZIP (Modo User)...${NC}"
	if [ "$AUTO_MODE" = false ]; then
		read -p "¿Estás seguro de que quieres sobreescribir tu entorno con rsync --delete? (y/N): " SHOULD_RSYNC
		if [[ ! "$SHOULD_RSYNC" =~ ^[Yy]$ ]]; then
			echo -e "${RED}Operación abortada por el usuario.${NC}"
			rm -rf "$TEMP_DIR"
			exit 0
		fi
	fi
	
	rsync -a --delete \
		--exclude='.git/' \
		--exclude='.env' \
		--exclude='.local/' \
		--exclude='.config/' \
		--exclude='.venv/' \
		--exclude='3rdparty/' \
		--exclude='__pycache__/' \
		--exclude='*.pyc' \
		--exclude='.agent/' \
		--exclude='storage/' \
		"$EXTRACTED_ROOT/" "$REPO_ROOT/"
	
	rm -rf "$TEMP_DIR"
	echo -e "${GREEN}✓ Código actualizado con éxito vía ZIP. Se recomienda revisar 'git status' y hacer commit.${NC}"
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

# 3.5 Services Manifest Update
CONFIG_DIR=""
if command -v python3 &> /dev/null; then
	CONFIG_DIR=$(python3 -c "import sys; sys.path.insert(0, './src'); from red_pill.core.paths import get_config_dir; print(get_config_dir())" 2>/dev/null || true)
fi
if [ -z "$CONFIG_DIR" ]; then
	CONFIG_DIR="$HOME/.config/red-pill"
fi
if [ -f "$REPO_ROOT/examples/services.yaml" ]; then
	echo -e "${BLUE}Sincronizando manifiesto de servicios (services.yaml)...${NC}"
	mkdir -p "$CONFIG_DIR"
	if [ -f "$CONFIG_DIR/services.yaml" ]; then
		if ! cmp -s "$REPO_ROOT/examples/services.yaml" "$CONFIG_DIR/services.yaml"; then
			cp "$CONFIG_DIR/services.yaml" "$CONFIG_DIR/services.yaml.bak"
			echo -e "${YELLOW}Respaldado services.yaml previo en services.yaml.bak${NC}"
			cp "$REPO_ROOT/examples/services.yaml" "$CONFIG_DIR/services.yaml"
			echo -e "${GREEN}✓ Manifiesto services.yaml actualizado.${NC}"
		fi
	else
		cp "$REPO_ROOT/examples/services.yaml" "$CONFIG_DIR/services.yaml"
		echo -e "${GREEN}✓ Manifiesto services.yaml instalado en configuración.${NC}"
	fi
fi

# 3.6 Workspace registry seed (copy-if-absent — NEVER overwrite the operator's access flags)
if [ -f "$REPO_ROOT/examples/workspaces.yaml" ] && [ ! -f "$CONFIG_DIR/workspaces.yaml" ]; then
	mkdir -p "$CONFIG_DIR"
	cp "$REPO_ROOT/examples/workspaces.yaml" "$CONFIG_DIR/workspaces.yaml"
	echo -e "${GREEN}✓ Registro de workspaces sembrado (workspaces.yaml). Edítalo o usa 'red-pill workspace enable'.${NC}"
fi

# 4. Dependency & Migration ignition
if command -v uv &> /dev/null; then
	echo -e "${BLUE}Igniciando migración de datos y timers...${NC}"
	
	# Sync virtualenv dependencies
	echo -e "${BLUE}Sincronizando dependencias del entorno virtual (uv sync)...${NC}"
	uv sync

	# Ensure graphify (code knowledge-graph CLI) — external tool dependency, idempotent.
	if ! uv tool list 2>/dev/null | grep -q graphifyy; then
		echo -e "${BLUE}Instalando graphify (graphifyy) como herramienta externa...${NC}"
		uv tool install graphifyy || echo -e "${YELLOW}[WARN] No se pudo instalar graphifyy.${NC}"
	fi

	# Migrate Neon-Link database (inject sessions_mapping table)
	echo -e "${BLUE}Migrando base de datos de Neon-Link (AgyBridge)...${NC}"
	uv run python -m neon_link.db
	
	# Sanitize engrams
	uv run red-pill sanitize --dry-run || true
	
	# Reinstall timers (handles XDG data dir creation and path changes)
	uv run python scripts/schedule_pulse.py --interval-hours 1
	
	# Thread Weaving (idempotent)
	uv run python scripts/thread_weave_migrate.py

	# Per-workspace memory relocation (.claude/memory → .red-pill/memory, idempotente)
	echo -e "${BLUE}Migrando memoria por-workspace (.claude/memory → .red-pill/memory)...${NC}"
	uv run python scripts/migrate_memory.py || true

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

	# Refresh IDE anchors (Sovereign Handshake + Agent_Core) + MCP config (idempotent)
	echo -e "${BLUE}Refrescando anclas de IDE y configuración MCP...${NC}"
	uv run python scripts/inject_anchor.py --ide auto --redpill-dir "$REPO_ROOT" || true
	uv run python scripts/inject_mcp.py --uv-path "$(command -v uv)" --redpill-dir "$REPO_ROOT" || true
	command -v claude &> /dev/null && uv run python scripts/inject_settings.py --redpill-dir "$REPO_ROOT" || true

	# Workspace access: re-sync from the registry; if interactive (tty), offer to add more.
	if [ -t 0 ] && command -v claude &> /dev/null && [ -f "$REPO_ROOT/scripts/manage_workspaces.py" ]; then
		uv run python scripts/manage_workspaces.py enable || true
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
