#!/bin/bash
set -euo pipefail

if [ -z "${IA_DIR:-}" ]; then
	if [ -n "${ANTIGRAVITY_IA_DIR:-}" ]; then
		export IA_DIR="$ANTIGRAVITY_IA_DIR"
	else
		# Default to the root of the project if no explicit IA_DIR is provided
		export IA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
	fi
fi
