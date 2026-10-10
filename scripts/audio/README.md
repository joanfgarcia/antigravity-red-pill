# scripts/audio — banco A/B de audio generativo local

Herramienta para correr y **clasificar por tipo de sonido** modelos de audio
locales en GPUs de consumo (8 GB): **voz** (TTS), **música** y **SFX/ambiente**
(pájaros, viento, foley…). Hermana de `scripts/imagegen/`.

## Piezas

| fichero | papel |
|---|---|
| `bootstrap.sh` | provisiona el runtime **por-máquina** (venv uv py3.12, torch cu128, diffusers main, kokoro, chatterbox-tts, MOSS-SoundEffect, Dasheng). No versiona terceros. |
| `bench_audio.py` | harness: carga cada motor, recorre sus piezas, mide tiempo/VRAM, guarda WAV + `metrics.jsonl` (reanudable por pieza). |
| `soundgenres.json` | matriz fija de sonidos por eje (voz / música / SFX). |

Motores (todos con licencia limpia):

| id | motor | eje | licencia |
|---|---|---|---|
| `kokoro_voice` | Kokoro-82M (`KPipeline`) | voz | Apache-2.0 |
| `chatterbox_voice` | Chatterbox 0.5B (`ChatterboxTTS`) | voz (clon/emoción) | MIT |
| `moss_sfx` | MOSS-SoundEffect v2.0 (`MossSoundEffectPipeline`) | SFX/ambiente | Apache-2.0 |
| `dasheng_scene` | Dasheng-AudioGen (`AutoModel`) | escena mixta | Apache-2.0 |

> Los backends de **onda** (moss/dasheng) cargan en sm_120 pero **superan los
> 8 GB** en su setup por defecto (necesitan cuantizar el text encoder). Descartados
> por licencia: Stable Audio Open (community/gated), AudioLDM2/AudioX/MMAudio/Woosh (CC-BY-NC).

## Rutas configurables

```
AUDIO_FORGE_HOME   ~/opt/audio-forge       # venv + caches
HF_HOME            $AUDIO_FORGE_HOME/hf-cache
AUDIO_FORGE_PYTHON 3.12
```

Otro operador puede instalar en otra ruta exportando `AUDIO_FORGE_HOME` antes
de llamar a `bootstrap.sh` / las recetas.

## Uso

```sh
bash scripts/audio/bootstrap.sh                                  # o configs/jobs/audio_setup.yaml
AUDIO_FORGE_HOME/venv/bin/python scripts/audio/bench_audio.py --element
AUDIO_FORGE_HOME/venv/bin/python scripts/audio/bench_audio.py --models kokoro_voice,moss_sfx --out ./out
```

Salida: `<out>/<motor>__<pieza>.wav` + `<out>/metrics.jsonl`. Fail-soft por motor.

## Hardware

GPU NVIDIA ≥8 GB (probado en RTX 5070 Laptop, sm_120):
- Kokoro/Chatterbox → ligeros (voz, ~0.8-3.3 GB).
- MOSS/Dasheng → cargan pero **superan 8 GB** por defecto (encoder Qwen3 grande).
