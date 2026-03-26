#!/usr/bin/env bash
# Autonomic Healing Reflex: CUDA (The White Blood Cells)
# Triggered by LazarusPulse on cuda_cortex_failure pain signal.
# Detects system CUDA via setup_torch.py and installs the matching wheel.
echo "[$(date -Iseconds)] [Lazarus Immune System] Initiating CUDA Tissue Regeneration..."

cd "$(dirname "$0")/.." || exit 1

SETUP_TORCH="$(dirname "$0")/setup_torch.py"
UV=$(command -v uv || echo "$HOME/.local/bin/uv")

if [ -f "$SETUP_TORCH" ]; then
	echo "[$(date -Iseconds)] [Lazarus Immune System] Auto-detecting CUDA version..."
	"$UV" run python "$SETUP_TORCH" --auto-fix
else
	echo "[$(date -Iseconds)] [Lazarus Immune System] setup_torch.py not found. Attempting generic install..."
	"$UV" pip install torch
fi

if [ $? -eq 0 ]; then
	echo "[$(date -Iseconds)] [Lazarus Immune System] Regeneration Successful."
else
	echo "[$(date -Iseconds)] [Lazarus Immune System] Regeneration Failed. Operator intervention required."
	exit 1
fi

