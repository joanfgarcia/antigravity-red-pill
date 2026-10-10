#!/usr/bin/env sh
# run_element.sh — dispatcher de venv por motor + ejecución de UN elemento.
#
# Los stacks TTS y difusión chocan (ver bootstrap.sh): kokoro/chatterbox viven
# en venv-tts; ACE-Step/Stable Audio en venv. Este script elige el intérprete
# según RP_ELEMENT.model y lanza bench_audio.py --element.
set -eu

FORGE="${AUDIO_FORGE_HOME:-$HOME/opt/audio-forge}"
OUT="${AUDIOGEN_OUT:-$HOME/Documents/IA/Aleth_Core/notes/2026-10-10-audiogen-ab}"
HERE="$(cd "$(dirname "$0")" && pwd)"

MODEL=$(printf '%s' "${RP_ELEMENT:-}" | "$FORGE/venv/bin/python" -c 'import sys,json;print(json.load(sys.stdin).get("model",""))' 2>/dev/null || true)

case "$MODEL" in
	kokoro_voice|chatterbox_voice) PY="$FORGE/venv-tts/bin/python" ;;
	*) PY="$FORGE/venv/bin/python" ;;
esac

mkdir -p "$OUT"
exec "$PY" -u "$HERE/bench_audio.py" --element --out "$OUT"
