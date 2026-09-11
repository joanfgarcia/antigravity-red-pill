#!/usr/bin/env bash
# setup_cuda_bindings.sh — Desacopla CUDA de red-pill creando un VENV SIDECAR
# local por máquina para las herramientas que necesitan los bindings CUDA.
#
# Por qué existe: el venv del repo (sharing/.venv) es uv-managed — `uv run`
# sincroniza contra uv.lock (llama-cpp-python CPU desde PyPI), así que cualquier
# wheel CUDA instalado ahí se revierte. Red-pill ya desacopla la inferencia de
# producción en un venv local por máquina (~/.local/share/red-pill/daemon/.venv);
# este script aplica el MISMO patrón a las herramientas de bake-off:
#
#   $HOME/.local/share/red-pill/llmtools-venv  (machine-local, NO uv-managed)
#     ├── llama-cpp-python==0.3.35 (wheel CUDA cuXXX, índice abetlen)
#     └── requests + typing-extensions + jinja2 + diskcache + numpy
#
# El venv del repo queda portable (CPU) y `uv run` nunca toca la parte CUDA.
# Idempotente. En CPU-only avisa y no crea nada.
#
# Uso: bash scripts/setup_cuda_bindings.sh [--force]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_VENV="${TOOLS_VENV:-$HOME/.local/share/red-pill/llmtools-venv}"

# ── 0. GPU presente? ─────────────────────────────────────────────────────────
if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi --query-gpu=name --format=csv,noheader >/dev/null 2>&1; then
	echo "[SKIP] Sin NVIDIA GPU en esta máquina — no se crea el sidecar CUDA."
	exit 0
fi
GPU="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
echo "[GPU] $GPU"

# ── 1. Detectar versión CUDA → índice abetlen ───────────────────────────────
cuda_ver=""
if [ -f /usr/local/cuda/version.json ]; then
	cuda_ver="$(python3 -c "import json;print(json.load(open('/usr/local/cuda/version.json'))['cuda']['version'])" 2>/dev/null || true)"
fi
if [ -z "$cuda_ver" ] && command -v nvcc >/dev/null 2>&1; then
	cuda_ver="$(nvcc --version 2>/dev/null | grep -oE 'release [0-9.]+' | head -1 | awk '{print $2}' || true)"
fi
if [ -z "$cuda_ver" ] && [ -x /usr/local/cuda/bin/nvcc ]; then
	cuda_ver="$(/usr/local/cuda/bin/nvcc --version 2>/dev/null | grep -oE 'release [0-9.]+' | head -1 | awk '{print $2}' || true)"
fi
if [ -z "$cuda_ver" ]; then
	echo "[WARN] No se detectó CUDA toolkit — asumo cu130."
	cuda_ver="13.0"
fi
case "$cuda_ver" in
	13.*)   idx="cu130" ;;
	12.9*)  idx="cu129" ;;
	12.8*)  idx="cu128" ;;
	12.6*)  idx="cu126" ;;
	12.4*)  idx="cu124" ;;
	12.2*)  idx="cu122" ;;
	12.1*)  idx="cu121" ;;
	*) echo "[ERROR] CUDA $cuda_ver sin índice abetlen conocido (añade el mapeo a este script)."; exit 1 ;;
esac
INDEX="https://abetlen.github.io/llama-cpp-python/whl/$idx"
echo "[CUDA] $cuda_ver → índice $idx"

# ── 2. Crear el venv sidecar (machine-local, no uv-managed) ─────────────────
if [ ! -x "$TOOLS_VENV/bin/python" ]; then
	echo "[VENV] creando $TOOLS_VENV..."
	uv venv "$TOOLS_VENV" --python 3.12
fi

# ── 3. Instalar el wheel CUDA (--no-deps) + deps del wheel + requests ───────
echo "[INSTALL] llama-cpp-python cu130 en el sidecar..."
uv pip install --python "$TOOLS_VENV/bin/python" llama-cpp-python==0.3.35 --force-reinstall --no-deps --index-url "$INDEX"
echo "[INSTALL] deps del wheel + requests..."
uv pip install --python "$TOOLS_VENV/bin/python" typing-extensions jinja2 diskcache numpy requests

# ── 4. Verificar CUDA ────────────────────────────────────────────────────────
"$TOOLS_VENV/bin/python" - <<'PY'
import glob, os
import llama_cpp
base = os.path.dirname(llama_cpp.__file__)
cuda = glob.glob(os.path.join(base, "**", "libggml-cuda.so*"), recursive=True)
print(f"[VERIFY] llama_cpp {llama_cpp.__version__} | CUDA .so: {len(cuda)}")
raise SystemExit(0 if cuda else 1)
PY
echo "[DONE] Sidecar CUDA listo en $TOOLS_VENV"
echo "       El venv del repo queda portable (CPU). Los harnesses que necesiten"
echo "       bindings CUDA usan: $TOOLS_VENV/bin/python"