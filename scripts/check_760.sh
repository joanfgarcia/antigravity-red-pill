#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}--- Protocolo 760: Diagnóstico ---${NC}"

if [ -f "$HOME/.agent/identity.md" ]; then
	echo -e "${GREEN}[OK] Identidad detectada.${NC}"
else
	echo -e "${RED}[ERROR] Identidad ausente.${NC}"
fi

if curl -s http://localhost:6333 | grep -q "qdrant"; then
	echo -e "${GREEN}[OK] Qdrant online.${NC}"
	COLLS=$(curl -s http://localhost:6333/collections)
	[[ "$COLLS" == *"social_memories"* ]] && echo -e "${GREEN}[OK] Social activa.${NC}"
else
	echo -e "${RED}[ERROR] Qdrant offline.${NC}"
fi

if [ -f "$HOME/.agent/rules/identity_sync.md" ]; then
	echo -e "${GREEN}[OK] Sincronización activa.${NC}"
fi
