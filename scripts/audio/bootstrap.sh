#!/usr/bin/env sh
# bootstrap.sh — provisiona el RUNTIME de audio generativo (voz / música / SFX).
#
# Por-máquina (NO se versiona). Se versiona ESTE script + bench_audio.py + recetas.
#
# Hay DOS venvs porque los stacks chocan: chatterbox-tts (TTS) arrastra
# diffusers 0.29 y torch 2.6+cu124 (sin sm_120), mientras que ACE-Step /
# Stable Audio exigen diffusers main + torch cu128. Se separan:
#   $FORGE_HOME/venv       → difusión (diffusers main, torch cu128)
#   $FORGE_HOME/venv-tts   → TTS (kokoro, chatterbox-tts) + torch cu128 forzado
#
# Rutas configurables: AUDIO_FORGE_HOME / AUDIO_FORGE_PYTHON / UV_BIN.
set -eu

FORGE_HOME="${AUDIO_FORGE_HOME:-$HOME/opt/audio-forge}"
HF_CACHE="${HF_HOME:-$FORGE_HOME/hf-cache}"
PY_VER="${AUDIO_FORGE_PYTHON:-3.12}"
UV="${UV_BIN:-$HOME/.local/bin/uv}"
VENV="$FORGE_HOME/venv"
VENV_TTS="$FORGE_HOME/venv-tts"
CU128="https://download.pytorch.org/whl/cu128"
# Set coherente: torch 2.10 ↔ torchaudio 2.10 ↔ torchvision 0.25. Sin pin, el
# índice cu128 sirve torchaudio 2.11 (enlaza libtorch 2.11 inexistente → .so roto).
TORCH_SET="torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0"

echo "== AudioGen bootstrap =="
echo "  forge_home : $FORGE_HOME"
mkdir -p "$FORGE_HOME" "$HF_CACHE"
command -v "$UV" >/dev/null 2>&1 || { echo "ERROR: uv no encontrado en $UV"; exit 1; }

uvpip() { _v="$1"; shift; "$UV" pip install --python "$_v" "$@"; }
mkvenv() { [ -x "$1/bin/python" ] || "$UV" venv "$1" --python "$PY_VER"; }

# ── venv difusión (ACE-Step / Stable Audio) ─────────────────────────────────
mkvenv "$VENV"
VPY="$VENV/bin/python"
echo "-- [difusión] base + torch cu128"
uvpip "$VPY" --upgrade "setuptools>=83" wheel
uvpip "$VPY" --index-url "$CU128" $TORCH_SET
echo "-- [difusión] diffusers main + toolkit (transformers 5.x: diffusers main exige hub>=1)"
uvpip "$VPY" \
	"git+https://github.com/huggingface/diffusers" \
	transformers accelerate safetensors sentencepiece \
	soundfile librosa numpy scipy einops

# ── venv TTS (kokoro / chatterbox) ──────────────────────────────────────────
mkvenv "$VENV_TTS"
TTS_PY="$VENV_TTS/bin/python"
echo "-- [tts] base + kokoro + chatterbox"
uvpip "$TTS_PY" --upgrade "setuptools>=83" wheel
uvpip "$TTS_PY" "transformers>=4.44,<5" sentencepiece soundfile
uvpip "$TTS_PY" kokoro "misaki[en]" chatterbox-tts
echo "-- [tts] restaurar torch cu128 (kokoro/chatterbox traen 2.6+cu124 sin sm_120)"
uvpip "$TTS_PY" --index-url "$CU128" --upgrade "torch==2.10.0" "torchaudio==2.10.0"
echo "-- [tts] deps de runtime: G2P inglés (spacy en_core_web_sm), watermarker (onnxruntime), pkg_resources (setuptools<81)"
uvpip "$TTS_PY" spacy onnxruntime
uvpip "$TTS_PY" "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
uvpip "$TTS_PY" "setuptools==80.9.0"

# ── smoke tests ─────────────────────────────────────────────────────────────
echo "-- smoke [difusión]"
HF_HOME="$HF_CACHE" "$VPY" - <<'PY'
import sys, torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "avail", torch.cuda.is_available())
if not torch.cuda.is_available() or (12, 0) != torch.cuda.get_device_capability(0):
	pass
print("cap", torch.cuda.get_device_capability(0))
import diffusers
for n in ("AceStepPipeline", "StableAudioPipeline"):
	print(f"  {'OK' if hasattr(diffusers, n) else 'FALTA'} {n}")
print("diffusers", diffusers.__version__)
PY

echo "-- smoke [tts]"
HF_HOME="$HF_CACHE" "$TTS_PY" - <<'PY'
import sys, torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "avail", torch.cuda.is_available())
import kokoro  # noqa
from chatterbox.tts import ChatterboxTTS  # noqa
print("kokoro + chatterbox OK")
PY

echo "== bootstrap OK =="
