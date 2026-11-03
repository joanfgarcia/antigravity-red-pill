#!/bin/bash
# llama.cpp oficial (modelos GGUF generales) — compila en ESTA máquina.
#
# Es el motor para todo lo que NO es ternario I2_S: chat, bake-offs, GGUF Q4/Q8.
# Los binarios no viajan en git (arquitectura CUDA, driver y toolkit son de cada
# instalación); la fuente sí, pineada en `.gitmodules`.
#
#   git submodule update --init 3rdparty/llama_official
#   bash scripts/llama_official_build.sh            # CUDA (por defecto)
#   bash scripts/llama_official_build.sh cpu        # cpu | vulkan | rocm
#
# Usa SIEMPRE `build/` como directorio: es la ruta que resuelve el runtime
# (`3rdparty/llama_official/build/bin/llama-cli`). Cambiar de backend reconfigura
# ese mismo directorio; si necesitas dos a la vez, clona el submódulo aparte.

set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
LLAMA="${ROOT}/3rdparty/llama_official"
BUILD="${BUILD_DIR:-${LLAMA}/build}"
JOBS="${JOBS:-$(nproc)}"

die() {
	echo "✗ $*" >&2
	exit 1
}

usage() {
	sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
}

check_tree() {
	[ -d "${LLAMA}" ] || die "no existe ${LLAMA} (¿clonaste con --recurse-submodules?)"
	[ -f "${LLAMA}/CMakeLists.txt" ] || die "el submódulo está vacío: git submodule update --init 3rdparty/llama_official"
	command -v cmake >/dev/null 2>&1 || die "cmake no está instalado"
}

case "${1:-}" in
"" | -h | --help)
	usage
	exit 0
	;;
--check)
	check_tree
	echo "✓ árbol completo"
	echo "  llama_official → $(git -C "${LLAMA}" rev-parse HEAD)"
	echo "  pin (sharing)  → $(git -C "${ROOT}" rev-parse ":3rdparty/llama_official" 2>/dev/null || echo '(sin indexar)')"
	exit 0
	;;
--list)
	echo "cpu cuda vulkan rocm"
	exit 0
	;;
esac

BACKEND="$1"

case "${BACKEND}" in
cpu) FLAGS="" ;;
cuda) FLAGS="-DGGML_CUDA=ON" ;;
vulkan) FLAGS="-DGGML_VULKAN=ON" ;;
rocm)
	FLAGS="-DGGML_HIPBLAS=ON"
	echo "⚠ rocm es experimental: no está medido en esta máquina." >&2
	;;
*)
	echo "✗ backend desconocido: ${BACKEND}" >&2
	echo "  válidos: cpu cuda vulkan rocm" >&2
	exit 1
	;;
esac

check_tree

echo "--- llama.cpp oficial: ${BACKEND} ---"
echo "  pin:   $(git -C "${LLAMA}" rev-parse HEAD)"
echo "  build: ${BUILD}"
echo "  jobs:  ${JOBS}"
echo

mkdir -p "${BUILD}"
cmake -S "${LLAMA}" -B "${BUILD}" ${FLAGS} -DCMAKE_BUILD_TYPE=Release
cmake --build "${BUILD}" --config Release -j"${JOBS}"

BIN="${BUILD}/bin/llama-cli"
[ -x "${BIN}" ] || die "la compilación terminó sin ${BIN}"
echo
echo "✓ ${BACKEND} listo: ${BIN}"
