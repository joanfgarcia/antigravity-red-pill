#!/usr/bin/env sh
# run_element.sh — dispatcher de venv por motor + ejecución de UN elemento.
#
# Los stacks TTS y difusión chocan (ver bootstrap.sh): kokoro/chatterbox viven
# en venv-tts; ACE-Step/Stable Audio en venv. Este script elige el intérprete
# según RP_ELEMENT.model y lanza bench_audio.py --element.
set -eu

FORGE="$AUDIO_FORGE_HOME"
OUT="$AUDIOGEN_OUT"
HERE="$(cd "$(dirname "$0")" && pwd)"

MODEL=$(printf '%s' "${RP_ELEMENT:-}" | "$FORGE/venv/bin/python" -c 'import sys,json;print(json.load(sys.stdin).get("model",""))' 2>/dev/null || true)

case "$MODEL" in
	kokoro_voice|chatterbox_voice) PY="$FORGE/venv-tts/bin/python" ;;
	moss_sfx) PY="$FORGE/venv-moss/bin/python" ;;
	dasheng_scene) PY="$FORGE/venv-dasheng/bin/python" ;;
	*) PY="$FORGE/venv/bin/python" ;;
esac

mkdir -p "$OUT"
exec "$PY" -u "$HERE/bench_audio.py" --element --out "$OUT"
