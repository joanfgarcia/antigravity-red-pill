#!/usr/bin/env sh
# gen.sh — lanzador de consola GENÉRICO, dirigido por el elenco (media_profiles.yaml).
#
# Sirve para cualquier modelo o familia de IMAGEN instalada. Wrapper delgado sobre gen_cli.py
# (usa el python del forge). Antes de generar, libera la VRAM del LLM residente.
#
# Uso:
#   ./gen.sh --role photoreal "un gato astronauta, foto realista"
#   ./gen.sh --model zimage_turbo "…" --width 832 --height 1216 --seed -1
#   ./gen.sh "…"                          # prompt directo; rol por defecto (photoreal)
#   ./gen.sh --role photoreal --dry-run   # resuelve y muestra sin generar
#
# Env (defaults): W H SEED OUTDIR — p.ej. W=1024 H=1536 SEED=-1 ./gen.sh "…"
# Requiere: elenco sembrado (~/.config/red-pill/media_profiles.yaml) y el forge.
set -eu

FORGE="${IMAGE_FORGE_HOME:-$HOME/opt/image-forge}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ ! -x "$FORGE/venv/bin/python" ]; then
	echo "[error] forge no encontrado en $FORGE (exporta IMAGE_FORGE_HOME o corre scripts/imagegen/bootstrap.sh)" >&2
	exit 1
fi

exec "$FORGE/venv/bin/python" "$HERE/gen_cli.py" "$@"
