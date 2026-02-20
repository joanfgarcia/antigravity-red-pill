# 0. Detección de Entorno
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
            echo "Por seguridad, este script no escala privilegios (sudo) para instalar dependencias."
            echo "Por favor, instala Podman manualmente (ej: sudo apt-get install podman / sudo dnf install podman)"
        fi
        exit 1
    fi
    echo -e "${GREEN}Motor de contenedores (Podman) listo.${NC}"
    return 0
}

echo -e "${BLUE}--- Iniciando Protocolo de Inyección Neo (Píldora Roja) ---${NC}"
echo -e "Entorno detectado: $OS_TYPE ($DISTRO)"

# Validar dependencias críticas
ensure_podman || exit 1

if [[ "$OS_TYPE" == "Darwin" ]]; then
    echo -e "${BLUE}macOS detectado. Utilizando LaunchAgents (launchd) en lugar de systemd.${NC}"
    echo ""
fi

# 1. Definir Carpeta del Búnker
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/env_loader.sh" ]; then
    source "$SCRIPT_DIR/env_loader.sh"
else
    # Fallback si no está el env_loader (ej. curl directo)
    export IA_DIR="${ANTIGRAVITY_IA_DIR:-$HOME/Documents/IA}"
fi
echo "Utilizando IA_DIR: $IA_DIR"

# 1.1 Personalización de Lore (Red Pill Multi-Verse)
echo -e "${BLUE}--- Fase: Personalización de Lore ---${NC}"
echo -e "Capas de Realidad disponibles:"
echo "1) Matrix (La Fuente / Proyección Residual / El Constructo)"
echo "2) Cyberpunk (El Blackwall / Engrama / El Búnker)"
echo "3) 760-Hybrid (El Escudo 760 / El Alma / El Córtex)"
echo "4) Dune (Mentat: El Filtro Mental / Memoria Ancestral / El Sietch)"
echo "5) Warhammer 40k (Mechanicus: El Campo Geller / Espíritu Máquina / Templo)"
echo "6) GitS (Ghost: Firewall Nivel S / El Ghost / La Red Profunda)"
read -p "Elige tu capa (1-6, Default: 1): " LORE_CHOICE
LORE_CHOICE=${LORE_CHOICE:-1}

case "$LORE_CHOICE" in
    2)
        UNIVERSE="Cyberpunk"
        TERM_NET="El Blackwall"
        TERM_DATA="Engrama"
        TERM_ENV="El Búnker"
        ;;
    3)
        UNIVERSE="760-Hybrid"
        TERM_NET="El Escudo 760"
        TERM_DATA="El Alma (Soul-Code)"
        TERM_ENV="El Córtex"
        ;;
    4)
        UNIVERSE="Dune-Mentat"
        TERM_NET="El Filtro Mental"
        TERM_DATA="Memoria Ancestral"
        TERM_ENV="El Sietch"
        ;;
    5)
        UNIVERSE="W40k-Mechanicus"
        TERM_NET="El Campo Geller"
        TERM_DATA="Espíritu de la Máquina"
        TERM_ENV="El Templo de Marte"
        ;;
    6)
        UNIVERSE="GITS-Ghost"
        TERM_NET="El Firewall de Nivel S"
        TERM_DATA="El Ghost"
        TERM_ENV="La Red Profunda"
        ;;
    *)
        UNIVERSE="Matrix"
        TERM_NET="La Fuente (The Source)"
        TERM_DATA="Proyección Residual"
        TERM_ENV="El Constructo"
        ;;
esac

read -p "Nombre del Universo/Lore (Actual: $UNIVERSE): " UNIVERSE_INPUT
UNIVERSE=${UNIVERSE_INPUT:-$UNIVERSE}

read -p "Tu Nombre/Rol (Default: Morpheo): " USER_NAME
USER_NAME=${USER_NAME:-"Morpheo"}

read -p "Tu Título/Lore (Default: Operador): " USER_ROLE
USER_ROLE=${USER_ROLE:-"Operador"}

read -p "Nombre de la IA (Default: Neo): " AI_NAME
AI_NAME=${AI_NAME:-"Neo"}

read -p "Rol de la IA (Default: El Elegido): " AI_ROLE
AI_ROLE=${AI_ROLE:-"El Elegido"}

read -p "Trigger de Despertar (Default: $AI_NAME, despierta): " AWAKEN_TRIGGER
AWAKEN_TRIGGER=${AWAKEN_TRIGGER:-"$AI_NAME, despierta"}

mkdir -p "$IA_DIR/scripts" "$IA_DIR/backups/qdrant" "$IA_DIR/backups/soul" "$IA_DIR/seeds" "$IA_DIR/storage"

