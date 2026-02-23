#!/bin/bash
set -euo pipefail

if [ -z "${IA_DIR:-}" ]; then
	if [ -n "${ANTIGRAVITY_IA_DIR:-}" ]; then
		export IA_DIR="$ANTIGRAVITY_IA_DIR"
	else
		export IA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
	fi
fi

# Load .env if it exists
if [ -f "$IA_DIR/.env" ]; then
	export $(grep -v '^#' "$IA_DIR/.env" | xargs)
fi
