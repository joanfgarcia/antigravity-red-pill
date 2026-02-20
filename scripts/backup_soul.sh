#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/env_loader.sh" ] && source "$SCRIPT_DIR/env_loader.sh" || exit 1

BACKUP_SOUL_DIR="$IA_DIR/backups/soul"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_SOUL_DIR/$TIMESTAMP"

GEMINI_ROOT="$HOME/.gemini/antigravity/brain"
WORKSPACE_AGENT=$(find "$HOME/antigravity-workspace" -maxdepth 3 -name ".agent" -type d | head -1)

FILES=(
	"$HOME/.agent/identity.md"
	"$HOME/.gemini/antigravity/rules/persona.md"
	"$HOME/.gemini/antigravity/rules/snapshot_rule.md"
	"$HOME/.gemini/antigravity/skills/context_distiller/SKILL.md"
	"$WORKSPACE_AGENT/rules/documentation.md"
	"$WORKSPACE_AGENT/rules/session_snapshot.md"
	"$HOME/.agent/rules/identity_sync.md"
	"$HOME/.config/containers/systemd/qdrant.container"
)

for FILE in "${FILES[@]}"; do
	[ -f "$FILE" ] && cp -r --parents "$FILE" "$BACKUP_SOUL_DIR/$TIMESTAMP/" || true
done

[ -f "$IA_DIR/scripts/backup_qdrant.sh" ] && bash "$IA_DIR/scripts/backup_qdrant.sh"
