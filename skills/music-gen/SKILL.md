---
name: music-gen
description: Genera música simbólica local (LLM→MIDI→FluidSynth→WAV, con control opcional de Ardour por MCP). No es un modelo: es una receta (tool-chain). Úsala para música, arreglos o partituras.
---

# Music generation (symbolic)

La música **simbólica** **no es un modelo**: es una **receta** (tool-chain), por eso
**no** la resuelve el router de modelos (`media resolve --task music` no aplica).

## Piezas
- `scripts/music/compose.py` — LLM → MIDI (`mido`) → FluidSynth → WAV.
- `configs/jobs/music_demo.yaml` — demo (un paso).
- `configs/jobs/music_setup.yaml` — venv + Ardour.
- `scripts/music/ardour_mcp_lite.py` — control del DAW por **MCP** (herramientas `ardour_*`).

## Uso directo
```bash
${MUSIC_FORGE_HOME:-$HOME/opt/music-forge}/venv/bin/python scripts/music/compose.py \
  --llm-prompt "lofi hip hop relajante en Do mayor" --out <destino>
```

## Vía job
```bash
${RED_PILL_CMD} job submit --recipe music_demo --kick
```

## Salida
A **staging** por convención; el artefacto aprobado se **promociona** al destino
definitivo (`media promote` o `--to` explícito). Nunca al repo/desk directamente.
