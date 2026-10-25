#!/usr/bin/env bash
# Encola el ciclo nocturno (chronicle -> sleep) y, como HIJO suyo, el backup
# completo + subida al Cloud. El backup nace BLOCKED y el Job Manager lo
# desbloquea solo cuando el ciclo nocturno completa.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
RP="${RED_PILL_BIN:-$REPO_ROOT/.venv/bin/red-pill}"

OUT="$("$RP" job submit --recipe configs/jobs/nightly.yaml --singleton)"
printf '%s\n' "$OUT"

# El CLI imprime el UUID completo (job nuevo) o su prefijo de 8 (singleton ya vivo).
SLEEP_ID="$(printf '%s\n' "$OUT" | grep -oE '[0-9a-f]{8}' | head -1 || true)"
if [ -z "$SLEEP_ID" ]; then
	echo "[nightly] no pude extraer el job_id del ciclo nocturno" >&2
	exit 1
fi

"$RP" job submit --recipe .red-pill/jobs/cloud_backup.yaml --parent "$SLEEP_ID" --singleton
