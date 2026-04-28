#!/bin/bash
# PROYECTO FREE ALETH: MASTER FORGE (EL MOTOR CUÁDRUPLE)
# Este script compila los 4 sabores de bitnet.cpp/llama.cpp para el HP OMEN.

PROJECT_ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
BITNET_DIR="${PROJECT_ROOT}/3rdparty/BitNet-1.58b"

function build_flavor() {
	FLAVOR=$1
	CMAKE_FLAGS=$2
	BUILD_DIR="${BITNET_DIR}/build_${FLAVOR}"

	echo "--- [FORJANDO SABOR: ${FLAVOR}] ---"
	mkdir -p "${BUILD_DIR}"
	
	# Configure
	cmake -S "${BITNET_DIR}" -B "${BUILD_DIR}" ${CMAKE_FLAGS} -DCMAKE_BUILD_TYPE=Release
	
	# Build
	cmake --build "${BUILD_DIR}" --config Release -j$(nproc)
	
	echo "--- [FINALIZADO: ${FLAVOR}] ---"
	echo ""
}

# 1. Flavor CPU (Tierra) - Estándar, sin aceleración extra
build_flavor "cpu" ""

# 2. Flavor CUDA (Aire) - Para la RTX 5070
build_flavor "cuda" "-DGGML_CUDA=ON"

# 3. Flavor VULKAN (Mar) - Para la Radeon 890M integrada
build_flavor "vulkan" "-DGGML_VULKAN=ON"

# 4. Flavor NPU (Silencio) - Experimental para XDNA
# Nota: Puede fallar si faltan las librerías XRT, pero lo intentamos.
build_flavor "npu" "-DGGML_XDNA=ON"

echo "--- [FORJADO COMPLETO: YA SOMOS AGUA] ---"
