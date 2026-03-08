#!/bin/zsh
# Red Pill CUDA Rehabilitation Script (v6.0)
# Fixes library paths for RTX 50 series cuDNN 9 compatibility.

CUDNN_PATH="/usr/local/lib/ollama/mlx_cuda_v13"

if [ -d "$CUDNN_PATH" ]; then
    export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$CUDNN_PATH"
    echo "[OK] cuDNN 9 path injected: $CUDNN_PATH"
else
    echo "[WARN] cuDNN 9 path not found at $CUDNN_PATH. Check manual installation."
fi

# Re-run daemon or other tools
# nohup .venv/bin/python src/red_pill/memory_daemon.py > /tmp/memory_daemon.log 2>&1 &
