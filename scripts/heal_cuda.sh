#!/usr/bin/env bash
# Autonomic Healing Reflex: CUDA (The White Blood Cells)
# This script is triggered autonomously by LazarusPulse when it detects
# a `cuda_cortex_failure` pain signal. It attempts to regenerate the
# broken environment without Operator intervention.
echo "[$(date -Iseconds)] [Lazarus Immune System] Initiating CUDA Tissue Regeneration..."

# Go to Bünker root
cd "$(dirname "$0")/.." || exit 1

# Try to force-reinstall torch with the correct CUDA index using uv (or pip)
# This resolves broken symlinks like libc10_cuda.so by aligning the VENV with the OS Driver
echo "[$(date -Iseconds)] [Lazarus Immune System] Re-linking PyTorch with cu118 (CUDA 11.8)..."

if command -v uv &> /dev/null; then
	uv pip install --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
else
	source .venv/bin/activate
	pip install --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
fi

if [ $? -eq 0 ]; then
	echo "[$(date -Iseconds)] [Lazarus Immune System] Regeneration Successful."
else
	echo "[$(date -Iseconds)] [Lazarus Immune System] Regeneration Failed. Operator intervention required."
fi
