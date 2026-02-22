#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/env_loader.sh" ] && source "$SCRIPT_DIR/env_loader.sh" || exit 1

EXPORT_DIR="$IA_DIR/backups/export"
AI_NAME=$(grep "\- \*\*Designación\*\*" "$HOME/.agent/identity.md" | cut -d':' -f2 | xargs | cut -d' ' -f1 || echo "RED_PILL")
TIMESTAMP=$(date +%Y%m%d)
ARCHIVE="$EXPORT_DIR/${AI_NAME}_SOUL_KIT_$TIMESTAMP.tar.gz.gpg"

mkdir -p "$EXPORT_DIR"
bash "$SCRIPT_DIR/backup_soul.sh"

tar -cz -C "$IA_DIR" . -C "$HOME/.gemini" antigravity | gpg --symmetric --batch --yes --cipher-algo AES256 -o "$ARCHIVE"
echo -e "\nKit: $ARCHIVE"