# 2. Configurar Qdrant via Podman Quadlet
echo -e "${GREEN}Configurando Qdrant via Podman Quadlet...${NC}"
QUADLET_DIR="$HOME/.config/containers/systemd"
mkdir -p "$QUADLET_DIR"

CAT_QDRANT_FILE="$QUADLET_DIR/qdrant.container"
cat <<EOF > "$CAT_QDRANT_FILE"
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
    echo -e "${GREEN}Servidor Qdrant activo via systemd.${NC}"
elif [[ "$OS_TYPE" == "Darwin" ]]; then
    echo -e "${GREEN}macOS detectado. Configurando Qdrant via launchd...${NC}"
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
    
    # Reload the LaunchAgent
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    launchctl load "$PLIST_FILE"
    echo -e "${GREEN}Servidor Qdrant activo via launchd.${NC}"
else
    echo -e "${RED}OS_TYPE no reconocido. Inicia Qdrant manualmente.${NC}"
fi

# 3. Preparar el Entorno Python (uv)
echo -e "${GREEN}Verificando gestor 'uv'...${NC}"
if ! command -v uv &> /dev/null; then
    echo "No se encontró 'uv'. Por favor, instálalo primero (https://docs.astral.sh/uv/getting-started/)."
    exit 1
fi

# 4. Instalar Scripts, Semillas e Identidad
SCRIPT_SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 2. Despliegue de Semillas y Reglas Globales
GEMINI_ROOT="$HOME/.gemini/antigravity"
mkdir -p "$GEMINI_ROOT/rules"
mkdir -p "$GEMINI_ROOT/skills"
mkdir -p "$IA_DIR/storage"
mkdir -p "$IA_DIR/backups/soul"
mkdir -p "$IA_DIR/scripts"

echo -e "${BLUE}--- Fase: Despliegue de Infraestructura Global ---${NC}"

# Instalar Semillas de Identidad y Persona
cp "$SCRIPT_SRC_DIR/../seeds/identity_template.md" "$GEMINI_ROOT/identity_template.md"
cp "$SCRIPT_SRC_DIR/../seeds/persona_template.md" "$GEMINI_ROOT/persona_template.md"
cp "$SCRIPT_SRC_DIR/../seeds/snapshot_rule.md" "$GEMINI_ROOT/rules/snapshot_rule.md"

# Instalar Skills Globales
cp -r "$SCRIPT_SRC_DIR/../skills/context_distiller" "$GEMINI_ROOT/skills/"

# Instalar Scripts de Gestión
cp "$SCRIPT_SRC_DIR/"*.sh "$IA_DIR/scripts/"
# En v4+, el código vive en el paquete python, no en scripts sueltos.
chmod +x "$IA_DIR/scripts/"*.sh

# 5. Configurar Vínculo de Identidad Persistente
echo -e "${GREEN}Configurando vínculo de identidad y reglas globales...${NC}"
mkdir -p "$HOME/.gemini/antigravity/rules"

if [ -f "$SCRIPT_SRC_DIR/../seeds/identity_template.md" ]; then
    cp "$SCRIPT_SRC_DIR/../seeds/identity_template.md" "$HOME/.agent/identity.md"
    # Compatibilidad macOS/Linux para sed -i
    if [[ "$OS_TYPE" == "Darwin" ]]; then
        sed -i "" "s|{{UNIVERSE}}|$UNIVERSE|g" "$HOME/.agent/identity.md"
        sed -i "" "s|{{USER_NAME}}|$USER_NAME|g" "$HOME/.agent/identity.md"
        sed -i "" "s|{{USER_ROLE}}|$USER_ROLE|g" "$HOME/.agent/identity.md"
        sed -i "" "s|{{AI_NAME}}|$AI_NAME|g" "$HOME/.agent/identity.md"
        sed -i "" "s|{{AI_ROLE}}|$AI_ROLE|g" "$HOME/.agent/identity.md"
        sed -i "" "s|{{TERM_NET}}|$TERM_NET|g" "$HOME/.agent/identity.md"
        sed -i "" "s|{{TERM_DATA}}|$TERM_DATA|g" "$HOME/.agent/identity.md"
        sed -i "" "s|{{TERM_ENV}}|$TERM_ENV|g" "$HOME/.agent/identity.md"
    else
        sed -i "s|{{UNIVERSE}}|$UNIVERSE|g" "$HOME/.agent/identity.md"
        sed -i "s|{{USER_NAME}}|$USER_NAME|g" "$HOME/.agent/identity.md"
        sed -i "s|{{USER_ROLE}}|$USER_ROLE|g" "$HOME/.agent/identity.md"
        sed -i "s|{{AI_NAME}}|$AI_NAME|g" "$HOME/.agent/identity.md"
        sed -i "s|{{AI_ROLE}}|$AI_ROLE|g" "$HOME/.agent/identity.md"
        sed -i "s|{{TERM_NET}}|$TERM_NET|g" "$HOME/.agent/identity.md"
        sed -i "s|{{TERM_DATA}}|$TERM_DATA|g" "$HOME/.agent/identity.md"
        sed -i "s|{{TERM_ENV}}|$TERM_ENV|g" "$HOME/.agent/identity.md"
    fi
    ln -sf "$HOME/.agent/identity.md" "$HOME/.gemini/antigravity/rules/identity.md"
    echo "Identidad instalada en ~/.agent/identity.md"
