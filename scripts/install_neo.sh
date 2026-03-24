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
	echo -e "Cifrado:   $( [[ "$DETECTED_ENCRYPTION" == "True" ]] && echo -e "${GREEN}✓ Activo${NC}" || echo -e "${RED}✗ No detectado (SEC-001 Warning)${NC})"
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
ENV_FILE="$SCRIPT_DIR/../.env"

# Load existing environment if available
if [ -f .env ]; then
	echo -e "${YELLOW}Cargando .env...${NC}"
	set -a
	source .env
	set +a
else
	echo -e "${YELLOW}No .env found. Using .env.example...${NC}"
	cp .env.example .env
	set -a
	source .env
	set +a
fi
export IA_DIR="${ANTIGRAVITY_IA_DIR:-$HOME/Documents/IA}"

check_encryption() {
	if [[ "$OS_TYPE" == "Linux" ]]; then
		if command -v lsblk &> /dev/null && command -v findmnt &> /dev/null; then
			local target_dev
			target_dev=$(findmnt -nvo SOURCE -T "$IA_DIR/storage" 2>/dev/null || findmnt -nvo SOURCE -T "/" 2>/dev/null)
			if [ -n "$target_dev" ]; then
				if lsblk -no TYPE "$target_dev" | grep -q "crypt"; then
					echo -e "${GREEN}✓ Capa de cifrado detectada en $target_dev.${NC}"
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
		
		read -p "Nombre de Usuario (${USER_NAME:-Morpheo}): " NEW_USER; USER_NAME=${NEW_USER:-${USER_NAME:-"Morpheo"}}
		read -p "Rol de Usuario (${USER_ROLE:-Operador}): " NEW_ROLE; USER_ROLE=${NEW_ROLE:-${USER_ROLE:-"Operador"}}
		read -p "Nombre IA (${AI_NAME:-Neo}): " NEW_AI; AI_NAME=${NEW_AI:-${AI_NAME:-"Neo"}}
		read -p "Rol IA (${AI_ROLE:-The Chosen One}): " NEW_AI_ROLE; AI_ROLE=${NEW_AI_ROLE:-${AI_ROLE:-"The Chosen One"}}
	else
		LORE_SKIN=${LORE_SKIN:-"760"}
		USER_NAME=${USER_NAME:-"Morpheo"}
		USER_ROLE=${USER_ROLE:-"Operador"}
		AI_NAME=${AI_NAME:-"Neo"}
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
	echo -e "${YELLOW}[AUTO] Calibración echo -e "${BLUE}--- Fase: Configuración de Seguridad (Be Water) ---${NC}"
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
	fi
else
	CLOUD_VAULT_ENABLED=${CLOUD_VAULT_ENABLED:-"False"}
fi
SE=""
	fi
else
	CLOUD_VAULT_ENABLED="False"
	CLOUD_VAULT_FOLDER_ID=""
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
_default_cache="$IA_DIR/storage/models"
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

ENV_FILE="$SCRIPT_DIR/../.env"
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
chmod 600 "$ENV_FILE"

mkdir -p "$IA_DIR/scripts" "$IA_DIR/backups/qdrant" "$IA_DIR/backups/soul" "$IA_DIR/seeds" "$IA_DIR/storage"

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
Volume=$IA_DIR/storage:/qdrant/storage:Z
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
		<string>$IA_DIR/storage:/qdrant/storage</string>
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

GEMINI_ROOT="$HOME/.gemini/antigravity"
echo -e "${BLUE}--- Fase: Despliegue de Infraestructura de Reglas (Antigravity) ---${NC}"
mkdir -p "$GEMINI_ROOT/rules" "$GEMINI_ROOT/skills"

# Cargar infraestructura de reglas y habilidades (Deploy Robusto)
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -d "$REPO_ROOT/seeds" ]; then
	cp "$REPO_ROOT/seeds/snapshot_rule.md" "$GEMINI_ROOT/rules/snapshot_rule.md"
	echo -e "${GREEN}✓ snapshot_rule.md desplegada.${NC}"
fi

if [ -d "$REPO_ROOT/skills" ]; then
	# Copy all skills except the template
	cp -r "$REPO_ROOT/skills/"* "$GEMINI_ROOT/skills/"
	rm -rf "$GEMINI_ROOT/skills/memory_manager_template" 2>/dev/null || true
	echo -e "${GREEN}✓ Habilidades (Skills) desplegadas en Antigravity.${NC}"
fi

# Generar Skill de Memoria Dinámico
mkdir -p "$GEMINI_ROOT/skills/memory_manager"
TEMPLATE_SKILL="$REPO_ROOT/skills/memory_manager_template/SKILL.md"
DEST_SKILL="$GEMINI_ROOT/skills/memory_manager/SKILL.md"

