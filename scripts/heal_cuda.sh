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
	# Fallback: detect from nvidia-smi and install cu126 for driver 560+
	DRIVER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | cut -d. -f1)
	if [ -n "$DRIVER" ] && [ "$DRIVER" -ge 560 ]; then
		CUDA_TAG="cu126"
	elif [ -n "$DRIVER" ] && [ "$DRIVER" -ge 530 ]; then
		CUDA_TAG="cu121"
	else
		CUDA_TAG="cu118"
	fi
	echo "[$(date -Iseconds)] [Lazarus Immune System] Driver ${DRIVER}x → installing torch ${CUDA_TAG}..."
	"$UV" pip install --force-reinstall torch --index-url "https://download.pytorch.org/whl/${CUDA_TAG}"
fi

if [ $? -eq 0 ]; then
	echo "[$(date -Iseconds)] [Lazarus Immune System] Regeneration Successful."
else
	echo "[$(date -Iseconds)] [Lazarus Immune System] Regeneration Failed. Operator intervention required."
	exit 1
fi

