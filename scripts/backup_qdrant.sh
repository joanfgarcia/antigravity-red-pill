#!/usr/bin/env bash
# ============================================================
# backup_qdrant.sh — Daily Qdrant Snapshot Backup
# Backs up all active collections to the backup dir.
# Retention: keeps last 14 days of snapshots.
# ============================================================
set -euo pipefail

QDRANT_URL="http://localhost:6333"
API_KEY="770-Sovereign-Key-001"
BACKUP_DIR="/home/joan/Documents/IA/backups/qdrant"
RETENTION_DAYS=14
LOG_FILE="${HOME}/.local/share/red_pill/backup.log"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

log() {
	echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== QDRANT BACKUP START (${TIMESTAMP}) ==="

# Check Qdrant is alive
HEALTH=$(curl -sf "${QDRANT_URL}/healthz" -H "api-key: ${API_KEY}" 2>/dev/null) || {
	log "ERROR: Qdrant not reachable at ${QDRANT_URL}"
	exit 1
}
log "Qdrant healthy: ${HEALTH}"

# Get list of collections
COLLECTIONS=$(curl -sf "${QDRANT_URL}/collections" \
	-H "api-key: ${API_KEY}" | \
	python3 -c "import sys, json; data=json.load(sys.stdin); [print(c['name']) for c in data['result']['collections']]")

log "Collections found: $(echo "$COLLECTIONS" | tr '\n' ' ')"

# Snapshot each collection
SUCCESS=0
FAIL=0

for COLLECTION in $COLLECTIONS; do
	SNAP_NAME="${COLLECTION}_${TIMESTAMP}.snapshot"
	log "  Snapshotting: ${COLLECTION} -> ${SNAP_NAME}"

	# Create snapshot via Qdrant API
	SNAP_RESULT=$(curl -sf -X POST \
		"${QDRANT_URL}/collections/${COLLECTION}/snapshots" \
		-H "api-key: ${API_KEY}" \
		-H "Content-Type: application/json" 2>/dev/null) || {
		log "  ERROR: Failed to create snapshot for ${COLLECTION}"
		FAIL=$((FAIL + 1))
		continue
	}

	# Get snapshot name from response
	REMOTE_SNAP=$(echo "$SNAP_RESULT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['result']['name'])" 2>/dev/null) || {
		log "  ERROR: Could not parse snapshot name for ${COLLECTION}"
		FAIL=$((FAIL + 1))
		continue
	}

	# Download snapshot from Qdrant to local backup dir
	DEST="${BACKUP_DIR}/${SNAP_NAME}"
	HTTP_CODE=$(curl -sf -w "%{http_code}" \
		-o "$DEST" \
		"${QDRANT_URL}/collections/${COLLECTION}/snapshots/${REMOTE_SNAP}" \
		-H "api-key: ${API_KEY}" 2>/dev/null) || {
		log "  ERROR: Download failed for ${COLLECTION}"
		FAIL=$((FAIL + 1))
		continue
	}

	SIZE=$(wc -c < "$DEST" 2>/dev/null || echo "?")
	log "  OK: ${SNAP_NAME} (${SIZE} bytes)"
	SUCCESS=$((SUCCESS + 1))

	# Delete snapshot from Qdrant server (cleanup)
	curl -sf -X DELETE \
		"${QDRANT_URL}/collections/${COLLECTION}/snapshots/${REMOTE_SNAP}" \
		-H "api-key: ${API_KEY}" > /dev/null 2>&1 || true
done

# Retention cleanup: remove snapshots older than RETENTION_DAYS
log "Cleaning up snapshots older than ${RETENTION_DAYS} days..."
CLEANED=$(find "$BACKUP_DIR" -name "*.snapshot" -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)
log "  Removed ${CLEANED} old snapshot(s)"

log "=== BACKUP DONE: ${SUCCESS} OK, ${FAIL} FAILED ==="
log ""
