#!/usr/bin/env bash
# Bake-off 2026-09-11 — evalúa 3 candidatos de destilación:
#   tiny-aya-global (Q4_K_M), Gemma-4-E4B-it (Q4_0), DeepSeek-R1-Distill-Qwen-7B (Q4_K_M)
#
# Descarga los GGUFs (reanudable vía wget -c), para el daemon para liberar VRAM,
# corre el harness CLI (model_battle_cli.py + distiller_v3_voice MODE B) y
# reinicia el daemon. Uso: bash scripts/bakeoff_new_models.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${MODELS_DIR:-$HOME/.local/share/red-pill/models}"
PROMPT="$REPO/src/red_pill/metabolism/prompts/distiller_v3_voice.txt"
DATE="$(date +%Y-%m-%d)"
OUT="$REPO/docs/BENCHMARKS/${DATE}-NEW_MODELS_BAKEOFF.txt"

mkdir -p "$MODELS_DIR"
trap 'systemctl --user start redpill-llm.service >/dev/null 2>&1 || true' EXIT

dl() { # <url> <fname>
	local url="$1"
	local fname="$2"
	local dest="$MODELS_DIR/$fname"
	if [ -f "$dest" ] && [ -s "$dest" ]; then
		echo "[dl] $fname ya presente ($(stat -c%s "$dest") bytes)"
		return 0
	fi
	echo "[dl] descargando $fname ..."
	wget -q -c -O "$dest.part" "$url"
	mv "$dest.part" "$dest"
	echo "[dl] $fname OK ($(stat -c%s "$dest") bytes)"
}

run_bakeoff() { # <label> <gguf>
	local label="$1" gguf="$2"
	echo "##### $label #####"
	"$REPO/.venv/bin/python" "$REPO/scripts/model_battle_cli.py" "$label" "$MODELS_DIR/$gguf" "$PROMPT" 2>&1 ||
		echo "  [!!] bake-off $label falló (exit $?)"
}

echo "=== [1/4] Descargas ==="
dl "https://huggingface.co/CohereLabs/tiny-aya-global-GGUF/resolve/main/tiny-aya-global-q4_k_m.gguf" "tiny-aya-global-q4_k_m.gguf" &
P1=$!
dl "https://huggingface.co/ggml-org/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_0.gguf" "gemma-4-E4B-it-Q4_0.gguf" &
P2=$!
dl "https://huggingface.co/unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf" "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf" &
P3=$!
wait "$P1" "$P2" "$P3"

echo "=== [2/4] Paro daemon para liberar VRAM ==="
systemctl --user stop redpill-llm.service || true
sleep 3

echo "=== [3/4] Bake-offs ==="
{
	echo "# Bake-off $DATE — candidatos nuevos"
	echo "# prompt: $PROMPT"
	run_bakeoff tiny_aya "tiny-aya-global-q4_k_m.gguf"
	run_bakeoff gemma4_e4b "gemma-4-E4B-it-Q4_0.gguf"
	run_bakeoff r1_distill "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf"
} 2>&1 | tee "$OUT"

echo "=== [4/4] Resultados en $OUT ==="