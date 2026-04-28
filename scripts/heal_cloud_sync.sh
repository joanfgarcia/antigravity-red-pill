#!/usr/bin/env bash
# heal_cloud_sync.sh — Autonomous CloudSync Healer
# Invoked by the Heartbeat Auto-Healer when a cloud_sync_error PainSignal is detected.
#
# Recovery sequence:
#   1. Verify DNS/network connectivity to Google APIs
#   2. Attempt OAuth2 token refresh via googleapis.com
#   3. Retry the last available Soul Kit upload
#
# Exit codes:
#   0 = healed successfully
#   1 = unrecoverable failure (escalate to Cortex)

set -euo pipefail

LOG_PREFIX="[HEAL_CLOUD_SYNC]"
TOKEN_FILE="$HOME/.agent/credentials/drive_token.json"

# Resolve IA_DIR (same logic as config.py)
IA_DIR="${IA_DIR:-$HOME/Documents/IA/sharing}"
EXPORT_DIR="$IA_DIR/backups/export"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $LOG_PREFIX $*"; }

# ─── Phase 1: Connectivity Check ───
log "Phase 1: Checking network connectivity to Google APIs..."
if ! curl -sf --max-time 10 "https://www.googleapis.com/discovery/v1/apis" > /dev/null 2>&1; then
	log "FAIL: Cannot reach googleapis.com. Network issue. Escalating."
	exit 1
fi
log "Phase 1: OK — googleapis.com reachable."

# ─── Phase 2: Token Refresh ───
log "Phase 2: Checking OAuth2 token validity..."
if [ ! -f "$TOKEN_FILE" ]; then
	log "FAIL: Token file not found at $TOKEN_FILE. Manual re-auth required. Escalating."
	exit 1
fi

# Attempt a lightweight Drive API call to validate the token
# We use the Python runtime since the token refresh logic is in the plugin
VENV_PYTHON="$IA_DIR/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
	log "WARN: venv python not found at $VENV_PYTHON. Trying system python."
	VENV_PYTHON="python3"
fi

TOKEN_CHECK=$($VENV_PYTHON -c "
import json, sys, os
sys.path.insert(0, os.path.join('$IA_DIR', 'src'))
try:
	from google.oauth2.credentials import Credentials
	from google.auth.transport.requests import Request
	creds = Credentials.from_authorized_user_file('$TOKEN_FILE', ['https://www.googleapis.com/auth/drive.file'])
	if not creds.valid:
		if creds.expired and creds.refresh_token:
			creds.refresh(Request())
			with open('$TOKEN_FILE', 'w') as f:
				f.write(creds.to_json())
			print('REFRESHED')
		else:
			print('EXPIRED_NO_REFRESH')
	else:
		print('VALID')
except Exception as e:
	print(f'ERROR:{e}')
" 2>&1)

case "$TOKEN_CHECK" in
	VALID)
		log "Phase 2: Token is valid."
		;;
	REFRESHED)
		log "Phase 2: Token was expired and has been refreshed successfully."
		;;
	EXPIRED_NO_REFRESH)
		log "FAIL: Token expired and no refresh_token available. Manual re-auth required."
		exit 1
		;;
	ERROR:*)
		log "FAIL: Token check error: ${TOKEN_CHECK#ERROR:}"
		exit 1
		;;
	*)
		log "FAIL: Unexpected token check result: $TOKEN_CHECK"
		exit 1
		;;
esac

# ─── Phase 3: Retry Last Export ───
log "Phase 3: Checking for pending Soul Kit in $EXPORT_DIR..."
if [ ! -d "$EXPORT_DIR" ]; then
	log "No export directory found. Nothing to retry. Healed (no action needed)."
	exit 0
fi

# Find the most recent kit file (sorted by modification time)
LATEST_KIT=$(find "$EXPORT_DIR" -maxdepth 1 -type f \( -name "*.gpg" -o -name "*.mls" -o -name "*.tar.gz" \) -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)

if [ -z "$LATEST_KIT" ]; then
	log "No kit files found in $EXPORT_DIR. Nothing to retry. Healed."
	exit 0
fi

log "Found pending kit: $(basename "$LATEST_KIT")"
log "Retry upload via CloudSync plugin..."

UPLOAD_RESULT=$($VENV_PYTHON -c "
import sys, os
sys.path.insert(0, os.path.join('$IA_DIR', 'src'))
try:
	from red_pill.plugins.cloud_sync.plugin import CloudSyncPlugin
	plugin = CloudSyncPlugin()
	if not plugin.service:
		print('NO_SERVICE')
	else:
		from googleapiclient.http import MediaFileUpload
		kit_path = '$LATEST_KIT'
		file_name = os.path.basename(kit_path)
		metadata = {'name': file_name}
		folder_id = plugin.folder_id
		if folder_id:
			metadata['parents'] = [folder_id]
		media = MediaFileUpload(kit_path, mimetype='application/octet-stream', resumable=True)
		result = plugin.service.files().create(body=metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
		print(f'OK:{result.get(\"id\", \"unknown\")}')
except Exception as e:
	print(f'ERROR:{e}')
" 2>&1)

case "$UPLOAD_RESULT" in
	OK:*)
		FILE_ID="${UPLOAD_RESULT#OK:}"
		log "Phase 3: Upload successful! File ID: $FILE_ID"
		log "Healed. CloudSync is operational."
		exit 0
		;;
	NO_SERVICE)
		log "FAIL: CloudSync plugin could not authenticate. Manual intervention required."
		exit 1
		;;
	ERROR:*)
		log "FAIL: Upload retry failed: ${UPLOAD_RESULT#ERROR:}"
		exit 1
		;;
	*)
		log "FAIL: Unexpected upload result: $UPLOAD_RESULT"
		exit 1
		;;
esac
