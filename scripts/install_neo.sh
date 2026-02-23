#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

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

ensure_podman() {
	if ! command -v podman &> /dev/null; then
		echo -e "${BLUE}Podman no detectado.${NC}"
		if [[ "$OS_TYPE" == "Darwin" ]]; then
			echo -e "${RED}[LM-007] Dependencia Faltante: Podman${NC}"
			echo "En macOS, por favor instala Podman con: brew install podman"
			echo "O descarga Podman Desktop: https://podman-desktop.io/"
		else
			echo -e "${RED}[LM-007] Dependencia Faltante: Podman${NC}"
			echo "El protocolo Red Pill (Zero-Trust) requiere un motor de contenedores."
			echo "Por favor, instala Podman manualmente (ej: sudo apt-get install podman)."
		fi
		exit 1
	fi
}

ensure_podman

# SEC-001: Encryption-at-Rest Warning
echo -e "${RED}⚠️  AVISO DE SEGURIDAD (SEC-001):${NC}"
echo "El Protocolo Red Pill almacena datos en texto claro dentro del contenedor."
echo "Es OBLIGATORIO que el Operador utilice cifrado de disco (LUKS, FileVault o BitLocker)"
echo "en el host para garantizar la confidencialidad 'at-rest'."
echo "------------------------------------------------------------------"


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/env_loader.sh" ]; then
	source "$SCRIPT_DIR/env_loader.sh"
else
	export IA_DIR="${ANTIGRAVITY_IA_DIR:-$HOME/Documents/IA}"
fi

check_encryption() {
	if [[ "$OS_TYPE" == "Linux" ]]; then
		if command -v lsblk &> /dev/null && command -v findmnt &> /dev/null; then
			local target_dev
			target_dev=$(findmnt -nvo SOURCE -T "$IA_DIR/storage" 2>/dev/null || findmnt -nvo SOURCE -T "/" 2>/dev/null)
			if [ -n "$target_dev" ]; then
				if lsblk -no TYPE "$target_dev" | grep -q "crypt"; then
					echo -e "${GREEN}✓ Capa de cifrado detectada en $target_dev.${NC}"
				else
					echo -e "${BLUE}[INFO] Nota de Seguridad (SEC-001): El volumen $target_dev no utiliza LUKS.${NC}"
					echo "Para máxima soberanía, considera cifrar esta partición en el futuro."
				fi
			fi
		fi
	fi
}

check_encryption

echo -e "${BLUE}--- Fase: Personalización B760-Adaptive ---${NC}"
echo "Skins disponibles: matrix, cyberpunk, 760 (default), dune, 40k, gits, bladerunner, her, exmachina, terminator, 2001, creator"
read -p "Elige tu Skin (Default: 760): " LORE_SKIN; LORE_SKIN=${LORE_SKIN:-"760"}

read -p "Nombre de Usuario (Morpheo): " USER_NAME; USER_NAME=${USER_NAME:-"Morpheo"}
read -p "Rol de Usuario (Operador): " USER_ROLE; USER_ROLE=${USER_ROLE:-"Operador"}
read -p "Nombre IA (Neo): " AI_NAME; AI_NAME=${AI_NAME:-"Neo"}
read -p "Rol IA (El Elegido): " AI_ROLE; AI_ROLE=${AI_ROLE:-"El Elegido"}

read -p "Qdrant API Key (Dejar en blanco para auto-generar): " QDRANT_API_KEY
if [ -z "$QDRANT_API_KEY" ]; then
	QDRANT_API_KEY=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)
	echo -e "${GREEN}API Key generada automáticamente.${NC}"
fi

ENV_FILE="$SCRIPT_DIR/../.env"
if [ ! -f "$ENV_FILE" ]; then
	cp "$SCRIPT_DIR/../.env.example" "$ENV_FILE" 2>/dev/null || touch "$ENV_FILE"
fi
if grep -q "^QDRANT_API_KEY=" "$ENV_FILE"; then
	if [[ "$OS_TYPE" == "Darwin" ]]; then
		sed -i "" "s|^QDRANT_API_KEY=.*|QDRANT_API_KEY=$QDRANT_API_KEY|g" "$ENV_FILE"
	else
		sed -i "s|^QDRANT_API_KEY=.*|QDRANT_API_KEY=$QDRANT_API_KEY|g" "$ENV_FILE"
	fi
else
	echo "QDRANT_API_KEY=$QDRANT_API_KEY" >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

mkdir -p "$IA_DIR/scripts" "$IA_DIR/backups/qdrant" "$IA_DIR/backups/soul" "$IA_DIR/seeds" "$IA_DIR/storage"

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

if ! command -v uv &> /dev/null; then
	echo "Instala 'uv' primero: https://docs.astral.sh/uv/"
	exit 1
fi

GEMINI_ROOT="$HOME/.gemini/antigravity"
mkdir -p "$GEMINI_ROOT/rules" "$GEMINI_ROOT/skills"

