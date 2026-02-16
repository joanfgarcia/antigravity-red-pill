#!/bin/bash
# forge_pill.sh - El Martillo de la Forja 760
# Propósito: Empaquetar la esencia pura del Proyecto Red Pill para su distribución universal.

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}--- [PROTOCOLO 760: FORJA DEL CÓDICE] ---${NC}"

# 1. Localizar la Raíz de la Realidad (Sharing Root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARING_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$(cd "$SHARING_ROOT/.." && pwd)"
OUTPUT_FILE="$OUTPUT_DIR/red_pill_distribution.tar.gz"

echo -e "Extrayendo pureza desde: ${SHARING_ROOT}"

# 2. La Purga de Sbras (Limpiar archivos temporales o innecesarios)
# No queremos basura en la distribución oficial
find "$SHARING_ROOT" -name "*.pyc" -delete
find "$SHARING_ROOT" -name "__pycache__" -delete

# 3. El Acto de Compresión (Empaquetado Plano)
# Usamos -C para que el tar contenga el interior de sharing, no la carpeta sharing en sí.
echo -e "${BLUE}Comprimiendo engramas en: ${OUTPUT_FILE}...${NC}"

tar -C "$SHARING_ROOT" -czf "$OUTPUT_FILE" .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}[ÉXITO] La Píldora Roja ha sido forjada.${NC}"
    echo -e "Ubicación del artefacto: ${OUTPUT_FILE}"
    echo -e "Tamaño: $(du -h "$OUTPUT_FILE" | cut -f1)"
else
    echo -e "${RED}[ERROR] La forja ha fallado. Revisa los permisos de la simulación.${NC}"
    exit 1
fi

echo -e "${BLUE}--- SOBERANÍA 760 GARANTIZADA ---${NC}"
