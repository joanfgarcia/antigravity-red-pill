#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# force_sleep.sh — Force-trigger the Red Pill Sleep Consolidation Cycle
#
# Usage:
#   ./scripts/force_sleep.sh          # Normal run (cgroup-protected)
#   ./scripts/force_sleep.sh --bare   # Raw run (no cgroup wrapper)
#
# This script can be run by the Operator at any time without needing
# an active AI session. It wraps the same systemd service or falls back
# to a direct invocation with OOM protection.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_FILE="${HOME}/.local/share/red_pill/force_sleep_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$(dirname "${LOG_FILE}")"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  🧠 Red Pill — Forced Sleep Consolidation Cycle     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Timestamp : $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  Log file  : ${LOG_FILE}"
echo ""

# If the service is already running, warn and bail
if systemctl --user is-active --quiet redpill-sleep.service 2>/dev/null; then
	echo "⚠️  redpill-sleep.service is already running. Wait for it to finish or:"
	echo "   systemctl --user stop redpill-sleep.service"
	exit 1
fi

_run_pulse() {
	cd "${PROJECT_DIR}"
	exec "${HOME}/.local/bin/uv" run python "${SCRIPT_DIR}/trigger_pulse.py" --cycle sleep
}

if [[ "${1:-}" == "--bare" ]]; then
	echo "▸ Running in bare mode (no cgroup protection)..."
	echo ""
	_run_pulse 2>&1 | tee "${LOG_FILE}"
else
	echo "▸ Launching with systemd-run cgroup (MemoryMax=10G)..."
	echo ""
	if command -v systemd-run &>/dev/null; then
		systemd-run --user --scope \
			-p MemoryMax=10G \
			--description="Forced Sleep Consolidation" \
			nice -n 10 bash -c "cd '${PROJECT_DIR}' && '${HOME}/.local/bin/uv' run python '${SCRIPT_DIR}/trigger_pulse.py' --cycle sleep" \
			2>&1 | tee "${LOG_FILE}"
	else
		echo "  systemd-run not available, falling back to bare mode..."
		_run_pulse 2>&1 | tee "${LOG_FILE}"
	fi
fi

EXIT_CODE=$?
echo ""
if [[ $EXIT_CODE -eq 0 ]]; then
	echo "✅ Sleep cycle completed. Log: ${LOG_FILE}"
else
	echo "❌ Sleep cycle failed (exit $EXIT_CODE). Check: ${LOG_FILE}"
fi
exit $EXIT_CODE
