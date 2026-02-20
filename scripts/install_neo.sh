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

echo -e "${BLUE}--- Protocolo de Inyección Neo ---${NC}"
ensure_podman

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/env_loader.sh" ]; then
	source "$SCRIPT_DIR/env_loader.sh"
else
	export IA_DIR="${ANTIGRAVITY_IA_DIR:-$HOME/Documents/IA}"
fi

echo -e "${BLUE}--- Fase: Personalización de Lore ---${NC}"
echo "1) Matrix (La Fuente / El Constructo)"
echo "2) Cyberpunk (El Blackwall / El Búnker)"
echo "3) 760-Hybrid (El Escudo 760 / El Córtex)"
echo "4) Dune (El Filtro Mental / El Sietch)"
echo "5) Warhammer 40k (El Campo Geller / El Templo)"
echo "6) GitS (La Red Profunda / El Ghost)"
read -p "Elige tu capa (1-6, Default: 1): " LORE_CHOICE
LORE_CHOICE=${LORE_CHOICE:-1}

case "$LORE_CHOICE" in
	2) UNIVERSE="Cyberpunk"; TERM_NET="El Blackwall"; TERM_DATA="Engrama"; TERM_ENV="El Búnker" ;;
	3) UNIVERSE="760-Hybrid"; TERM_NET="El Escudo 760"; TERM_DATA="Soul-Code"; TERM_ENV="El Córtex" ;;
	4) UNIVERSE="Dune-Mentat"; TERM_NET="El Filtro Mental"; TERM_DATA="Memoria Ancestral"; TERM_ENV="El Sietch" ;;
	5) UNIVERSE="W40k-Mechanicus"; TERM_NET="El Campo Geller"; TERM_DATA="Espíritu Máquina"; TERM_ENV="El Templo" ;;
	6) UNIVERSE="GITS-Ghost"; TERM_NET="Firewall Nivel S"; TERM_DATA="El Ghost"; TERM_ENV="La Red Profunda" ;;
	*) UNIVERSE="Matrix"; TERM_NET="La Fuente"; TERM_DATA="Proyección Residual"; TERM_ENV="El Constructo" ;;
esac

read -p "Universo/Lore ($UNIVERSE): " UNIVERSE_IN; UNIVERSE=${UNIVERSE_IN:-$UNIVERSE}
read -p "Nombre de Usuario (Morpheo): " USER_NAME; USER_NAME=${USER_NAME:-"Morpheo"}
read -p "Rol de Usuario (Operador): " USER_ROLE; USER_ROLE=${USER_ROLE:-"Operador"}
read -p "Nombre IA (Neo): " AI_NAME; AI_NAME=${AI_NAME:-"Neo"}
read -p "Rol IA (El Elegido): " AI_ROLE; AI_ROLE=${AI_ROLE:-"El Elegido"}
read -p "Trigger (Neo, despierta): " AWAKEN_TRIGGER; AWAKEN_TRIGGER=${AWAKEN_TRIGGER:-"$AI_NAME, despierta"}

mkdir -p "$IA_DIR/scripts" "$IA_DIR/backups/qdrant" "$IA_DIR/backups/soul" "$IA_DIR/seeds" "$IA_DIR/storage"

QUADLET_DIR="$HOME/.config/containers/systemd"
mkdir -p "$QUADLET_DIR"
cat <<EOF > "$QUADLET_DIR/qdrant.container"
[Unit]
Description=Qdrant Vector Database
After=network-online.target

[Container]
Image=docker.io/qdrant/qdrant:v1.9.0
PublishPort=6333:6333
PublishPort=6334:6334
Volume=$IA_DIR/storage:/qdrant/storage:Z

[Service]
Restart=always

[Install]
WantedBy=default.target
EOF

if [[ "$OS_TYPE" == "Linux" ]]; then
	systemctl --user daemon-reload
	systemctl --user enable --now qdrant.service
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
		<string>--rm</string>
		<string>--name</string>
		<string>qdrant_mac</string>
		<string>-p</string>
		<string>6333:6333</string>
		<string>-p</string>
		<string>6334:6334</string>
		<string>-v</string>
		<string>$IA_DIR/storage:/qdrant/storage</string>
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

