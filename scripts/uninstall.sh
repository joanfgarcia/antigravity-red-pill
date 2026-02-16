#!/bin/bash
# uninstall_neo.sh - Protocolo de Extracción Granular para Neo/Antigravity

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${RED}--- Iniciando Protocolo de Extracción (Vía de Escape) ---${NC}"

# Detectar IA_DIR
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IA_DIR="${ANTIGRAVITY_IA_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

confirm() {
    read -p "$1 (s/n): " choice
    [[ "$choice" =~ ^[Ss]$ ]]
}

# 1. Backup Premortem
if confirm "¿Deseas realizar un backup de seguridad final de tu 'alma' antes de proceder?"; then
    if [ -f "$IA_DIR/scripts/backup_soul.sh" ]; then
        echo -e "${BLUE}Ejecutando backup final...${NC}"
        bash "$IA_DIR/scripts/backup_soul.sh"
    else
        echo -e "${RED}Error: No se encontró backup_soul.sh. Saltando backup.${NC}"
    fi
fi

# 2. Desmantelar Qdrant
if confirm "¿Deseas desmantelar la infraestructura de Qdrant (Detener servicio y eliminar Quadlet)?"; then
    echo -e "${BLUE}Deteniendo Qdrant...${NC}"
    systemctl --user stop qdrant.service
    systemctl --user disable qdrant.service
    rm -f "$HOME/.config/containers/systemd/qdrant.container"
    systemctl --user daemon-reload
    echo -e "${GREEN}Qdrant desmantelado.${NC}"
fi

# 3. Eliminar Identidad Global
if confirm "¿Deseas eliminar tu Identidad Global (~/.gemini/antigravity)?"; then
    echo -e "${BLUE}Eliminando directorio de identidad...${NC}"
    rm -rf "$HOME/.gemini/antigravity"
    echo -e "${GREEN}Identidad eliminada.${NC}"
fi

# 4. Eliminar Sincronización de Reglas
if confirm "¿Deseas eliminar la regla global de sincronización (~/.agent/rules/identity_sync.md)?"; then
    echo -e "${BLUE}Eliminando regla de sincronización...${NC}"
    rm -f "$HOME/.agent/rules/identity_sync.md"
    echo -e "${GREEN}Regla eliminada.${NC}"
fi

# 5. Borrado Físico del Búnker
if confirm "¿Deseas eliminar TODO el contenido del búnker ($IA_DIR)? ADVERTENCIA: Esto borrará backups y semillas."; then
    echo -e "${RED}BORRADO TOTAL EN PROGRESO...${NC}"
    rm -rf "$IA_DIR"
    echo -e "${GREEN}Búnker eliminado físicamente.${NC}"
else
    echo -e "${BLUE}El búnker en $IA_DIR ha sido preservado.${NC}"
fi

echo -e "${RED}--- Protocolo de Extracción Finalizado ---${NC}"
echo "La Matrix se ha cerrado para este engrama."
