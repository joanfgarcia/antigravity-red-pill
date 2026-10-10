#!/usr/bin/env sh
# bootstrap.sh — runtime de música SIMBÓLICA libre (MIDI + FluidSynth + Ardour).
#
# Por-máquina (NO se versiona). Se versiona este script + compose.py + recetas.
#
# NO requiere sudo para lo python (venv, mido, ardour-mcp), pero FluidSynth y
# Ardour SÍ son paquetes del sistema:
#     sudo apt install fluidsynth ardour lmms
# Este script los DETECTA y avisa (no los instala).
#
# Rutas configurables: MUSIC_FORGE_HOME (def ~/opt/music-forge), UV_BIN.
set -eu

FORGE_HOME="${MUSIC_FORGE_HOME:-$HOME/opt/music-forge}"
PY_VER="${MUSIC_FORGE_PYTHON:-3.12}"
UV="${UV_BIN:-$HOME/.local/bin/uv}"
VENV="$FORGE_HOME/venv"

echo "== Music bootstrap (simbólico libre) =="
mkdir -p "$FORGE_HOME"
command -v "$UV" >/dev/null 2>&1 || { echo "ERROR: uv no encontrado"; exit 1; }

[ -x "$VENV/bin/python" ] || "$UV" venv "$VENV" --python "$PY_VER"
VPY="$VENV/bin/python"

echo "-- mido (autoría MIDI)"
"$UV" pip install --python "$VPY" mido

echo "-- ardour-mcp (MIT; control del DAW por OSC) [opcional, no aborta]"
"$UV" pip install --python "$VPY" "git+https://github.com/raibid-entertainment/ardour-mcp" 2>&1 | tail -3 || echo "   (ardour-mcp no instalado; se puede añadir luego)"
# ardour-mcp 0.0.1 usa la API antigua del SDK (Server.call_tool); mcp>=1.x la rompe.
"$UV" pip install --python "$VPY" "mcp==0.9.1" 2>&1 | tail -1

echo "-- detección de binarios del sistema"
for b in fluidsynth ardour lmms; do
	if command -v "$b" >/dev/null 2>&1; then
		echo "   OK  $b -> $(command -v "$b")"
	else
		echo "   FALTA $b  (instala: sudo apt install $b)"
	fi
done

echo "-- soundfonts disponibles"
ls /usr/share/sounds/sf2/*.sf2 2>/dev/null || echo "   (ninguno; MUSIC_SF2 apuntará al que elijas)"

echo "-- smoke"
"$VPY" -c "import mido; print('mido OK', mido.__version__ if hasattr(mido,'__version__') else '')" 2>&1 | tail -1

echo "== bootstrap OK (recuerda: fluidsynth/ardour requieren sudo apt) =="
