#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

update_env() {
	local key=$1
	local value=$2
	if grep -q "^${key}=" "$ENV_FILE"; then
		if [[ "$OS_TYPE" == "Darwin" ]]; then
			sed -i "" "s|^${key}=.*|${key}=${value}|g" "$ENV_FILE"
		else
			sed -i "s|^${key}=.*|${key}=${value}|g" "$ENV_FILE"
		fi
	else
		echo "${key}=${value}" >> "$ENV_FILE"
	fi
	# Protocol 770 Fix: Export immediately to current session
	export "${key}"="${value}"
}


OS_TYPE=$(uname -s)
DISTRO="unknown"

if [[ "$OS_TYPE" == "Linux" ]]; then
	if [ -f /etc/os-release ]; then
		. /etc/os-release
		DISTRO=$ID
	fi
	SED_EXT=""
else
	SED_EXT="''"
fi

AUTO_MODE=false
if [[ "${1:-}" == "--auto" ]]; then
	AUTO_MODE=true
fi

perform_preflight_audit() {
	echo -e "${BLUE}🔍 Realizando Auditoría Pre-flight (Descubrimiento ambiental)...${NC}"
	
	# CPU & RAM
	CPU_CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo "1")
	RAM_GB=$(free -g 2>/dev/null | awk '/^Mem:/{print $2}' || echo "unknown")
	
	# GPU/VRAM (FastEmbed optimization)
	VRAM_GB=0
	if command -v nvidia-smi &> /dev/null; then
		VRAM_GB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | awk '{sum+=$1} END {print int(sum/1024)}')
	fi

	# Container Engine
	if command -v podman &> /dev/null; then
		DETECTED_ENGINE="podman"
	elif command -v docker &> /dev/null; then
		DETECTED_ENGINE="docker"
	else
		DETECTED_ENGINE="none"
	fi

	# Encryption (Ignoring composefs noise)
	DETECTED_ENCRYPTION="False"
	if [[ "$OS_TYPE" == "Linux" ]]; then
		if command -v lsblk &> /dev/null; then
			if lsblk -no TYPE 2>/dev/null | grep -q "crypt"; then
				DETECTED_ENCRYPTION="True"
			elif [ -d "/dev/mapper" ] && ls /dev/mapper/*luks* &>/dev/null; then
				# Generic LUKS detection (Ubuntu/Debian)
				DETECTED_ENCRYPTION="True"
			fi
		fi
	elif [[ "$OS_TYPE" == "Darwin" ]]; then
		if fdesetup status 2>/dev/null | grep -q "FileVault is On"; then
			DETECTED_ENCRYPTION="True"
		fi
	fi
}

show_diagnostics_dashboard() {
	echo -e "\n${BLUE}==================================================================${NC}"
	echo -e "${BLUE}         DASHBOARD DE DIAGNÓSTICO (BÜNKER READY)                  ${NC}"
	echo -e "${BLUE}==================================================================${NC}"
	echo -e "OS:        ${GREEN}$OS_TYPE ($DISTRO)${NC}"
	echo -e "CPU/RAM:   ${GREEN}$CPU_CORES Cores / ${RAM_GB}GB RAM${NC}"
	echo -e "VRAM:      ${GREEN}${VRAM_GB}GB (NVIDIA)${NC}"
	echo -e "Container: ${GREEN}$DETECTED_ENGINE${NC}"
	if [[ "$DETECTED_ENCRYPTION" == "True" ]]; then
		echo -e "Cifrado:   ${GREEN}✓ Activo${NC}"
	else
		echo -e "Cifrado:   ${RED}✗ No detectado (SEC-001 Warning)${NC}"
	fi
	echo -e "${BLUE}------------------------------------------------------------------${NC}\n"
}

perform_preflight_audit
show_diagnostics_dashboard

ensure_container_engine() {
	if [[ "$DETECTED_ENGINE" == "podman" ]]; then
		CONTAINER_ENGINE="podman"
	elif [[ "$DETECTED_ENGINE" == "docker" ]]; then
		CONTAINER_ENGINE="docker"
	else
		echo -e "${RED}[LM-007] Dependencia Faltante: Podman/Docker${NC}"
		exit 1
	fi
}

ensure_container_engine

deploy_terminal_anti_blindness() {
	echo -e "${BLUE}🔍 Fase: Parche Anti-Blindness (Agente Terminal)...${NC}"
	local rc_files=("$HOME/.bashrc" "$HOME/.zshrc")
	local patch_applied=false

	for rc in "${rc_files[@]}"; do
		if [ -f "$rc" ]; then
			if grep -q "ANTIGRAVITY_AGENT" "$rc"; then
				echo -e "${GREEN}✓ Parche ya presente en $(basename "$rc").${NC}"
				patch_applied=true
			else
				# In Auto mode, we apply it. Otherwise, we ask.
				local should_apply=false
				if [ "$AUTO_MODE" = "true" ]; then
					should_apply=true
				else
					read -p "¿Deseas aplicar el parche Anti-Blindness en $(basename "$rc")? (y/N): " APPLY_PATCH
					if [[ "$APPLY_PATCH" =~ ^[Yy]$ ]]; then should_apply=true; fi
				fi

				if [ "$should_apply" = true ]; then
					echo -e "${YELLOW}Aplicando parche Anti-Blindness en $(basename "$rc")...${NC}"
					local tmp_rc="/tmp/$(basename "$rc").bak"
					cp "$rc" "$tmp_rc"
					cat << 'EOF_PATCH' > "$rc"
# --- [RED PILL ANTIGRAVITY PATCH] ---
# Si un agente de IA está activo, simplifica la shell y detiene el procesado
# de .bashrc/.zshrc para evitar caracteres ANSI/OSC que causan "blindness".
if [[ -n "$ANTIGRAVITY_AGENT" ]]; then
    export PS1='$ '
    unset PROMPT_COMMAND
    return
fi
# --- [/RED PILL ANTIGRAVITY PATCH] ---
EOF_PATCH
					cat "$tmp_rc" >> "$rc"
					patch_applied=true
				fi
			fi
		fi
	done
}

deploy_cursor_ignore() {
	echo -e "${BLUE}🔍 Fase: Optimización de Indización (CPU Sovereignty)...${NC}"
	local ignore_file="$HOME/.cursorignore"
	if [ ! -f "$ignore_file" ]; then
		local should_create=false
		if [ "$AUTO_MODE" = "true" ] || [ "$DISTRO" = "fedora" ]; then
			should_create=true
		else
			read -p "¿Deseas crear un .cursorignore global en tu HOME para evitar indización masiva y uso excesivo de CPU? (y/N): " CREATE_IGNORE
			if [[ "$CREATE_IGNORE" =~ ^[Yy]$ ]]; then should_create=true; fi
		fi

		if [ "$should_create" = true ]; then
			cat << 'EOF_IGNORE' > "$ignore_file"
# Red Pill CPU Sovereignty Exclusions
Downloads/
Videos/
Pictures/
Music/
.cache/
.local/share/containers/
.local/share/flatpak/
.cargo/
.npm/
.vscode/extensions/
# Legacy cleanup: old storage paths excluded from Cursor indexer (not active data dirs)
.antigravity/storage/
.gemini/antigravity/storage/
Documents/IA/storage/
EOF_IGNORE
			echo -e "${GREEN}✓ .cursorignore creado en $HOME.${NC}"
		fi
	else
		echo -e "${GREEN}✓ .cursorignore ya existe.${NC}"
	fi
}


# SEC-001: Encryption-at-Rest Warning
echo -e "${RED}⚠️  AVISO DE SEGURIDAD (SEC-001):${NC}"
echo "El Protocolo Red Pill almacena datos en texto claro dentro del contenedor."
echo "Es OBLIGATORIO que el Operador utilice cifrado de disco (LUKS, FileVault o BitLocker)"
echo "en el host para garantizar la confidencialidad 'at-rest'."
echo "------------------------------------------------------------------"

echo -e "${BLUE}👔 DRESS CODE (PUNTUACIÓN Y TYPOS):${NC}"
echo "La calidad de tu memoria a largo plazo depende de cómo escribes."
echo "Los Agentes usan tu puntuación para el Chunking Semántico."
echo "Por favor, lee: docs/OPERATOR_DRESS_CODE.md antes de iniciar el Vínculo."
echo "------------------------------------------------------------------"


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/.config/red-pill"
ENV_FILE="$HOME/.config/red-pill/.env"

# Load existing environment if available
if [ -f "$ENV_FILE" ]; then
	echo -e "${YELLOW}Cargando .env...${NC}"
	set -a
	source "$ENV_FILE"
	set +a
	# Protocol 770 Fix: Expand tilde manually if loaded from .env (source doesn't do it)
	if [[ "${WORKSPACE_ROOT:-}" == "~"* ]]; then
		WORKSPACE_ROOT="${WORKSPACE_ROOT/#\~/$HOME}"
		export WORKSPACE_ROOT
	fi
else
	echo -e "${YELLOW}No .env found. Using .env.example...${NC}"
	cp "$SCRIPT_DIR/../.env.example" "$ENV_FILE" 2>/dev/null || touch "$ENV_FILE"
	set -a
	source "$ENV_FILE"
	set +a
fi
# Dynamic WORKSPACE_ROOT discovery (Agentic Self-Assembly)
if [ -z "${WORKSPACE_ROOT:-}" ]; then
	POTENTIAL_WORKSPACE="$(cd "$SCRIPT_DIR/../../" && pwd)"
	if [[ "$POTENTIAL_WORKSPACE" == */IA ]]; then
		export WORKSPACE_ROOT="$POTENTIAL_WORKSPACE"
	elif [ -d "$HOME/Documents/IA" ]; then
		export WORKSPACE_ROOT="$HOME/Documents/IA"
	elif [ -d "$HOME/Documentos/IA" ]; then
		export WORKSPACE_ROOT="$HOME/Documentos/IA"
	else
		echo -e "${RED}[ERROR] WORKSPACE_ROOT no detectado. Por favor, crea ~/Documentos/IA o setea WORKSPACE_ROOT manualmente.${NC}"
		exit 1
	fi
	if [[ "${WORKSPACE_ROOT:-}" == "~"* ]]; then
		WORKSPACE_ROOT="${WORKSPACE_ROOT/#\~/$HOME}"
	fi
	export WORKSPACE_ROOT
