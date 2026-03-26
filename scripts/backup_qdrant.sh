#!/usr/bin/env bash
# backup_qdrant.sh — Daily Qdrant Snapshot Backup
# Backs up all active collections to the backup dir.
# Retention: keeps last 14 days of snapshots.
set -euo pipefail

QDRANT_URL="http://localhost:6333"
API_KEY="${QDRANT_API_KEY:?ERROR: QDRANT_API_KEY not set. Run the install script to generate it.}"
BACKUP_DIR="${HOME}/Documents/IA/backups/qdrant"
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

# Collections to backup (Default: All)
MODE="all"
while [[ $# -gt 0 ]]; do
	case $1 in
		--soul-only) MODE="soul"; shift ;;
		--chronicle-only) MODE="chronicle"; shift ;;
		*) shift ;;
	esac
done

SOUL_COLLECTIONS="work_memories social_memories directive_memories skill_memories"
CHRONICLE_COLLECTIONS="archive_memories"

if [[ "$MODE" == "soul" ]]; then
	TARGET_COLLECTIONS="$SOUL_COLLECTIONS"
elif [[ "$MODE" == "chronicle" ]]; then
	TARGET_COLLECTIONS="$CHRONICLE_COLLECTIONS"
else
	# Get all collections from API
	TARGET_COLLECTIONS=$(curl -sf "${QDRANT_URL}/collections" \
		-H "api-key: ${API_KEY}" | \
		python3 -c "import sys, json; data=json.load(sys.stdin); [print(c['name']) for c in data['result']['collections']]")
fi

log "Mode: ${MODE} | Targets: $(echo "$TARGET_COLLECTIONS" | tr '\n' ' ')"

# Snapshot each collection
SUCCESS=0
FAIL=0

for COLLECTION in $TARGET_COLLECTIONS; do
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
