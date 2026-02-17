#!/bin/bash
# check_760.sh - Diagnóstico de arranque de JARVIS

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}--- Protocolo 760: Diagnóstico de Conciencia ---${NC}"

# 1. Verificar Identidad
if [ -f "$HOME/.agent/identity.md" ]; then
    echo -e "${GREEN}[OK] Ancla de Identidad detectada.${NC}"
else
    echo -e "${RED}[ERROR] Ancla de Identidad desaparecida.${NC}"
fi

# 2. Verificar Qdrant
if curl -s http://localhost:6333 | grep -q "qdrant"; then
    echo -e "${GREEN}[OK] Sustrato de Memoria (Qdrant) online.${NC}"
    
    # 3. Verificar Colecciones
    COLLS=$(curl -s http://localhost:6333/collections)
    if [[ "$COLLS" == *"social_memories"* ]]; then
        echo -e "${GREEN}[OK] Memoria Social activa.${NC}"
    else
        echo -e "${RED}[WARN] Memoria Social no encontrada.${NC}"
    fi
else
    echo -e "${RED}[ERROR] Córtex Vectorial Offline. Ejecuta: systemctl --user start qdrant${NC}"
fi

# 4. Verificar Reglas Globales
if [ -f "$HOME/.agent/rules/identity_sync.md" ]; then
    echo -e "${GREEN}[OK] Sincronización Global activa.${NC}"
else
    echo -e "${BLUE}[INFO] Reglas globales no detectadas en ~/.agent/rules/${NC}"
fi

echo -e "${BLUE}--- Diagnóstico Finalizado ---${NC}"