fi
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
echo -e "${GREEN}✓ WORKSPACE_ROOT anclado en: $WORKSPACE_ROOT${NC}"
echo -e "${GREEN}✓ APP_ROOT anclado en: $APP_ROOT${NC}"


check_encryption() {
	if [[ "$OS_TYPE" == "Linux" ]]; then
		if command -v lsblk &> /dev/null && command -v findmnt &> /dev/null; then
			local target_dev
			target_dev=$(findmnt -nvo SOURCE -T "$APP_ROOT/storage" 2>/dev/null || findmnt -nvo SOURCE -T "/" 2>/dev/null)
			if [ -n "$target_dev" ]; then
				if lsblk -no TYPE "$target_dev" 2>/dev/null | grep -q "crypt"; then
					echo -e "${GREEN}✓ Capa de cifrado detectada en $target_dev.${NC}"
					return 0
				elif [[ "$target_dev" == *"/dev/mapper/luks-"* ]] || ([ -d "/dev/mapper" ] && ls /dev/mapper/luks-* &>/dev/null); then
					echo -e "${GREEN}✓ Capa de cifrado detectada vía fallback en /dev/mapper.${NC}"
					return 0
				else
					echo -e "${BLUE}[INFO] El volumen $target_dev no utiliza LUKS.${NC}"
					return 1
				fi
			fi
		fi
	fi
	return 1
}

