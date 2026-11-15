#!/bin/bash
# Legacy: antes compilaba los cuatro sabores a mano (sin verificar el árbol).
# Ahora delega en scripts/bitnet_build.sh — un sabor por invocación, con la
# cadena de pins comprobada antes de tocar cmake.
#
#   bash scripts/build_bunker_flavors.sh              # cpu, cuda y vulkan
#   bash scripts/build_bunker_flavors.sh cuda         # solo uno
#
# El sabor "npu" se retiró: este fork no tiene backend NPU (no existe flag
# GGML_XDNA/GGML_NPU); fingirlo solo producía un build de CPU con nombre de NPU.

set -euo pipefail

ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"

FLAVORS=("$@")
if [ ${#FLAVORS[@]} -eq 0 ]; then
	FLAVORS=(cpu cuda vulkan)
fi

for flavor in "${FLAVORS[@]}"; do
	bash "${ROOT}/scripts/bitnet_build.sh" "${flavor}"
done
