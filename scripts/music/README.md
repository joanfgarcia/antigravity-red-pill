# scripts/music — cadena de música SIMBÓLICA 100% libre

Genera música **sin modelos de onda ni GPU**: texto → **MIDI** → **FluidSynth** →
**WAV**, con librerías de instrumentos **libres**. Todo con binario Linux y
licencias GPL/LGPL/MIT/CC0.

```
LLM local ──▶ MIDI (mido) ──▶ FluidSynth + SoundFont libre ──▶ WAV
   │                                    ▲
   └ (opcional) Ardour (GPL) + ardour-mcp (MIT, OSC) — el "modelo que usa el DAW"
```

## Piezas

| fichero | papel |
|---|---|
| `bootstrap.sh` | provisiona venv (uv py3.12) + `mido` + `ardour-mcp` (opcional); **detecta** `fluidsynth`/`ardour` del sistema. |
| `compose.py` | arreglo → `.mid` (mido) → `.wav` (FluidSynth). Modos `--demo`, `--spec`, `--llm-prompt`. |

## Cadena abierta (binarios Linux, licencias libres)

| etapa | software | licencia | instalar |
|---|---|---|---|
| DAW | **Ardour 9.x** | GPL-2 | `sudo apt install ardour` |
| DAW alt | **LMMS** | GPL-2+ | `sudo apt install lmms` |
| Render SF2 | **FluidSynth** | LGPL-2.1 | `sudo apt install fluidsynth` |
| Render SFZ | sfizz | MIT | (no en repos; compilar) |
| Synths | Yoshimi, Hydrogen, Surge XT | GPL | `sudo apt install yoshimi hydrogen` |
| Control DAW | **ardour-mcp** | MIT | pip (lo instala `bootstrap.sh`) |

**Instrumentos libres**: `TimGM6mb.sf2` (ya en `/usr/share/sounds/sf2/`),
**GeneralUser GS** (libre), **VSCO 2 CE** (CC0, orquestal, SFZ), **VCSL** (CC0).

## Rutas

```
MUSIC_FORGE_HOME  ~/opt/music-forge
MUSIC_SF2         /usr/share/sounds/sf2/TimGM6mb.sf2
REDPILL_LLM_URL   http://localhost:8760   # LLM local para --llm-prompt
```

## Uso

```sh
bash scripts/music/bootstrap.sh
sudo apt install fluidsynth ardour lmms          # ← requiere sudo (el operador)

MUSIC_FORGE_HOME/venv/bin/python scripts/music/compose.py --demo --out out/song
MUSIC_FORGE_HOME/venv/bin/python scripts/music/compose.py --spec arreglo.json --out out/song
MUSIC_FORGE_HOME/venv/bin/python scripts/music/compose.py --llm-prompt "lofi en Do mayor" --out out/song
```

Salida: `out/song.mid` + `out/song.wav`.
