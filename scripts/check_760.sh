#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/env_loader.sh" ] && source "$SCRIPT_DIR/env_loader.sh"

echo -e "${BLUE}--- Protocolo 760: Diagnóstico ---${NC}"

if command -v grep &> /dev/null && [ -f "$HOME/.gemini/GEMINI.md" ] && grep -q "REDPILL:BEGIN sovereign_handshake" "$HOME/.gemini/GEMINI.md"; then
	echo -e "${GREEN}[OK] GEMINI.md Zero-Trust Activo.${NC}"
else
	echo -e "${RED}[ERROR] GEMINI.md inyectado incorrectamente o ausente.${NC}"
fi

if curl -s http://localhost:6333 -H "api-key: ${QDRANT_API_KEY:-}" | grep -q "qdrant"; then
	echo -e "${GREEN}[OK] Qdrant online.${NC}"
	COLLS=$(curl -s http://localhost:6333/collections -H "api-key: ${QDRANT_API_KEY:-}")
	[[ "$COLLS" == *"social_memories"* ]] && echo -e "${GREEN}[OK] Social activa.${NC}"
else
	echo -e "${RED}[ERROR] Qdrant offline.${NC}"
fi

