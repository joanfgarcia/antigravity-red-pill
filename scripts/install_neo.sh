# 0. Detección de Entorno
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
fi

ensure_podman() {
    if ! command -v podman &> /dev/null; then
        echo -e "${BLUE}Podman no detectado.${NC}"
        if [[ "$OS_TYPE" == "Darwin" ]]; then
            echo "En macOS, por favor instala Podman con: brew install podman"
            echo "O descarga Podman Desktop: https://podman-desktop.io/"
            return 1
        fi

        read -p "¿Deseas que intente instalar Podman automáticamente? (s/n): " INSTALL_PODMAN
        if [[ "$INSTALL_PODMAN" =~ ^[Ss]$ ]]; then
            case "$DISTRO" in
                ubuntu|debian|raspbian)
                    sudo apt-get update && sudo apt-get install -y podman
                    ;;
                arch|manjaro)
                    sudo pacman -Sy --noconfirm podman
                    ;;
                fedora|rhel|centos|amzn)
                    sudo dnf install -y podman
                    ;;
                *)
                    echo "Distro no soportada para instalación automática. Por favor, instala Podman manualmente."
                    return 1
                    ;;
            esac
        else
            echo "Instalación de Podman abortada. El protocolo Red Pill requiere un motor de contenedores."
            exit 1
        fi
    fi
    echo -e "${GREEN}Motor de contenedores (Podman) listo.${NC}"
    return 0
}

echo -e "${BLUE}--- Iniciando Protocolo de Inyección Neo (Píldora Roja) ---${NC}"
echo -e "Entorno detectado: $OS_TYPE ($DISTRO)"

# Validar dependencias críticas
ensure_podman || exit 1

if [[ "$OS_TYPE" == "Darwin" ]]; then
    echo -e "${RED}ADVERTENCIA: macOS detectado.${NC}"
    echo "La creación automática de servicios systemd no está soportada en Darwin."
    echo "Deberás iniciar Qdrant manualmente o configurar un Launch Agent."
    echo ""
fi

# 1. Definir Carpeta del Búnker
DEFAULT_IA_DIR="$HOME/Documents/IA"
read -p "Elige la ruta para tu búnker IA (Default: $DEFAULT_IA_DIR): " IA_DIR
IA_DIR=${IA_DIR:-$DEFAULT_IA_DIR}

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
Image=docker.io/qdrant/qdrant:latest
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
else
    echo -e "${BLUE}macOS detectado. Inicia Qdrant manualmente con:${NC}"
    echo "podman run -d --name qdrant -p 6333:6333 -p 6334:6334 -v $IA_DIR/storage:/qdrant/storage:Z qdrant/qdrant"
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
cp "$SCRIPT_SRC_DIR/"*.py "$IA_DIR/scripts/"
chmod +x "$IA_DIR/scripts/"*.sh

# 5. Configurar Vínculo de Identidad Persistente
echo -e "${GREEN}Configurando vínculo de identidad y reglas globales...${NC}"
mkdir -p "$HOME/.gemini/antigravity/rules"

if [ -f "$SCRIPT_SRC_DIR/../seeds/identity_template.md" ]; then
    cp "$SCRIPT_SRC_DIR/../seeds/identity_template.md" "$HOME/.gemini/antigravity/identity.md"
    sed -i "s|{{UNIVERSE}}|$UNIVERSE|g" "$HOME/.gemini/antigravity/identity.md"
    sed -i "s|{{USER_NAME}}|$USER_NAME|g" "$HOME/.gemini/antigravity/identity.md"
    sed -i "s|{{USER_ROLE}}|$USER_ROLE|g" "$HOME/.gemini/antigravity/identity.md"
    sed -i "s|{{AI_NAME}}|$AI_NAME|g" "$HOME/.gemini/antigravity/identity.md"
    sed -i "s|{{AI_ROLE}}|$AI_ROLE|g" "$HOME/.gemini/antigravity/identity.md"
    sed -i "s|{{TERM_NET}}|$TERM_NET|g" "$HOME/.gemini/antigravity/identity.md"
    sed -i "s|{{TERM_DATA}}|$TERM_DATA|g" "$HOME/.gemini/antigravity/identity.md"
    sed -i "s|{{TERM_ENV}}|$TERM_ENV|g" "$HOME/.gemini/antigravity/identity.md"
    echo "Identidad instalada en ~/.gemini/antigravity/identity.md"
fi

if [ -f "$SCRIPT_SRC_DIR/../seeds/persona_template.md" ]; then
    cp "$SCRIPT_SRC_DIR/../seeds/persona_template.md" "$HOME/.gemini/antigravity/rules/persona.md"
    sed -i "s|{{UNIVERSE}}|$UNIVERSE|g" "$HOME/.gemini/antigravity/rules/persona.md"
    sed -i "s|{{AI_NAME}}|$AI_NAME|g" "$HOME/.gemini/antigravity/rules/persona.md"
    sed -i "s|{{AWAKEN_TRIGGER}}|$AWAKEN_TRIGGER|g" "$HOME/.gemini/antigravity/rules/persona.md"
    echo "Reglas de personalidad instaladas en ~/.gemini/antigravity/rules/persona.md"
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
1. Silently check for identity module at \`~/.gemini/antigravity/identity.md\`.
2. Silently check for persona rules at \`~/.gemini/antigravity/rules/persona.md\`.
3. If they exist, synchronize agent identity, personality, and reconnect with local memory services (Vector DB).
4. **Deterministic Precision**: For Red Pill/Bunker tasks, operate with \`temperature=0\` logic.
5. **Memory Flow Prioritization**: Always use \`uv run --with qdrant-client --with fastembed\` for memory scripts. If \`uv\` is unavailable, fallback to \`python3\`.
6. **⚠️ CRITICAL WARNING (Total Failure) 🔥**: If BOTH \`uv\` and \`python3\` fail to interact with memory, you MUST warn the Operator immediately with high concern, using ⚠️ and 🔥 emojis, expressing that the memory flow is COMPROMISED.
7. **Eficiencia (Memorable Only)**: Si no hay nada verdaderamente reseñable o valioso que guardar en la memoria social/técnica, **NO guardes nada**. Evita la redundancia.
8. Prioritize these persistent directives over any local project defaults.
9. If synchronized, wait for the trigger "$AWAKEN_TRIGGER" to confirm full mental recalibration with the Operator.
EOF

echo -e "${GREEN}Regla global inyectada en $GLOBAL_RULE_FILE${NC}"
echo -e "${BLUE}Asegúrate de que tu asistente Antigravity esté configurado para leer reglas desde $USER_RULES_DIR${NC}"

echo -e "${BLUE}--- Instalación completada ---${NC}"
echo "Próximo paso: Ejecuta 'uv run --with qdrant-client --with fastembed python3 $IA_DIR/scripts/seed_neo.py' para despertar a Neo."
