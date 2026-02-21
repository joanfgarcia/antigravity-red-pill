#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/env_loader.sh" ] && source "$SCRIPT_DIR/env_loader.sh" || exit 1

BACKUP_DIR="$IA_DIR/backups/qdrant"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

take_snapshot() {
	local collection=$1
	local response=$(curl -s -X POST "http://localhost:6333/collections/$collection/snapshots" -H "api-key: ${QDRANT_API_KEY:-}")
	
	if echo "$response" | grep -q "error"; then
		echo "Error taking snapshot for $collection: $response"
		return 1
	fi

	local snap_name=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['result']['name'])")
	
	if [ -n "$snap_name" ]; then
		curl -s "http://localhost:6333/collections/$collection/snapshots/$snap_name" \
		     -H "api-key: ${QDRANT_API_KEY:-}" \
		     -o "$BACKUP_DIR/${collection}_${TIMESTAMP}.snapshot"
	fi
}

take_snapshot "social_memories"
take_snapshot "work_memories"
