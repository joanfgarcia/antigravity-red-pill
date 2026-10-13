---
name: audio-gen
description: Genera audio local con el arnés de media de Red-Pill — voz TTS (kokoro, chatterbox) y SFX/escena (moss, dasheng). Úsala cuando haya que sintetizar voz o sonido en este equipo.
capability: audio_gen
---

# Audio generation (local)

Audio local sobre la GPU/CPU del puesto. Elenco: `~/.config/red-pill/media_profiles.yaml`.

## Voz (TTS)
- `kokoro_voice` — ligero, **español OK**, sin clonación, corre en CPU.
- `chatterbox_voice` — clonación (~5 s) + emoción, 23 idiomas.

## SFX / escena
- `moss_sfx` — entorno/animales/urban/foley (OOM en 8 GB por defecto → el router lo rechaza **limpio**).
- `dasheng_scene` — escena mixta (voz+música+SFX+ambiente); justo en 8 GB.

## Router (tarea → modelo)
```bash
${RED_PILL_CMD} media resolve --task narration     # kokoro_voice
${RED_PILL_CMD} media resolve --task cloning       # chatterbox_voice
${RED_PILL_CMD} media validate --task sfx          # JSON; moss/dasheng pueden salir como error (OOM)
```

## Recetas y harness
- `configs/jobs/audio_setup.yaml` — monta venvs.
- `configs/jobs/audio_bench.yaml` — element_job fail-soft.
- `scripts/audio/` — harness con **dispatcher de venvs** (`run_element.sh`), porque los
  stacks TTS y difusión chocan (dos venvs).

## Salida
Staging → promoción, igual que imagen (`media promote <title> --to <destino>`).