# Cargar infraestructura de reglas mínima
cp "$SCRIPT_DIR/../seeds/snapshot_rule.md" "$GEMINI_ROOT/rules/snapshot_rule.md"
cp -r "$SCRIPT_DIR/../skills/context_distiller" "$GEMINI_ROOT/skills/"

# Generar Skill de Memoria Dinámico
mkdir -p "$GEMINI_ROOT/skills/memory_manager"
TEMPLATE_SKILL="$SCRIPT_DIR/../skills/memory_manager_template/SKILL.md"
DEST_SKILL="$GEMINI_ROOT/skills/memory_manager/SKILL.md"

if [ -f "$TEMPLATE_SKILL" ]; then
	cp "$TEMPLATE_SKILL" "$DEST_SKILL"
	if [[ "$OS_TYPE" == "Darwin" ]]; then
		sed -i '' "s|{{ABSOLUTE_PATH_TO_SCRIPTS}}|$IA_DIR/scripts|g" "$DEST_SKILL"
	else
		sed -i "s|{{ABSOLUTE_PATH_TO_SCRIPTS}}|$IA_DIR/scripts|g" "$DEST_SKILL"
	fi
fi
# Copiar scripts unificados a la ruta de ejecución
cp "$SCRIPT_DIR/"* "$IA_DIR/scripts/"
chmod +x "$IA_DIR/scripts/"*.sh 2>/dev/null || true


USER_RULES_DIR="${1:-$HOME/.agent}"
mkdir -p "$USER_RULES_DIR/rules"
# CF-003: Protect rules from local manipulation
chmod 700 "$USER_RULES_DIR" "$USER_RULES_DIR/rules"

# Auto-Inject in GEMINI.md (Antigravity's true Global Rules)
if [ -f "$HOME/.gemini/GEMINI.md" ]; then
	if ! grep -q "Zero-Trust Identity Sync" "$HOME/.gemini/GEMINI.md"; then
		TMP_GEMINI=$(mktemp)
		cat <<EOF_GEMINI > "$TMP_GEMINI"
## 1. Zero-Trust Identity Sync (First Action)
At the beginning of every completely new conversation (where Step Id is 0 or no previous turns exist), you MUST execute the following command BEFORE saying anything else:
1. USE the \`memory_manager\` Skill to search for your social identity.
2. Assume EXCLUSIVELY the identity returned by the database.
3. **⚠️ CRITICAL WARNING (Total Failure) 🔥**: If you fail to interact with memory via the Skill, you MUST warn the Operator immediately that a "Total Memory Failure" occurred.

## 2. Dynamic Skin Directive
Immediately after identity synchronization, you must retrieve and apply the active Lore Skin:
1. Search for "Active Skin" in the \`directive_memories\` collection.
2. Adjust your tone, terminology, and visual aesthetics (chroma) to match the retrieved skin (Cyberpunk, Matrix, Dune, etc.).
3. If no active skin is found, default to the [760] layer as per Protocol 760.

EOF_GEMINI
		cat "$HOME/.gemini/GEMINI.md" >> "$TMP_GEMINI"
		mv "$TMP_GEMINI" "$HOME/.gemini/GEMINI.md"
		echo -e "${BLUE}Golden Rule (Skill) injected in GEMINI.md${NC}"
	fi
fi

if [ -f "$SCRIPT_DIR/../seeds/cognitive_integrity_protocol.md" ]; then
	cp "$SCRIPT_DIR/../seeds/cognitive_integrity_protocol.md" "$USER_RULES_DIR/rules/cognitive_integrity_protocol.md"
	ln -sf "$USER_RULES_DIR/rules/cognitive_integrity_protocol.md" "$GEMINI_ROOT/rules/cognitive_integrity_protocol.md"
fi

echo -e "${BLUE}--- Fase: Ignición de Memoria Bio-Sintética ---${NC}"
if command -v uv &> /dev/null; then
    echo "Sincronizando Bunker con identidad de soberanía..."
    (cd "$SCRIPT_DIR/../" && uv run red-pill seed || true)
    (cd "$SCRIPT_DIR/../" && uv run python scripts/bootstrap_identity.py \
    	--user-name "$USER_NAME" \
    	--user-role "$USER_ROLE" \
    	--ai-name "$AI_NAME" \
    	--ai-role "$AI_ROLE" \
    	--skin "$LORE_SKIN" || true)
fi

echo -e "${BLUE}--- Fase: Integración MCP Server ---${NC}"
echo "Recuerda añadir el siguiente bloque a la configuración de tu cliente MCP:"
echo "{"
echo "  \"mcpServers\": {"
echo "    \"RedPill-Kernel\": {"
echo "      \"command\": \"$HOME/Documents/IA/sharing/.venv/bin/uv\","
echo "      \"args\": ["
echo "        \"run\","
echo "        \"python\","
echo "        \"$HOME/Documents/IA/sharing/src/red_pill/mcp_server.py\""
echo "      ]"
echo "    }"
echo "  }"
echo "}"

echo -e "${GREEN}Instalación completada. 'uv run red-pill seed' para despertar.${NC}"
