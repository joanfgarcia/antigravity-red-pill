#!/usr/bin/env sh
# bootstrap.sh — provisiona el RUNTIME de generación de imagen (por-máquina).
#
# Lo que instala (venv uv, torch, diffusers, gemlite, image-studio) NO se
# versiona: es terceros y se construye/descarga en cada máquina. Lo versionado
# es ESTE script + bench_imagegen.py + las recetas de job.
#
# Rutas configurables (opción por defecto del puesto de referencia):
#   IMAGE_FORGE_HOME          (def $HOME/opt/image-forge)
#   REDPILL_IMAGE_MODELS_DIR  (def $XDG_DATA_HOME/red-pill/models/image)
#   IMAGE_FORGE_PYTHON        (def 3.12 — el 3.14 del sistema no tiene wheels torch)
#   UV_BIN                    (def $HOME/.local/bin/uv)
#
# Idempotente: re-ejecutarlo sólo actualiza.
set -eu

FORGE_HOME="${IMAGE_FORGE_HOME:-$HOME/opt/image-forge}"
MODELS_DIR="${REDPILL_IMAGE_MODELS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/red-pill/models/image}"
HF_CACHE="${HF_HOME:-$FORGE_HOME/hf-cache}"
PY_VER="${IMAGE_FORGE_PYTHON:-3.12}"
VENV="$FORGE_HOME/venv"
UV="${UV_BIN:-$HOME/.local/bin/uv}"

echo "== ImageGen bootstrap =="
echo "  forge_home : $FORGE_HOME"
echo "  models_dir : $MODELS_DIR"
echo "  hf_cache   : $HF_CACHE"
echo "  python     : $PY_VER"

mkdir -p "$FORGE_HOME" "$MODELS_DIR" "$HF_CACHE"

if ! command -v "$UV" >/dev/null 2>&1; then
	echo "ERROR: uv no encontrado en $UV (instala astral uv: https://docs.astral.sh/uv/)"
	exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
	echo "-- creando venv ($PY_VER)"
	"$UV" venv "$VENV" --python "$PY_VER"
else
	echo "-- venv existente, actualizando"
fi
VPY="$VENV/bin/python"

echo "-- setuptools/wheel base (torch cu128 exige setuptools>=83)"
"$UV" pip install --python "$VPY" --upgrade "setuptools>=83" wheel

echo "-- torch + torchvision (cu128; Blackwell sm_120)"
"$UV" pip install --python "$VPY" --index-url https://download.pytorch.org/whl/cu128 torch torchvision

echo "-- diffusers (main) + toolkit"
"$UV" pip install --python "$VPY" \
	"git+https://github.com/huggingface/diffusers" \
	transformers accelerate safetensors sentencepiece protobuf pillow \
	huggingface_hub hf_transfer einops bitsandbytes

echo "-- gemlite + hqq (path ternario)"
"$UV" pip install --python "$VPY" \
	"git+https://github.com/mobiusml/gemlite" hqq

echo "-- image-studio (sólo backend_gpu)"
if [ ! -d "$FORGE_HOME/image-studio/.git" ]; then
	git clone --depth 1 https://github.com/PrismML-Eng/image-studio "$FORGE_HOME/image-studio"
else
	echo "   ya clonado — skip"
fi

echo "-- smoke test CUDA sm_120"
HF_HOME="$HF_CACHE" "$VPY" - <<'PY'
import sys
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda)
print("available", torch.cuda.is_available())
if not torch.cuda.is_available():
	print("FATAL: CUDA no disponible")
	sys.exit(1)
print("gpu", torch.cuda.get_device_name(0), "cap", torch.cuda.get_device_capability(0))
x = torch.randn(2048, 2048, device="cuda", dtype=torch.float16)
y = (x @ x).sum().item()
print("matmul ok:", y == y and y != 0.0)
print("smoke OK")
PY

echo "== bootstrap OK =="
