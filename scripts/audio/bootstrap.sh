#!/usr/bin/env sh
# bootstrap.sh — provisiona el RUNTIME de audio generativo (voz / música / SFX).
#
# Por-máquina (NO se versiona). Se versiona ESTE script + bench_audio.py + recetas.
#
# Varios venvs porque los stacks chocan (torch/diffusers/transformers distintos):
#   venv        → difusión genérica (diffusers main, torch cu128)
#   venv-tts    → TTS (kokoro, chatterbox-tts)
#   venv-moss   → MOSS-SoundEffect v2 (Apache-2.0) — SFX
#   venv-dasheng→ Dasheng-AudioGen (Apache-2.0) — escena mixta (voz+música+SFX+ambiente)
#
# Rutas configurables: AUDIO_FORGE_HOME / AUDIO_FORGE_PYTHON / UV_BIN.
set -eu

FORGE_HOME="${AUDIO_FORGE_HOME:-$HOME/opt/audio-forge}"
HF_CACHE="${HF_HOME:-$FORGE_HOME/hf-cache}"
PY_VER="${AUDIO_FORGE_PYTHON:-3.12}"
UV="${UV_BIN:-$HOME/.local/bin/uv}"
CU128="https://download.pytorch.org/whl/cu128"
TORCH_SET="torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0"

VENV="$FORGE_HOME/venv"
VENV_TTS="$FORGE_HOME/venv-tts"
VENV_MOSS="$FORGE_HOME/venv-moss"
VENV_DSG="$FORGE_HOME/venv-dasheng"

echo "== AudioGen bootstrap =="
mkdir -p "$FORGE_HOME" "$HF_CACHE"
command -v "$UV" >/dev/null 2>&1 || { echo "ERROR: uv no encontrado en $UV"; exit 1; }

uvpip() { _v="$1"; shift; "$UV" pip install --python "$_v" "$@"; }
mkvenv() { [ -x "$1/bin/python" ] || "$UV" venv "$1" --python "$PY_VER"; }

# ── venv difusión (genérico) ────────────────────────────────────────────────
mkvenv "$VENV"; VPY="$VENV/bin/python"
echo "-- [difusión] torch cu128 + diffusers main"
uvpip "$VPY" --upgrade "setuptools>=83" wheel
uvpip "$VPY" --index-url "$CU128" $TORCH_SET
uvpip "$VPY" "git+https://github.com/huggingface/diffusers" transformers accelerate \
	safetensors sentencepiece soundfile librosa numpy scipy einops

# ── venv TTS (kokoro / chatterbox) ──────────────────────────────────────────
mkvenv "$VENV_TTS"; TTS_PY="$VENV_TTS/bin/python"
echo "-- [tts] kokoro + chatterbox"
uvpip "$TTS_PY" --upgrade "setuptools>=83" wheel
uvpip "$TTS_PY" "transformers>=4.44,<5" sentencepiece soundfile
uvpip "$TTS_PY" kokoro "misaki[en]" chatterbox-tts
uvpip "$TTS_PY" --index-url "$CU128" --upgrade "torch==2.10.0" "torchaudio==2.10.0"
uvpip "$TTS_PY" spacy onnxruntime
uvpip "$TTS_PY" "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
# pkg_resources: setuptools>=81 lo eliminó, pero torch-cu128 exige >=83 → shim
# mínimo (resemble-perth lo usa para localizar sus pesos de watermark).
"$TTS_PY" - <<'PY'
import os, sysconfig
shim = os.path.join(sysconfig.get_paths()["purelib"], "pkg_resources.py")
if not os.path.exists(shim):
	with open(shim, "w") as f:
		f.write(
			"import importlib.util as _iu, os as _os\n"
			"def resource_filename(package_or_requirement, resource_name):\n"
			"\tspec = _iu.find_spec(package_or_requirement)\n"
			"\tif spec is None or spec.origin is None:\n"
			"\t\traise ImportError(package_or_requirement)\n"
			"\treturn _os.path.join(_os.path.dirname(spec.origin), resource_name)\n"
		)
	print("pkg_resources shim ->", shim)
PY

# ── venv-moss (MOSS-SoundEffect v2, Apache-2.0) ─────────────────────────────
mkvenv "$VENV_MOSS"; MOSS_PY="$VENV_MOSS/bin/python"
echo "-- [moss] clone MOSS-TTS + install moss_soundeffect_v2"
[ -d "$FORGE_HOME/MOSS-TTS/.git" ] || git clone --depth 1 https://github.com/OpenMOSS/MOSS-TTS "$FORGE_HOME/MOSS-TTS"
uvpip "$MOSS_PY" --upgrade "setuptools>=68" wheel
uvpip "$MOSS_PY" --index-strategy unsafe-best-match --extra-index-url "$CU128" -e "$FORGE_HOME/MOSS-TTS/moss_soundeffect_v2[torch-cu128]"

# ── venv-dasheng (Dasheng-AudioGen, Apache-2.0) ─────────────────────────────
mkvenv "$VENV_DSG"; DSG_PY="$VENV_DSG/bin/python"
echo "-- [dasheng] torch cu128 + transformers<5 + einops"
uvpip "$DSG_PY" --upgrade "setuptools>=83" wheel
uvpip "$DSG_PY" --index-url "$CU128" torch==2.10.0 torchaudio==2.10.0
uvpip "$DSG_PY" "transformers<5" einops soundfile accelerate

# ── smoke tests ─────────────────────────────────────────────────────────────
echo "-- smoke [difusión]"
HF_HOME="$HF_CACHE" "$VPY" - <<'PY'
import torch, diffusers
print("torch", torch.__version__, "cap", torch.cuda.get_device_capability(0), "diffusers", diffusers.__version__)
PY
echo "-- smoke [tts]"
HF_HOME="$HF_CACHE" "$TTS_PY" - <<'PY'
import torch, kokoro, perth  # noqa
from chatterbox.tts import ChatterboxTTS  # noqa
assert perth.PerthImplicitWatermarker is not None, "watermarker no disponible (pkg_resources shim?)"
print("kokoro + chatterbox + watermarker OK", torch.__version__)
PY
echo "-- smoke [moss]"
HF_HOME="$HF_CACHE" "$MOSS_PY" -c "import torch;from moss_soundeffect_v2 import MossSoundEffectPipeline;print('moss OK', torch.__version__)" 2>&1 | tail -3
echo "-- smoke [dasheng]"
HF_HOME="$HF_CACHE" "$DSG_PY" -c "import torch,einops;from transformers import AutoModel;print('dasheng deps OK', torch.__version__)" 2>&1 | tail -3

echo "== bootstrap OK =="
