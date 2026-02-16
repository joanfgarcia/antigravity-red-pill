#!/bin/bash
# backup_qdrant.sh - Trigger a snapshot of the Qdrant database

# Determinar la ruta base (IA_DIR)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Si estamos en ~/Documents/IA/sharing/scripts, subimos dos niveles para llegar a ~/Documents/IA
POTENTIAL_IA_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [[ "$POTENTIAL_IA_DIR" == *"IA" ]]; then
    IA_DIR="$POTENTIAL_IA_DIR"
else
    IA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
IA_DIR="${ANTIGRAVITY_IA_DIR:-$IA_DIR}"
BACKUP_DIR="$IA_DIR/backups/qdrant"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

echo "Iniciando Snapshot de Qdrant..."

# Trigger snapshot via API
curl -X POST "http://localhost:6333/collections/social_memories/snapshots" -o "$BACKUP_DIR/social_memories_$TIMESTAMP.snapshot"
curl -X POST "http://localhost:6333/collections/work_memories/snapshots" -o "$BACKUP_DIR/work_memories_$TIMESTAMP.snapshot"

echo "Snapshot completado en $BACKUP_DIR"
