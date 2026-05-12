#!/bin/bash
set -euo pipefail

if [ -z "${APP_ROOT:-}" ]; then
	export APP_ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
fi

# Load .env if it exists
ENV_FILE="$HOME/.config/red-pill/.env"
if [ -f "$ENV_FILE" ]; then
	export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

# Backward compatibility for v6.8.7 bash scripts
export IA_DIR="${WORKSPACE_ROOT:-$APP_ROOT}"
