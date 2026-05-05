#!/bin/bash
set -euo pipefail

if [ -z "${APP_ROOT:-}" ]; then
	export APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

# Load .env if it exists
if [ -f "$APP_ROOT/.env" ]; then
	export $(grep -v '^#' "$APP_ROOT/.env" | xargs)
fi

# Backward compatibility for v6.8.7 bash scripts
export IA_DIR="${WORKSPACE_ROOT:-$APP_ROOT}"