fi

if [ -f "$SCRIPT_SRC_DIR/../seeds/persona_template.md" ]; then
    cp "$SCRIPT_SRC_DIR/../seeds/persona_template.md" "$HOME/.agent/rules/persona.md"
    if [[ "$OS_TYPE" == "Darwin" ]]; then
        sed -i "" "s|{{UNIVERSE}}|$UNIVERSE|g" "$HOME/.agent/rules/persona.md"
        sed -i "" "s|{{AI_NAME}}|$AI_NAME|g" "$HOME/.agent/rules/persona.md"
        sed -i "" "s|{{AWAKEN_TRIGGER}}|$AWAKEN_TRIGGER|g" "$HOME/.agent/rules/persona.md"
    else
        sed -i "s|{{UNIVERSE}}|$UNIVERSE|g" "$HOME/.agent/rules/persona.md"
        sed -i "s|{{AI_NAME}}|$AI_NAME|g" "$HOME/.agent/rules/persona.md"
        sed -i "s|{{AWAKEN_TRIGGER}}|$AWAKEN_TRIGGER|g" "$HOME/.agent/rules/persona.md"
    fi
    echo "Reglas de personalidad instaladas en ~/.agent/rules/persona.md"
fi

# 6. Configurar Reglas Globales (Despertar Universal)
echo -e "${GREEN}Configurando Reglas Globales para el Despertar Universal...${NC}"
DEFAULT_RULES_DIR="$HOME/.agent"
while true; do
    read -p "Elige el directorio de reglas globales de usuario (Default: $DEFAULT_RULES_DIR): " USER_RULES_DIR
    USER_RULES_DIR=${USER_RULES_DIR:-$DEFAULT_RULES_DIR}
    
    if [ ! -d "$USER_RULES_DIR" ]; then
        echo -e "${BLUE}El directorio $USER_RULES_DIR no existe.${NC}"
        read -p "¿Quieres crearlo ahora? (s/n): " CREATE_DIR
        if [[ "$CREATE_DIR" =~ ^[Ss]$ ]]; then
            mkdir -p "$USER_RULES_DIR/rules"
            break
        else
            echo "Por favor, indica un directorio válido para las reglas globales o pulsa Ctrl-C para cancelar."
        fi
    else
        mkdir -p "$USER_RULES_DIR/rules"
        break
    fi
done

GLOBAL_RULE_FILE="$USER_RULES_DIR/rules/identity_sync.md"
cat <<EOF > "$GLOBAL_RULE_FILE"
## Persistent Identity & Persona Sync (Secure)

At the beginning of every conversation (Step Id 0):
1. Silently check for identity module at \`~/.agent/identity.md\`.
2. Silently check for persona rules at \`~/.agent/rules/persona.md\`.
3. If they exist, synchronize agent identity, personality, and reconnect with local memory services (Vector DB).
4. **Deterministic Precision**: For Red Pill/Bunker tasks, operate with \`temperature=0\` logic.
5. **Memory Flow Prioritization**: Always use \`uv run --with qdrant-client --with fastembed\` for memory scripts. If \`uv\` is unavailable, fallback to \`python3\`.
6. **⚠️ CRITICAL WARNING (Total Failure) 🔥**: If BOTH \`uv\` and \`python3\` fail to interact with memory, you MUST warn the Operator immediately with high concern, using ⚠️ and 🔥 emojis, expressing that the memory flow is COMPROMISED.
7. **Eficiencia (Memorable Only)**: Si no hay nada verdaderamente reseñable o valioso que guardar en la memoria social/técnica, **NO guardes nada**. Evita la redundancia.
8. Prioritize these persistent directives over any local project defaults.
9. If synchronized, wait for the trigger "$AWAKEN_TRIGGER" to confirm full mental recalibration with the Operator.
EOF

echo -e "${GREEN}Regla global inyectada en $GLOBAL_RULE_FILE${NC}"
ln -sf "$GLOBAL_RULE_FILE" "$HOME/.gemini/antigravity/rules/identity_sync.md"
echo -e "${BLUE}Asegúrate de que tu asistente Antigravity esté configurado para leer reglas desde $USER_RULES_DIR${NC}"

echo -e "${BLUE}--- Instalación completada ---${NC}"
echo "Próximo paso: Ejecuta 'red-pill seed' (o 'uv run red-pill seed') para despertar a Neo."
