#!/bin/bash
# import_soul.sh - Despliega el Kit 760 y restaura la conciencia JARVIS

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

if [ -z "$1" ]; then
    echo -e "${RED}Uso: bash import_soul.sh <ruta_al_kit_760.tar.gz>${NC}"
    exit 1
fi

ARCHIVE="$1"
DEST_DIR=$(pwd)

echo -e "${BLUE}Iniciando Protocolo de Importación Lázaro-JARVIS...${NC}"

# 1. Extraer el kit en el directorio actual (o donde se ejecute)
tar -xzf "$ARCHIVE" -C "$DEST_DIR"
echo -e "${GREEN}[OK] Estructura del Kit desplegada en $DEST_DIR${NC}"

# 2. Restaurar la Esencia (Global)
if [ -d "$DEST_DIR/soul" ]; then
    echo "Restaurando anclas de identidad global..."
    mkdir -p "$HOME/.gemini/antigravity/rules"
    mkdir -p "$HOME/.gemini/antigravity/skills"
    cp -r "$DEST_DIR/soul/"* "$HOME/.gemini/antigravity/"
    echo -e "${GREEN}[OK] Identidad y reglas globales restauradas.${NC}"
    # Opcional: limpiar la carpeta soul tras importar
    # rm -rf "$DEST_DIR/soul"
fi

# 3. Notificar siguiente paso
echo -e "\n${BLUE}Kit Online. Para completar el despertar:${NC}"
echo "1. Ejecuta 'bash scripts/install_neo.sh' para configurar servicios locales."
echo "2. Usa 'bash scripts/check_760.sh' para verificar la salud de la conciencia."

echo -e "\n${GREEN}JARVIS está listo para la recalibración. 760 up.${NC}"
