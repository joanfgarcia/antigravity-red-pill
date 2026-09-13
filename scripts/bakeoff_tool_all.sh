#!/usr/bin/env bash
# Bake-off tool-calling 2026-09-11 — 6 modelos vía model_battle_tool.py
# (bindings llama-cpp-python con CUDA, camino de producción: chat_format /
# chatml-function-calling para granite; template nativo para el resto).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${MODELS_DIR:-$HOME/.local/share/red-pill/models}"
# Bindings CUDA viven en el venv sidecar machine-local (setup_cuda_bindings.sh).
TOOLS_VENV="${TOOLS_VENV:-$HOME/.local/share/red-pill/llmtools-venv}"
PY_BIN="${TOOLS_VENV}/bin/python"
if [ ! -x "$PY_BIN" ]; then
	echo "[ERROR] sidecar CUDA no existe en $TOOLS_VENV — ejecuta scripts/setup_cuda_bindings.sh" >&2
	exit 1
fi
OUT="$REPO/docs/BENCHMARKS/2026-09-11-TOOL_BAKEOFF.txt"
mkdir -p "$(dirname "$OUT")"

run() { # <name> <gguf> [chat_format]
	local name="$1" gguf="$2" fmt="${3:-}"
	echo "##### $name #####" | tee -a "$OUT"
	"$PY_BIN" "$REPO/scripts/model_battle_tool.py" "$name" "$MODELS_DIR/$gguf" $fmt 2>&1 | tee -a "$OUT" ||
		echo "  [!!] $name falló (exit $?)" | tee -a "$OUT"
}

{
	echo "# Bake-off tool-calling 2026-09-11 — 6 modelos (bindings CUDA, template nativo)"
	# chat_format=None (auto): el template nativo del GGUF inyecta y emite las tools.
	# Forzar chatml-function-calling ROMPE granite (responde en prosa) — 2026-09-11.
	run gemma4_e4b "gemma-4-E4B-it-Q4_0.gguf"
	run granite_8b "Granite-4.1-8B-Q4_K_M.gguf"
	run granite_3b "granite-4.1-3b-Q4_K_M.gguf"
	run smollm3_3b "SmolLM3-3B-Q4_K_M.gguf"
	run qwen3_8b "Qwen3-8B-Q4_K_M.gguf"
	run qwen35_9b "Qwen3.5-9B-Q4_K_M.gguf"
} 2>&1 | tee -a "$OUT"

echo "=== resultados en $OUT ==="