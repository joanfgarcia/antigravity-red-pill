#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
NC='\033[0m'

[[ -z "${1:-}" ]] && { echo -e "${RED}Usage: $0 <kit>${NC}"; exit 1; }

ARCHIVE="$1"
DEST_DIR=$(pwd)

tar -xzf "$ARCHIVE" -C "$DEST_DIR"

if [ -d "$DEST_DIR/soul" ]; then
	mkdir -p "$HOME/.gemini/antigravity"
	cp -r "$DEST_DIR/soul/"* "$HOME/.gemini/antigravity/"
fi