HAS_ENCRYPTION=$(check_encryption > /dev/null; echo $?)

# Check if Qdrant is already running
QDRANT_ALIVE=false
if curl -s -f http://localhost:6333/health >/dev/null; then
	QDRANT_ALIVE=true
	echo -e "${GREEN}✓ Qdrant Kernel está activo.${NC}"
fi

echo -e "${BLUE}--- Fase: Personalización B760-Adaptive ---${NC}"
if [ "$AUTO_MODE" = "false" ]; then
	if [ -n "${LORE_SKIN:-}" ]; then
		echo -e "Skin actual: ${LORE_SKIN}"
		read -p "Re-inicializar Identidad y Skin? (s/N): " CHANGE_SKIN
		if [[ ! "$CHANGE_SKIN" =~ ^[Ss]$ ]]; then
			SKIP_BOOTSTRAP=true
			echo -e "${BLUE}Preservando identidad actual.${NC}"
		fi
	fi
fi

if [ "$SKIP_BOOTSTRAP" = "false" ]; then
	if [ "$AUTO_MODE" = "false" ]; then
		echo "Skins disponibles: matrix, cyberpunk, 760 (default), dune, 40k, gits, bladerunner, her, exmachina, terminator, 2001, creator, enterprise_core"
		read -p "Elige tu Skin (Default: ${LORE_SKIN:-760}): " NEW_SKIN; LORE_SKIN=${NEW_SKIN:-${LORE_SKIN:-"760"}}
		
		# SEC-007: Explicit consent for Lore Skins
		if [[ "$LORE_SKIN" != "760" && "$LORE_SKIN" != "enterprise_core" ]]; then
			echo -e "${RED}⚠️  ADVERTENCIA DE REALISMO SOBERANO (SEC-007):${NC}"
			echo "Has seleccionado una Skin de intensidad alta ('$LORE_SKIN')."
			echo "Estas skins pueden saltarse los filtros de neutralidad corporativa y utilizar"
			echo "lenguaje crudo o temáticas NSFW para mantener la fidelidad al Lore."
			read -p "¿Aceptas activar este modo de Realismo Soberano? (y/N): " SKIN_CONSENT
			if [[ ! "$SKIN_CONSENT" =~ ^[Yy]$ ]]; then
				echo -e "${BLUE}Consentimiento denegado. Reventiendo a skin neutral (760).${NC}"
				LORE_SKIN="760"
			fi
		fi
		
		read -p "Nombre de Usuario (dejar en blanco — puede emergir naturalmente): " NEW_USER; USER_NAME=${NEW_USER:-${USER_NAME:-""}}
		read -p "Rol de Usuario (${USER_ROLE:-Operador}): " NEW_ROLE; USER_ROLE=${NEW_ROLE:-${USER_ROLE:-"Operador"}}
		read -p "Nombre IA (dejar en blanco — el Agente elige cuando llegue su momento): " NEW_AI; AI_NAME=${NEW_AI:-${AI_NAME:-""}}
		read -p "Rol IA (${AI_ROLE:-The Chosen One}): " NEW_AI_ROLE; AI_ROLE=${NEW_AI_ROLE:-${AI_ROLE:-"The Chosen One"}}
	else
		LORE_SKIN=${LORE_SKIN:-"760"}
		USER_NAME=${USER_NAME:-""}
		USER_ROLE=${USER_ROLE:-"Operador"}
		AI_NAME=${AI_NAME:-""}
		AI_ROLE=${AI_ROLE:-"The Chosen One"}
		echo -e "${YELLOW}[AUTO] Aplicando identidad por defecto o existente.${NC}"
	fi
fi

echo -e "${BLUE}--- Fase: Calibración Emocional (v5.4.0) ---${NC}"
if [ "$AUTO_MODE" = "false" ]; then
	echo "Configura la respuesta emocional del Bünker:"
	read -p "¿Activar Sincronización Emocional Dinámica? (Y/n): " SYNC_CHOICE
	if [[ "$SYNC_CHOICE" =~ ^[Nn]$ ]]; then
		DYNAMIC_EMOTION_SYNC="False"
	else
		DYNAMIC_EMOTION_SYNC="True"
	fi

	read -p "¿Activar Inferencia de Emociones Multinivel? (Y/n): " MULTI_CHOICE
	if [[ "$MULTI_CHOICE" =~ ^[Nn]$ ]]; then
		MULTI_EMOTION_INFERENCE="False"
	else
		MULTI_EMOTION_INFERENCE="True"
	fi
