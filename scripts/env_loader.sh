#!/bin/bash
set -euo pipefail

if [ -z "${IA_DIR:-}" ]; then
	_POTENTIAL_IA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
	if [[ "$_POTENTIAL_IA_DIR" != *"IA"* ]] && [[ "$_POTENTIAL_IA_DIR" != *"antigravity"* ]]; then
		_POTENTIAL_IA_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
	fi
	export IA_DIR="${ANTIGRAVITY_IA_DIR:-$_POTENTIAL_IA_DIR}"
fi
