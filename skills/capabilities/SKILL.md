---
name: capabilities
description: Orienta sobre las capacidades locales de media de Red-Pill (imagen/audio/música) — qué hay instalado, cómo consultarlo (router/elenco), cómo añadir un modelo o capacidad sin tocar código, y el modelo de staging/promoción.
capability: media
---

# Local media capabilities

## ¿Qué tengo disponible?
- **Elenco** declarativo: `~/.config/red-pill/media_profiles.yaml` (seed: `examples/media_profiles.yaml.example`).
- **Runtimes**: `~/.config/red-pill/runtimes.yaml`.
- **Consulta** (sin cargar modelos):
```bash
${RED_PILL_CMD} media validate --task <capability> --width W --height H   # JSON: status/model/adapted/warnings/errors
${RED_PILL_CMD} media resolve --task <capability>                         # tarea -> modelo
${RED_PILL_CMD} media adapt --model <id> --width W --height H            # ajuste + warnings
```
El router (`red_pill/core/media_router.py`) resuelve **tarea → modelo** (cascade
`media_roles`) y aplica **adapters** por modelo (`constraints`).

## Añadir un modelo (imagen/audio) — SIN tocar código
El elenco es la única fuente; el harness/router lo consumen genéricamente (patrón
registro+plugin). Pasos:

1. **Runtime**: el modelo se ancla a un engine de `~/.config/red-pill/runtimes.yaml`
   (`runtime: <id>`). Si el engine no existe (backend nuevo), añádelo ahí y móntalo
   con `scripts/<area>/bootstrap.sh`.
2. **Pesos**: descárgalos al `hf-cache` del forge (o donde declare el runtime). Sin
   pesos, la familia no se dará por activa.
3. **Entrada en el elenco** (`~/.config/red-pill/media_profiles.yaml`). Campos:
   `modality` (image|audio), `task`, `pipeline`, `runtime`, `weights`, `quant`,
   `sampler`, `vram_footprint`, `capabilities` (tipo de arte/sonido), `constraints`
   (`dim_multiple`, `max_pixels`/`max_vram_mb`…), `adapters` (`snap_dims`,
   `reject_oversize`…), `not_capable_for`, `priority`, `license`, `notes`.
4. **Cascade**: añádelo a `media_roles.<task>` (orden = preferencia).
5. **Verifica**: `${RED_PILL_CMD} media validate --task <t> --width W --height H` (JSON)
   y `${RED_PILL_CMD} media resolve --task <t>`.

```yaml
mi_modelo:
  modality: image
  task: text2image
  pipeline: MiPipeline
  runtime: diffusers_cuda
  weights: "org/mi-modelo"
  quant: { scheme: bnb4, dtype: bfloat16 }
  sampler: { steps: 8, guidance: 1.0, size: 1024 }
  vram_footprint: { peak_mb: 4000 }
  capabilities: ["photorealism"]
  constraints: { dim_multiple: 16, max_pixels: 4194304 }
  adapters: ["snap_dims", "reject_oversize"]
  not_capable_for: []
  priority: 4
  license: { id: apache-2.0, commercial_ok: true, source: "..." }
  notes: "..."
```
Referencia de campos: `examples/media_profiles.yaml.example`. Nada más: no se toca
el harness ni el router (`docs/CORE/CONVENTIONS.md` §10.8).

## Modelo de ejecución
- Config viva por-máquina en `~/.config/red-pill/`; artefactos en `~/opt/*`.
- Generación → **staging** (`<RP_TMP_DIR>/red-pill/media/staging/<title>/`); promoción
  **explícita** con `media promote`.
- **Fail-clean**: lo imposible falla en el ensamblado (error JSON); lo adaptable avisa
  (warning); lo no controlable (OOM) lo cubre el DAG (fail-soft).

## Montar / ubicar los forges (opcional, por-máquina)
Cada forge (imagen/audio/música) es un venv + pesos separado; default
`~/opt/<area>-forge`, **configurable** por env en `.env`
(`IMAGE_FORGE_HOME` / `AUDIO_FORGE_HOME` / `MUSIC_FORGE_HOME`) — cámbialo por gusto,
restricciones de equipo o SO. Se crean con `scripts/<area>/bootstrap.sh`; modelos
sugeridos en `examples/media_profiles.yaml.example`. Si un forge **no** está montado,
su capability está inactiva y sus skills **no** se siembran.

**Dos piezas independientes**: el **runtime** (bootstrap) y el **elenco**
(`media_profiles.yaml`). Si el forge existe pero `media validate` falla con
"media_profiles.yaml no encontrado" → **siembra el elenco** (bootstrap no lo hace):
`cp examples/media_profiles.yaml.example ~/.config/red-pill/media_profiles.yaml`.

## Skills relacionadas
`image-gen` · `audio-gen` · `music-gen`.