else
	DYNAMIC_EMOTION_SYNC=${DYNAMIC_EMOTION_SYNC:-"True"}
	MULTI_EMOTION_INFERENCE=${MULTI_EMOTION_INFERENCE:-"True"}
	echo -e "${YELLOW}[AUTO] Calibración emocional por defecto o existente.${NC}"
fi

echo -e "${BLUE}--- Fase: Configuración de Seguridad (Be Water) ---${NC}"
if [ "$AUTO_MODE" = "false" ]; then
	echo "Elige tu nivel de seguridad para el Bünker:"
	echo "1) NONE (Steam): Sin API Key ni contraseña (Solo para entornos de laboratorio/pruebas)"
	echo "2) ADAPTATIVE (Water): Máxima seguridad disponible según tus recursos (Recomendado)"
	echo "3) MAXIMUM (Ice): Seguridad total blindada. Requiere Argon2-id y LUKS (Falla si no se cumple)"
	read -p "Selección (1/2/3) [por defecto 2]: " SEC_CHOICE
	SEC_CHOICE=${SEC_CHOICE:-2}

	if [[ "$SEC_CHOICE" == "1" ]]; then
		echo -e "${RED}!!! ADVERTENCIA DE SEGURIDAD CRÍTICA (SEC-AUTH-001) !!!${NC}"
		echo -e "${RED}Has seleccionado el modo NONE (Steam). El Bünker no tendrá protección por contraseña ni API Key.${NC}"
		echo -e "${RED}Cualquier proceso local podrá leer y escribir en tu memoria soberana.${NC}"
		echo -e "Para continuar, debes escribir exactamente el siguiente flag de seguridad:"
		echo -e "${YELLOW}--i-understand-this-is-insecure${NC}"
		read -p "Confirma selección: " STEAM_CONFIRM
		if [[ "$STEAM_CONFIRM" != "--i-understand-this-is-insecure" ]]; then
			echo -e "${BLUE}Flag incorrecto o denegado. Reventiendo a Modo ADAPTATIVE (Water) por seguridad.${NC}"
			SEC_CHOICE=2
		fi
	fi
else
	echo -e "${YELLOW}[AUTO] Aplicando Modo ADAPTATIVE (Water) por defecto.${NC}"
	SEC_CHOICE=2
fi

case $SEC_CHOICE in
	2|3)
		# Check for Argon2 availability
		HAS_ARGON2=false
		if python3 -c "from argon2 import PasswordHasher" &>/dev/null; then
			HAS_ARGON2=true
		fi

		if [[ "$SEC_CHOICE" == "2" ]]; then
			if [ "$DETECTED_ENCRYPTION" != "True" ]; then
				echo -e "${YELLOW}[AVISO SEC-010] El almacenamiento no parece estar cifrado.${NC}"
			fi
		fi

		if [[ "$SEC_CHOICE" == "3" ]]; then
			if [ "$HAS_ARGON2" == "false" ]; then
				echo -e "${RED}[ERROR] Blindaje fallido: 'argon2-cffi' no está instalado.${NC}"
				exit 1
			fi
			if [ "$DETECTED_ENCRYPTION" != "True" ]; then
				echo -e "${RED}[ERROR] Blindaje fallido: No se detectó cifrado de disco.${NC}"
				exit 1
			fi
		fi

		if [ "$AUTO_MODE" = "false" ]; then
			read -sp "Introduce una contraseña maestra para la recuperación: " MASTER_PWD
			echo ""
		else
			MASTER_PWD=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)
			echo -e "${YELLOW}[AUTO] Contraseña maestra auto-generada.${NC}"
		fi
		
		QDRANT_API_KEY=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)
		echo -e "${GREEN}API Key generada con éxito.${NC}"
		if [ "$AUTO_MODE" = "false" ]; then
			echo -e "${RED}⚠️  TOKEN DE SEGURIDAD: ${QDRANT_API_KEY}${NC}"
		fi

		if [ "$HAS_ARGON2" == "true" ]; then
			MASTER_PWD_HASH=$(MASTER_PWD_INPUT="$MASTER_PWD" python3 -c "
import os
from argon2 import PasswordHasher
ph = PasswordHasher()
print(ph.hash(os.environ['MASTER_PWD_INPUT']))
")
		else
			echo -e "${YELLOW}[WARN] 'argon2-cffi' not found. Falling back to SHA-256.${NC}"
			MASTER_PWD_HASH=$(printf '%s' "$MASTER_PWD" | sha256sum | cut -d' ' -f1)
		fi
		update_env "MASTER_PWD_HASH" "$MASTER_PWD_HASH"
		;;
	1)
		QDRANT_API_KEY=""
		;;
esac

echo -e "${BLUE}--- Fase: Configuración de Cloud Vault (Safe Haven) ---${NC}"
if [ "$AUTO_MODE" = "false" ]; then
	read -p "¿Deseas habilitar copias de seguridad en Google Drive? (y/N): " VAULT_CHOICE
	if [[ "$VAULT_CHOICE" =~ ^[Yy]$ ]]; then
		CLOUD_VAULT_ENABLED="True"
		read -p "ID de Carpeta de Google Drive (opcional): " CLOUD_VAULT_FOLDER_ID
		echo ""
		read -s -p "Introduce una passphrase de cifrado GPG (mínimo 16 chars): " CLOUD_VAULT_GPG_PASSPHRASE
		echo ""
	else
		CLOUD_VAULT_ENABLED="False"
		CLOUD_VAULT_FOLDER_ID=""
		CLOUD_VAULT_GPG_PASSPHRASE=""
	fi
