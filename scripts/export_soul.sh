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

TEMP_EXPORT=$(mktemp -d -t soul_export_XXXXXXXX)
mkdir -p "$TEMP_EXPORT/soul"

cp -r "$IA_DIR/"* "$TEMP_EXPORT/"
rm -rf "$TEMP_EXPORT/backups/export"
cp -r "$HOME/.gemini/antigravity/"* "$TEMP_EXPORT/soul/"

tar -cz -C "$TEMP_EXPORT" . | gpg --symmetric --cipher-algo AES256 --batch --yes --passphrase-fd 0 -o "$ARCHIVE" < /dev/tty || {
	tar -cz -C "$TEMP_EXPORT" . | gpg --symmetric --cipher-algo AES256 -o "$ARCHIVE"
}

rm -rf "$TEMP_EXPORT"
echo -e "\nKit: $ARCHIVE"
