#!/bin/bash
set -euo pipefail

if [ -z "${IA_DIR:-}" ]; then
	if [ -n "${ANTIGRAVITY_IA_DIR:-}" ]; then
		export IA_DIR="$ANTIGRAVITY_IA_DIR"
	else
		_POTENTIAL_IA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
		if [[ "$_POTENTIAL_IA_DIR" == "$HOME/.gemini/antigravity" ]] || [[ "$_POTENTIAL_IA_DIR" == *"Documents/IA/sharing" ]]; then
			export IA_DIR="$_POTENTIAL_IA_DIR"
		else
			echo "Error: Path not in allow-list. Set ANTIGRAVITY_IA_DIR explicitly." >&2
			exit 1
		fi
	fi
fi