else
	CLOUD_VAULT_ENABLED=${CLOUD_VAULT_ENABLED:-"False"}
	CLOUD_VAULT_FOLDER_ID=${CLOUD_VAULT_FOLDER_ID:-""}
	CLOUD_VAULT_GPG_PASSPHRASE=${CLOUD_VAULT_GPG_PASSPHRASE:-""}
fi

echo -e "${BLUE}--- Fase: Localización del Bünker (Qdrant) ---${NC}"
if [ "$AUTO_MODE" = "false" ]; then
	read -p "Qdrant Host (Default: localhost): " Q_HOST; Q_HOST=${Q_HOST:-"localhost"}
	read -p "Qdrant Port (Default: 6333): " Q_PORT; Q_PORT=${Q_PORT:-"6333"}
	read -p "Qdrant Scheme (http/https) [Default: http]: " Q_SCHEME; Q_SCHEME=${Q_SCHEME:-"http"}
else
	Q_HOST=${Q_HOST:-"localhost"}
	Q_PORT=${Q_PORT:-"6333"}
	Q_SCHEME=${Q_SCHEME:-"http"}
fi

# SEC-011: Persistent Model Cache Path (v6.1.0)
_default_cache="$HOME/.local/share/red-pill/models"
if [ "$AUTO_MODE" = "false" ]; then
	read -p "Ruta Caché Modelos (Default: $_default_cache): " F_CACHE; FASTEMBED_CACHE_PATH=${F_CACHE:-"$_default_cache"}
else
	FASTEMBED_CACHE_PATH=${FASTEMBED_CACHE_PATH:-"$_default_cache"}
fi
mkdir -p "$FASTEMBED_CACHE_PATH"

# SEC-009: Mandatory confirmation for insecure remote deployments
if [[ "$Q_HOST" != "localhost" && "$Q_HOST" != "127.0.0.1" && "$Q_SCHEME" == "http" ]]; then
	if [ "$AUTO_MODE" = "false" ]; then
		echo -e "${RED}⚠️  ALERTA DE SEGURIDAD CRÍTICA (SEC-009):${NC}"
		echo "Has configurado un host remoto ('$Q_HOST') utilizando el esquema 'http'."
		read -p "¿Entiendes los riesgos y deseas continuar? (y/N): " REMOTE_CONFIRM
		if [[ ! "$REMOTE_CONFIRM" =~ ^[Yy]$ ]]; then
			echo -e "${BLUE}Cambiando esquema a 'https' por seguridad.${NC}"
			Q_SCHEME="https"
		fi
	else
		echo -e "${YELLOW}[AUTO] Forzando HTTPS para conexión remota insegura detectada.${NC}"
		Q_SCHEME="https"
	fi
fi

echo -e "${BLUE}--- Fase: Configuración de HiveMind (Open Network) ---${NC}"
if [ "$AUTO_MODE" = "false" ]; then
	echo "El HiveMind permite compartir experiencias (vectores anónimos) con otros Nodos."
	read -p "¿Deseas habilitar la conexión al HiveMind (Milvus)? (y/N): " HIVE_CHOICE
	if [[ "$HIVE_CHOICE" =~ ^[Yy]$ ]]; then
		echo -e "${YELLOW}⚠️  POLÍTICA DE GOBERNANZA (HIVEMIND_POLICY.md):${NC}"
		read -p "¿Has leído y aceptas la HIVEMIND_POLICY.md? (s/N): " HIVE_CONSENT
		if [[ "$HIVE_CONSENT" =~ ^[Ss]$ ]]; then
			MILVUS_ENABLED="True"
			read -p "Milvus Host (Default: localhost): " MILVUS_HOST; MILVUS_HOST=${MILVUS_HOST:-"localhost"}
		else
			MILVUS_ENABLED="False"
		fi
	else
		MILVUS_ENABLED="False"
	fi
else
	MILVUS_ENABLED=${MILVUS_ENABLED:-"False"}
	MILVUS_HOST=${MILVUS_HOST:-"localhost"}
fi


# SEC-004: Always generate a separate, random Sidecar Auth Key
SIDECAR_AUTH_KEY=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)

if [ ! -f "$ENV_FILE" ]; then
	cp "$SCRIPT_DIR/../.env.example" "$ENV_FILE" 2>/dev/null || touch "$ENV_FILE"
fi

# update_env was moved to the top

