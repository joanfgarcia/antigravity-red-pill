---
name: music-gen
description: "Genera música simbólica local (LLM→MIDI→FluidSynth→WAV, con control opcional de Ardour por MCP). No es un modelo: es una receta (tool-chain). Úsala para música, arreglos o partituras."
capability: music_gen
---

# Music generation (symbolic)

La música **simbólica** **no es un modelo**: es una **receta** (tool-chain), por eso
**no** la resuelve el router de modelos (`media resolve --task music` no aplica).

## Piezas
- `scripts/music/compose.py` — LLM → MIDI (`mido`) → FluidSynth → WAV.
- `configs/jobs/music_demo.yaml` — demo (un paso).
- `configs/jobs/music_setup.yaml` — venv + Ardour.
- `scripts/music/ardour_mcp_lite.py` — control del DAW por **MCP** (herramientas `ardour_*`).

## ¿Disponible / cómo montarlo?
El forge se crea con `bash scripts/music/bootstrap.sh`; raíz **configurable**
`MUSIC_FORGE_HOME` (def `~/opt/music-forge`) — cámbiala en `.env` si tu equipo/SO lo
requiere.

## Uso directo
```bash
"$MUSIC_FORGE_HOME/venv/bin/python" "$IA_DIR/scripts/music/compose.py" \
  --llm-prompt "lofi hip hop relajante en Do mayor" --out "$RP_MEDIA_STAGING/mi-cancion"
```
Rutas por **env** (el runner exporta el `.env`); sin defaults ni rutas absolutas — si
`MUSIC_FORGE_HOME`/`IA_DIR`/`RP_MEDIA_STAGING` no están configuradas, el comando falla.

## Vía job
```bash
${RED_PILL_CMD} job submit --recipe music_demo --kick
```

## Salida
A **staging** por convención; el artefacto aprobado se **promociona** al destino
definitivo (`media promote` o `--to` explícito). Nunca al repo/desk directamente.
