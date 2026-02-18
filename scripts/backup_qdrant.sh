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

# Function to perform two-step snapshot (create + download)
take_snapshot() {
    local collection=$1
    echo "Triggering snapshot for $collection..."
    
    # 1. POST to create snapshot and capture response
    local response=$(curl -s -X POST "http://localhost:6333/collections/$collection/snapshots")
    
    # 2. Extract snapshot name using python
    local snap_name=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['result']['name'])")
    
    if [ -n "$snap_name" ]; then
        echo "Downloading snapshot: $snap_name"
        # 3. GET to download binary
        curl -s "http://localhost:6333/collections/$collection/snapshots/$snap_name" -o "$BACKUP_DIR/${collection}_${TIMESTAMP}.snapshot"
        echo "Success: $collection snapshot saved."
    else
        echo "Error: Failed to create snapshot for $collection. Response: $response"
    fi
}

take_snapshot "social_memories"
take_snapshot "work_memories"

echo "Backup process finished in $BACKUP_DIR"