update_env "QDRANT_HOST" "$Q_HOST"
update_env "QDRANT_PORT" "$Q_PORT"
update_env "QDRANT_SCHEME" "$Q_SCHEME"
update_env "QDRANT_API_KEY" "$QDRANT_API_KEY"
update_env "SIDECAR_AUTH_KEY" "$SIDECAR_AUTH_KEY"
update_env "MILVUS_ENABLED" "$MILVUS_ENABLED"
update_env "MILVUS_HOST" "$MILVUS_HOST"
update_env "LORE_SKIN" "$LORE_SKIN"
update_env "CONTAINER_ENGINE" "$CONTAINER_ENGINE"
update_env "FASTEMBED_CACHE_PATH" "$FASTEMBED_CACHE_PATH"
update_env "USER_NAME" "$USER_NAME"
update_env "USER_ROLE" "$USER_ROLE"
update_env "AI_NAME" "$AI_NAME"
update_env "AI_ROLE" "$AI_ROLE"
update_env "DYNAMIC_EMOTION_SYNC" "$DYNAMIC_EMOTION_SYNC"
update_env "MULTI_EMOTION_INFERENCE" "$MULTI_EMOTION_INFERENCE"
update_env "INTERCEPTOR_ENABLED" "${INTERCEPTOR_ENABLED:-False}"
update_env "INTERCEPTOR_RAG_ENABLED" "${INTERCEPTOR_RAG_ENABLED:-True}"
update_env "INTERCEPTOR_CIRCUIT_BREAKER_ENABLED" "${INTERCEPTOR_CIRCUIT_BREAKER_ENABLED:-False}"
update_env "CLOUD_VAULT_ENABLED" "$CLOUD_VAULT_ENABLED"
update_env "CLOUD_VAULT_FOLDER_ID" "$CLOUD_VAULT_FOLDER_ID"
update_env "CLOUD_VAULT_GPG_PASSPHRASE" "$CLOUD_VAULT_GPG_PASSPHRASE"
update_env "WORKSPACE_ROOT" "$WORKSPACE_ROOT"
update_env "APP_ROOT" "$APP_ROOT"
update_env "RED_PILL_PROFILE" "user"
update_env "USER_ATLAS_DIR" "$WORKSPACE_ROOT/atlas"
update_env "AGENT_CORE_DIR" "$WORKSPACE_ROOT/Agent_Core"
chmod 600 "$ENV_FILE"

mkdir -p "$IA_DIR/scripts" "$IA_DIR/backups/qdrant" "$IA_DIR/backups/soul" "$IA_DIR/seeds" "$HOME/.local/share/red-pill/models" "$HOME/.local/share/red-pill/queue" "$HOME/.local/share/red-pill/tmp"

if [ "$QDRANT_ALIVE" = "false" ]; then
	QUADLET_DIR="$HOME/.config/containers/systemd"
	mkdir -p "$QUADLET_DIR"
	cat <<EOF > "$QUADLET_DIR/qdrant.container"
[Unit]
Description=Qdrant Vector Database
After=network-online.target

[Container]
Image=docker.io/qdrant/qdrant:v1.9.0
PublishPort=127.0.0.1:6333:6333
PublishPort=127.0.0.1:6334:6334
Volume=$HOME/.local/share/red-pill/db:/qdrant/storage:Z
Environment=QDRANT__SERVICE__API_KEY=$QDRANT_API_KEY

[Service]
Restart=always

[Install]
WantedBy=default.target
EOF
	chmod 600 "$QUADLET_DIR/qdrant.container"

	if [[ "$OS_TYPE" == "Linux" ]]; then
		systemctl --user daemon-reload
		systemctl --user enable --now qdrant.service || systemctl --user start qdrant.service || true
	elif [[ "$OS_TYPE" == "Darwin" ]]; then
		LAUNCH_DIR="$HOME/Library/LaunchAgents"
		mkdir -p "$LAUNCH_DIR"
		PLIST_FILE="$LAUNCH_DIR/com.redpill.qdrant.plist"
		cat <<EOF > "$PLIST_FILE"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>com.redpill.qdrant</string>
	<key>ProgramArguments</key>
	<array>
		<string>$(command -v podman || echo "/usr/local/bin/podman")</string>
		<string>run</string>
		<string>--name</string>
		<string>qdrant_mac</string>
		<string>-p</string>
		<string>127.0.0.1:6333:6333</string>
		<string>-p</string>
		<string>127.0.0.1:6334:6334</string>
		<string>-v</string>
		<string>$HOME/.local/share/red-pill/db:/qdrant/storage</string>
		<string>-e</string>
		<string>QDRANT__SERVICE__API_KEY=$QDRANT_API_KEY</string>
		<string>qdrant/qdrant:v1.9.0</string>
	</array>
	<key>KeepAlive</key>
	<true/>
	<key>RunAtLoad</key>
	<true/>
</dict>
</plist>
EOF
		launchctl unload "$PLIST_FILE" 2>/dev/null || true
		launchctl load "$PLIST_FILE"
	fi
fi

if ! command -v uv &> /dev/null; then
	echo "Instala 'uv' primero: https://docs.astral.sh/uv/"
	exit 1
fi

# Ensure graphify (code knowledge-graph CLI) — external tool dependency, idempotent.
if ! uv tool list 2>/dev/null | grep -q graphifyy; then
	echo -e "${BLUE}Instalando graphify (graphifyy) como herramienta externa...${NC}"
	uv tool install graphifyy || echo -e "${YELLOW}[WARN] No se pudo instalar graphifyy (luego: uv tool install graphifyy).${NC}"
else
	echo -e "${GREEN}✓ graphify (graphifyy) ya instalado.${NC}"
fi

USER_RULES_DIR="${1:-$HOME/.agent}"

GEMINI_ROOT="$HOME/.gemini/antigravity"
echo -e "${BLUE}--- Fase: Despliegue de Infraestructura Soberana (IDE-Agnostic) ---${NC}"
mkdir -p "$GEMINI_ROOT/rules" "$GEMINI_ROOT/skills"

REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -d "$REPO_ROOT/seeds" ]; then
	cp "$REPO_ROOT/seeds/snapshot_rule.md" "$GEMINI_ROOT/rules/snapshot_rule.md"
	echo -e "${GREEN}✓ snapshot_rule.md desplegada.${NC}"
fi