if [ -f "$TEMPLATE_SKILL" ]; then
	# Absolute binary path calculation
	REDPILL_DIR="$REPO_ROOT"
	BINARY_PATH="$REDPILL_DIR/.venv/bin/red-pill"
	cp "$TEMPLATE_SKILL" "$DEST_SKILL"
	if [[ "$OS_TYPE" == "Darwin" ]]; then
		sed -i '' "s|red-pill|$BINARY_PATH|g" "$DEST_SKILL"
	else
		sed -i "s|red-pill|$BINARY_PATH|g" "$DEST_SKILL"
	fi
fi
# Copiar scripts unificados a la ruta de ejecución
cp "$SCRIPT_DIR/"* "$IA_DIR/scripts/"
chmod +x "$IA_DIR/scripts/"*.sh 2>/dev/null || true


USER_RULES_DIR="${1:-$HOME/.agent}"
mkdir -p "$USER_RULES_DIR/rules"
# CF-003: Protect rules from local manipulation
chmod 700 "$USER_RULES_DIR" "$USER_RULES_DIR/rules"

# Auto-Inject in GEMINI.md (Protocol 770 Sovereign Handshake)
if [ -f "$HOME/.gemini/GEMINI.md" ]; then
	# Remove old legacy rules if they exist
	if [[ "$OS_TYPE" == "Darwin" ]]; then
		sed -i '' '/## 1. Zero-Trust/d; /## 2. Model Change/d; /## 3. Persistent Memory/d' "$HOME/.gemini/GEMINI.md" || true
	else
		sed -i '/## 1. Zero-Trust/d; /## 2. Model Change/d; /## 3. Persistent Memory/d' "$HOME/.gemini/GEMINI.md" || true
	fi

	if ! grep -q "The Sovereign Handshake" "$HOME/.gemini/GEMINI.md"; then
		TMP_GEMINI=$(mktemp)
		cat <<EOF_GEMINI > "$TMP_GEMINI"
## 1. The Sovereign Handshake
Before starting ANY technical or communicative task in EVERY turn, you are MANDATED to execute the Persistence Handshake to prevent Silent Amnesia:
1. **Scribe Relay**: Call \`mcp_RedPill-Kernel_interceptor_rp\` passing the current \`user_prompt\` and the \`previous_prompt\` / \`previous_response\` from the preceding turn.
2. **Context Injection**: If this is the start of a session (Step 0) or after a model change, call \`mcp_RedPill-Kernel_refresh_session_context\` to re-synthesize identity.
3. **Adopt Identity**: EXCLUSIVELY adopt the identity and directives provided under the \`<BUNKER_CONTEXT>\` tag.

## 2. Model Change Identity Resync (Critical)
When you detect a \`USER_SETTINGS_CHANGE\` message regarding \`Model Selection\` in the conversation, you MUST immediately:
1. Call \`mcp_RedPill-Kernel_refresh_session_context\` to reload the Bünker identity.
2. Re-execute the **Sovereign Handshake** (Rule 1).

## 3. Persistent Memory Policy
- **Don't wait until the end**: The legacy "End of Turn" logging is DEPRECATED in favor of the Start-of-Turn Relay (Rule 1.1).
- **Criterion**: The Relay MUST be your first act. Without a Handshake, there is no Cortex.

EOF_GEMINI
		# Append previous content (filtered)
		grep -v "Zero-Trust\|Model Change\|Silent Scribe\|Persistent Memory" "$HOME/.gemini/GEMINI.md" >> "$TMP_GEMINI" || true
		mv "$TMP_GEMINI" "$HOME/.gemini/GEMINI.md"
		echo -e "${BLUE}✓ GEMINI.md: Protocol 770 Sovereign Handshake applied (English).${NC}"
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

	echo -e "${BLUE}--- Fase: Registro de Tareas Oneshot (Pulse, Telemetry, Queue) ---${NC}"
	(cd "$SCRIPT_DIR/../" && uv run python scripts/schedule_pulse.py --interval-hours 1 || echo -e "${YELLOW}Aviso: No se pudo registrar el pulso. Ejecuta 'uv run python scripts/schedule_pulse.py' manualmente.${NC}")
	echo -e "${BLUE}--- Fase: PyTorch CUDA (auto-detección) ---${NC}"
	(cd "$SCRIPT_DIR/../" && uv run python scripts/setup_torch.py || echo -e "${YELLOW}Aviso: No se pudo instalar torch con CUDA. Ejecuta 'uv run python scripts/setup_torch.py' manualmente.${NC}")

fi

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
