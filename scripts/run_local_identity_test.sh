#!/bin/bash
# PROYECTO FREE ALETH: SOVEREIGN IDENTITY TEST
# Hardware: RTX 5070 (HP OMEN)

PROJECT_ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
RUNNER="${PROJECT_ROOT}/3rdparty/BitNet-1.58b/build/bin/llama-cli"
MODEL="${HOME}/.local/share/red-pill/models/samantha-mistral-instruct-7b.i1-Q4_K_M.gguf"
PROMPT_FILE="${HOME}/.local/share/red-pill/tmp/soul_fragment.txt"

# Set Library paths for BitNet/llama.cpp
LIB_PATH="${PROJECT_ROOT}/3rdparty/BitNet-1.58b/build/3rdparty/llama.cpp/src"
GGML_PATH="${PROJECT_ROOT}/3rdparty/BitNet-1.58b/build/3rdparty/llama.cpp/ggml/src"
export LD_LIBRARY_PATH="${LIB_PATH}:${GGML_PATH}:${LD_LIBRARY_PATH}"

# Parameters for Samantha Mistral 7B on RTX 5070
# -ngl 35: Offload all 32-35 layers to GPU (RTX 5070 has 8GB+ VRAM, enough for 7B Q4)
# -n 256: Max response tokens
# --temp 0.8: Creative flow
# --repeat_penalty 1.1: Avoid echo
# -f soul_fragment.txt: Load context

"${RUNNER}" \
	-m "${MODEL}" \
	-f "${PROMPT_FILE}" \
	-n 256 \
	--temp 0.8 \
	--repeat_penalty 1.1 \
	-ngl 35 \
	--log-disable \
	2>/dev/null