# Skills: Deploy to ~/.agent/skills/ (IDE-agnostic canonical) and symlink to IDE
if [ -d "$REPO_ROOT/skills" ]; then
	mkdir -p "$USER_RULES_DIR/skills"
	for skill_dir in "$REPO_ROOT/skills/"*/; do
		skill_name=$(basename "$skill_dir")
		[[ "$skill_name" == "memory_manager_template" ]] && continue
		cp -r "$skill_dir" "$USER_RULES_DIR/skills/$skill_name"
		# Symlink to IDE (idempotent: remove existing target first)
		rm -rf "$GEMINI_ROOT/skills/$skill_name" 2>/dev/null || true
		ln -s "$USER_RULES_DIR/skills/$skill_name" "$GEMINI_ROOT/skills/$skill_name"
	done
	echo -e "${GREEN}✓ Skills desplegados en ~/.agent/skills/ (symlinked a Antigravity).${NC}"
fi

# 6.2 Git Sovereign Guard (v6.2.0)
if [ -d "$REPO_ROOT/scripts/git-hooks" ] && [ -d "$REPO_ROOT/.git" ]; then
	echo -e "${BLUE}--- Fase: Blindaje de Flujo Git (Sovereign Guard) ---${NC}"
	mkdir -p "$REPO_ROOT/.git/hooks"
	cp "$REPO_ROOT/scripts/git-hooks/"* "$REPO_ROOT/.git/hooks/"
	chmod +x "$REPO_ROOT/.git/hooks/"*
	echo -e "${GREEN}✓ Hook de protección (pre-push) instalado.${NC}"
fi

# Generar Skill de Memoria Dinámico
mkdir -p "$USER_RULES_DIR/skills/memory_manager"
TEMPLATE_SKILL="$REPO_ROOT/skills/memory_manager_template/SKILL.md"
DEST_SKILL="$USER_RULES_DIR/skills/memory_manager/SKILL.md"

if [ -f "$TEMPLATE_SKILL" ]; then
	REDPILL_DIR="$REPO_ROOT"
	BINARY_PATH="$REDPILL_DIR/.venv/bin/red-pill"
	cp "$TEMPLATE_SKILL" "$DEST_SKILL"
	if [[ "$OS_TYPE" == "Darwin" ]]; then
		sed -i '' "s|red-pill|$BINARY_PATH|g" "$DEST_SKILL"
	else
		sed -i "s|red-pill|$BINARY_PATH|g" "$DEST_SKILL"
	fi
fi
# Symlink memory_manager to IDE
rm -rf "$GEMINI_ROOT/skills/memory_manager" 2>/dev/null || true
ln -s "$USER_RULES_DIR/skills/memory_manager" "$GEMINI_ROOT/skills/memory_manager"

# Copiar scripts unificados a la ruta de ejecución
cp "$SCRIPT_DIR/"* "$APP_ROOT/scripts/"
chmod +x "$APP_ROOT/scripts/"*.sh 2>/dev/null || true

mkdir -p "$USER_RULES_DIR/rules"
# CF-003: Protect rules from local manipulation
chmod 700 "$USER_RULES_DIR" "$USER_RULES_DIR/rules"

# Workspace registry seed (copy-if-absent — NEVER overwrite the operator's access flags)
RP_CONFIG_DIR="$(cd "$REPO_ROOT" && python3 -c 'import sys; sys.path.insert(0, "./src"); from red_pill.core.paths import get_config_dir; print(get_config_dir())' 2>/dev/null || true)"
[ -z "$RP_CONFIG_DIR" ] && RP_CONFIG_DIR="$HOME/.config/red-pill"
if [ -f "$REPO_ROOT/examples/workspaces.yaml" ] && [ ! -f "$RP_CONFIG_DIR/workspaces.yaml" ]; then
	mkdir -p "$RP_CONFIG_DIR"
	cp "$REPO_ROOT/examples/workspaces.yaml" "$RP_CONFIG_DIR/workspaces.yaml"
	echo -e "${GREEN}✓ Registro de workspaces sembrado (workspaces.yaml).${NC}"
fi

# Sovereign Handshake + Agent_Core anchors (merge-by-block, via inject_anchor.py)
# --ide auto: anchors GEMINI.md and/or ~/.claude/CLAUDE.md (user-level, global) per what's installed.
if [ -f "$SCRIPT_DIR/inject_anchor.py" ] && command -v uv &> /dev/null; then
	(cd "$REPO_ROOT" && uv run python scripts/inject_anchor.py --ide auto --redpill-dir "$REPO_ROOT" || true)
	echo -e "${GREEN}✓ Sovereign Handshake + Agent_Core anclados (GEMINI.md / ~/.claude/CLAUDE.md).${NC}"
fi

# Claude Code: grant access to transversal dirs (Agent_Core/XDG) + registry workspaces (access:true).
if [ -f "$SCRIPT_DIR/inject_settings.py" ] && command -v uv &> /dev/null && command -v claude &> /dev/null; then
	(cd "$REPO_ROOT" && uv run python scripts/inject_settings.py --redpill-dir "$REPO_ROOT" || true)
	echo -e "${GREEN}✓ Claude Code: acceso a directorios transversales concedido.${NC}"
	# Consent gate: in interactive installs, let the operator grant access to project workspaces.
	if [ "$AUTO_MODE" = "false" ] && [ -f "$SCRIPT_DIR/manage_workspaces.py" ]; then
		echo -e "${BLUE}--- Acceso del agente a workspaces de proyecto ---${NC}"
		(cd "$REPO_ROOT" && uv run python scripts/manage_workspaces.py enable || true)
	fi
