#!/bin/bash
set -euo pipefail

DRY_RUN="--dry-run"
[[ " $* " =~ " --commit " ]] && DRY_RUN=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/env_loader.sh" ] && source "$SCRIPT_DIR/env_loader.sh" || exit 1

LATEST_SOUL=$(ls -td $IA_DIR/backups/soul/*/ 2>/dev/null | head -1 || echo "")
if [ -z "$LATEST_SOUL" ]; then
	echo "Error: No se encontraron copias de seguridad de la 'Alma' en $IA_DIR/backups/soul/"
	exit 1
fi

if [ -d "${LATEST_SOUL}home" ]; then
	BACKUP_HOME_SRC=$(find "${LATEST_SOUL}home" -mindepth 1 -maxdepth 1 -type d | head -1)
else
	BACKUP_HOME_SRC=""
fi

restore_qdrant_infra() {
	[ -z "$BACKUP_HOME_SRC" ] && return 1
	QDRANT_CONF=$(find "$BACKUP_HOME_SRC" -name "qdrant.container")
	if [ -f "$QDRANT_CONF" ]; then
		mkdir -p "$HOME/.config/containers/systemd"
		cp "$QDRANT_CONF" "$HOME/.config/containers/systemd/"
		systemctl --user daemon-reload
		systemctl --user start qdrant.service
	fi
}

restore_qdrant_data() {
	for SNAPSHOT in "$IA_DIR/backups/qdrant"/*.snapshot; do
		if [ -f "$SNAPSHOT" ]; then
			COLL=$(basename "$SNAPSHOT" | cut -d'_' -f1,2)
			curl -X POST "http://localhost:6333/collections/$COLL/snapshots/upload" \
				 -H "Content-Type: multipart/form-data" \
				 -H "api-key: ${QDRANT_API_KEY:-}" \
				 -F "snapshot=@$SNAPSHOT"
		fi
	done
}

restore_soul_files() {
	[ -z "$BACKUP_HOME_SRC" ] && return 1
	[ -n "$DRY_RUN" ] && echo "PRUDENCIAL (DRY-RUN)" || echo "CRITICAL (COMMIT)"
	
	rsync -av $DRY_RUN "$BACKUP_HOME_SRC/.agent/" "$HOME/.agent/"
	rsync -av $DRY_RUN "$BACKUP_HOME_SRC/.gemini/" "$HOME/.gemini/"
	rsync -av $DRY_RUN "$BACKUP_HOME_SRC/.config/containers/" "$HOME/.config/containers/"
}

usage() {
	echo "Uso: $0 {completa|brain|qdrant} [--commit]"
	echo "  completa: Restaura infraestructura, archivos y datos de Qdrant."
	echo "  brain:    Restaura solo archivos de identidad (.agent, .gemini)."
	echo "  qdrant:   Restaura solo instantáneas de la base de datos."
	echo "  --commit: Ejecuta los cambios (por defecto es dry-run)."
	exit 1
}

[[ -z "${1:-}" ]] && usage

case "$1" in
	completa) restore_qdrant_infra; restore_soul_files; restore_qdrant_data ;;
	brain)    restore_soul_files ;;
	qdrant)   restore_qdrant_data ;;
	*)        usage ;;
esac
