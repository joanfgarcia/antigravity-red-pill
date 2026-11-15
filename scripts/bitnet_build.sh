#!/bin/bash
# BitNet local — compila UN sabor del fork en ESTA máquina.
#
# Los binarios nunca viajan en git: dependen de la arquitectura CUDA, del driver,
# del toolkit y del sistema. Lo que sí viaja es el pin del submódulo (`3rdparty/
# BitNet-1.58b` + su `3rdparty/llama.cpp` anidado), así que dos instalaciones
# compilan exactamente la misma fuente.
#
#   git submodule update --init --recursive   # fuente en el pin exacto
#   bash scripts/bitnet_build.sh cuda         # binarios de esta máquina
#
# Sabores:
#   cpu     sin aceleración (siempre funciona, es el más lento)
#   cuda    NVIDIA (RTX 5070 en la máquina de referencia)
#   vulkan  GPU integrada / multiplataforma (Radeon 890M aquí)
#   rocm    AMD HIP — EXPERIMENTAL, no medido en esta máquina
#   npu     NO existe en este fork (no hay flag NPU; se dice en vez de mentir)

set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
BITNET="${ROOT}/3rdparty/BitNet-1.58b"
JOBS="${JOBS:-$(nproc)}"

die() {
	echo "✗ $*" >&2
	exit 1
}

usage() {
	sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
}

check_tree() {
	[ -d "${BITNET}" ] || die "no existe ${BITNET} (¿clonaste con --recurse-submodules?)"
	[ -f "${BITNET}/CMakeLists.txt" ] || die "el submódulo está vacío: git submodule update --init --recursive"
	# El pin incluye bitnet_porter.cu, que incluye estos dos headers. Sin ellos el
	# árbol no compila: es la señal de que falta el submódulo anidado.
	if [ ! -f "${BITNET}/3rdparty/llama.cpp/ggml/src/ggml-cuda/bitnet_porter.cuh" ] ||
		[ ! -f "${BITNET}/3rdparty/llama.cpp/ggml/gpu/bitnet_kernels/bitnet_kernels.h" ]; then
		die "falta el llama.cpp anidado (o sus headers I2_S): git submodule update --init --recursive"
	fi
	command -v cmake >/dev/null 2>&1 || die "cmake no está instalado"
}

pins() {
	echo "  sharing        → BitNet     $(git -C "${ROOT}" rev-parse ":3rdparty/BitNet-1.58b" 2>/dev/null || echo '(sin indexar)')"
	echo "  BitNet-1.58b   → llama.cpp  $(git -C "${BITNET}" rev-parse ":3rdparty/llama.cpp" 2>/dev/null)"
	echo "  llama.cpp                     $(git -C "${BITNET}/3rdparty/llama.cpp" rev-parse HEAD 2>/dev/null)"
}

case "${1:-}" in
"" | -h | --help)
	usage
	exit 0
	;;
--check)
	check_tree
	echo "✓ árbol completo"
	pins
	exit 0
	;;
--list)
	echo "cpu cuda vulkan rocm npu"
	exit 0
	;;
esac

FLAVOR="$1"

case "${FLAVOR}" in
cpu) FLAGS="" ;;
cuda) FLAGS="-DGGML_CUDA=ON" ;;
vulkan) FLAGS="-DGGML_VULKAN=ON" ;;
rocm)
	FLAGS="-DGGML_HIPBLAS=ON"
	echo "⚠ rocm es experimental: no está medido en esta máquina." >&2
	;;
npu)
	die "este fork no tiene backend NPU (no existe flag --GGML_XDNA/--GGML_NPU). Usa cpu."
	;;
*)
	echo "✗ sabor desconocido: ${FLAVOR}" >&2
	echo "  válidos: cpu cuda vulkan rocm (npu no soportado)" >&2
	exit 1
	;;
esac

check_tree

BUILD="${BITNET}/build_${FLAVOR}"
echo "--- BitNet local: sabor ${FLAVOR} ---"
pins
echo "  destino: ${BUILD}"
echo "  jobs:    ${JOBS}"
echo

mkdir -p "${BUILD}"
cmake -S "${BITNET}" -B "${BUILD}" ${FLAGS} -DCMAKE_BUILD_TYPE=Release
cmake --build "${BUILD}" --config Release -j"${JOBS}"

BIN="${BUILD}/bin/llama-server"
[ -x "${BIN}" ] || die "la compilación terminó sin ${BIN}"
echo
echo "✓ ${FLAVOR} listo: ${BIN}"
echo "  el runtime lo resuelve solo (core/paths.py). Prueba:"
echo "    GGML_BITNET_FORCE_AXON=$(echo "${FLAVOR}" | tr '[:lower:]' '[:upper:]') \\"
echo "      ${BUILD}/bin/llama-cli -m <modelo.gguf> -p 'Hello' -n 32"