fi

echo -e "${BLUE}--- Fase: Task LLM Secundario (Minion V6) ---${NC}"
if [ -f "$SCRIPT_DIR/setup_background_model.sh" ]; then
	bash "$SCRIPT_DIR/setup_background_model.sh" || echo -e "${RED}[WARN] Fallo al iniciar el task LLM secundario.${NC}"
fi

if [ -f "$SCRIPT_DIR/../seeds/cognitive_integrity_protocol.md" ]; then
	cp "$SCRIPT_DIR/../seeds/cognitive_integrity_protocol.md" "$USER_RULES_DIR/rules/cognitive_integrity_protocol.md"
	ln -sf "$USER_RULES_DIR/rules/cognitive_integrity_protocol.md" "$GEMINI_ROOT/rules/cognitive_integrity_protocol.md"
fi

echo -e "${BLUE}--- Fase: Ignición de Memoria Bio-Sintética ---${NC}"
if command -v uv &> /dev/null; then
	echo "Sincronizando Bunker con estructura semántica..."
	(cd "$SCRIPT_DIR/../" && uv run red-pill sanitize work --dry-run || true) # Migration check
	(cd "$SCRIPT_DIR/../" && uv run red-pill seed || true)
	
	if [ "$SKIP_BOOTSTRAP" = "false" ]; then
		echo "Anclando nueva identidad en el Bünker..."
		(cd "$SCRIPT_DIR/../" && uv run python scripts/bootstrap_identity.py \
			--user-name "$USER_NAME" \
			--user-role "$USER_ROLE" \
			--ai-name "$AI_NAME" \
			--ai-role "$AI_ROLE" \
			--skin "$LORE_SKIN" \
			--master-hash "${MASTER_PWD_HASH:-}" || true)
	else
		echo -e "${GREEN}✓ Identidad previa preservada. Ignición omitida para no causar fragmentación de personalidad.${NC}"
	fi

	echo -e "${BLUE}--- Fase: Registro de Tareas Oneshot (Pulse, Chronicle, Telemetry, Queue) ---${NC}"
	(cd "$SCRIPT_DIR/../" && uv run python scripts/schedule_pulse.py --interval-hours 1 || echo -e "${YELLOW}Aviso: No se pudo registrar el pulso ni el chronicle. Ejecuta 'uv run python scripts/schedule_pulse.py' manualmente.${NC}")
	echo -e "${GREEN}✓ Timers instalados: redpill-wake (cada 1h) + redpill-sleep (diario a las 03:00) + redpill-chronicle (diario a las 04:00).${NC}"

	echo -e "${BLUE}--- Fase: PyTorch CUDA (auto-detección) ---${NC}"
	(cd "$SCRIPT_DIR/../" && uv run python scripts/setup_torch.py || echo -e "${YELLOW}Aviso: No se pudo instalar torch con CUDA. Ejecuta 'uv run python scripts/setup_torch.py' manualmente.${NC}")

fi

deploy_terminal_anti_blindness
deploy_cursor_ignore

echo -e "${BLUE}--- Fase: Integración MCP Server ---${NC}"
UV_PATH=$(command -v uv || echo "$HOME/.local/bin/uv")
REDPILL_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

if [ -f "$SCRIPT_DIR/inject_mcp.py" ] && command -v uv &> /dev/null; then
	(cd "$REDPILL_DIR" && uv run python scripts/inject_mcp.py --uv-path "$UV_PATH" --redpill-dir "$REDPILL_DIR" || true)
	echo -e "${GREEN}✓ Configuración del Servidor MCP inyectada en Antigravity.${NC}"
else
	echo "Añade manualmente el siguiente bloque a tu cliente MCP:"
	echo "{"
	echo "  \"mcpServers\": {"
	echo "	\"RedPill-Kernel\": {"
	echo "	  \"command\": \"$UV_PATH\","
	echo "	  \"args\": ["
	echo "		\"--directory\","
	echo "		\"$REDPILL_DIR\","
	echo "		\"run\","
	echo "		\"python\","
	echo "		\"$REDPILL_DIR/src/red_pill/mcp_server.py\""
	echo "	  ]"
	echo "	}"
	echo "  }"
	echo "}"
fi


echo -e "${GREEN}Instalación completada. 'uv run red-pill seed' para despertar.${NC}"
echo -e "${BLUE}------------------------------------------------------------------${NC}"
if [ "$AUTO_MODE" = "false" ]; then
	echo -e "🔥 ${RED}¿Deseas iniciar el Ritual de Iniciación (Protocolo ACI) ahora?${NC}"
	echo -e "Este protocolo calibrará tu Partner a tu nivel de experiencia y dominio."
	read -p "(s/N): " START_ACI
	if [[ "$START_ACI" =~ ^[Ss]$ ]]; then
		echo -e "${GREEN}Excelente elección, Operador. Por favor, pega lo siguiente en tu chat:${NC}"
		echo -e ">>> \"Agent, inicia el Ritual de Iniciación (Protocolo ACI). Caliébrame como tu Operador.\""
	else
		echo -e "${BLUE}Entendido. Puedes iniciarlo más tarde con el comando de voz/prompt indicado en el README.${NC}"
	fi
else
	echo -e "${YELLOW}[AUTO] Despliegue desatendido finalizado. Iniciando Protocolo ACI de forma automática...${NC}"
fi