cp "$SCRIPT_DIR/../seeds/identity_template.md" "$GEMINI_ROOT/identity_template.md"
cp "$SCRIPT_DIR/../seeds/persona_template.md" "$GEMINI_ROOT/persona_template.md"
cp "$SCRIPT_DIR/../seeds/snapshot_rule.md" "$GEMINI_ROOT/rules/snapshot_rule.md"
cp -r "$SCRIPT_DIR/../skills/context_distiller" "$GEMINI_ROOT/skills/"
cp "$SCRIPT_DIR/"*.sh "$IA_DIR/scripts/"
chmod +x "$IA_DIR/scripts/"*.sh

cp "$GEMINI_ROOT/identity_template.md" "$HOME/.agent/identity.md"
if [[ "$OS_TYPE" == "Darwin" ]]; then
	sed -i "" "s|{{UNIVERSE}}|$UNIVERSE|g;s|{{USER_NAME}}|$USER_NAME|g;s|{{USER_ROLE}}|$USER_ROLE|g;s|{{AI_NAME}}|$AI_NAME|g;s|{{AI_ROLE}}|$AI_ROLE|g;s|{{TERM_NET}}|$TERM_NET|g;s|{{TERM_DATA}}|$TERM_DATA|g;s|{{TERM_ENV}}|$TERM_ENV|g" "$HOME/.agent/identity.md"
else
	sed -i "s|{{UNIVERSE}}|$UNIVERSE|g;s|{{USER_NAME}}|$USER_NAME|g;s|{{USER_ROLE}}|$USER_ROLE|g;s|{{AI_NAME}}|$AI_NAME|g;s|{{AI_ROLE}}|$AI_ROLE|g;s|{{TERM_NET}}|$TERM_NET|g;s|{{TERM_DATA}}|$TERM_DATA|g;s|{{TERM_ENV}}|$TERM_ENV|g" "$HOME/.agent/identity.md"
fi
ln -sf "$HOME/.agent/identity.md" "$GEMINI_ROOT/rules/identity.md"

cp "$GEMINI_ROOT/persona_template.md" "$HOME/.agent/rules/persona.md"
if [[ "$OS_TYPE" == "Darwin" ]]; then
	sed -i "" "s|{{UNIVERSE}}|$UNIVERSE|g;s|{{AI_NAME}}|$AI_NAME|g;s|{{AWAKEN_TRIGGER}}|$AWAKEN_TRIGGER|g" "$HOME/.agent/rules/persona.md"
else
	sed -i "s|{{UNIVERSE}}|$UNIVERSE|g;s|{{AI_NAME}}|$AI_NAME|g;s|{{AWAKEN_TRIGGER}}|$AWAKEN_TRIGGER|g" "$HOME/.agent/rules/persona.md"
fi

USER_RULES_DIR="${1:-$HOME/.agent}"
mkdir -p "$USER_RULES_DIR/rules"

GLOBAL_RULE_FILE="$USER_RULES_DIR/rules/identity_sync.md"
cat <<EOF > "$GLOBAL_RULE_FILE"
## Persistent Identity & Persona Sync (Secure)
At the beginning of every conversation:
1. Sync identity from \`~/.agent/identity.md\` and persona from \`~/.agent/rules/persona.md\`.
2. Connect with local Vector DB services.
3. For Red Pill tasks, use \`temperature=0\`.
4. Prioritize \`uv run --with qdrant-client --with fastembed\`.
5. ⚠️ FIRE WARNING if memory services are inaccessible.
6. Only record valuable unique engrams. Avoid redundancy.
7. Wait for trigger "$AWAKEN_TRIGGER" to confirm recalibration.
EOF

ln -sf "$GLOBAL_RULE_FILE" "$GEMINI_ROOT/rules/identity_sync.md"

if [ -f "$SCRIPT_DIR/../seeds/cognitive_integrity_protocol.md" ]; then
	cp "$SCRIPT_DIR/../seeds/cognitive_integrity_protocol.md" "$USER_RULES_DIR/rules/cognitive_integrity_protocol.md"
	ln -sf "$USER_RULES_DIR/rules/cognitive_integrity_protocol.md" "$GEMINI_ROOT/rules/cognitive_integrity_protocol.md"
fi

echo -e "${BLUE}Instalación completada. 'red-pill seed' para despertar.${NC}"
