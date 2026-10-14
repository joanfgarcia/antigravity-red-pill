---
name: capabilities
description: Orienta sobre las capacidades locales de media de Red-Pill (imagen/audio/música) — qué hay instalado, cómo consultarlo (router/elenco), cómo añadir un modelo o un runtime (engine) siguiendo el patrón data-over-code, y el modelo de staging/promoción.
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

## Añadir un modelo o un runtime (imagen/audio)
El elenco (`media_profiles.yaml`) es la **única fuente de verdad de máquina**: lo
consume el **router** *y* el **harness** (`scripts/<area>/`, que traduce cada
entrada a su loader por el campo `backend`). Añadir un modelo = editar el YAML.
Guía completa con ejemplo trabajado: `docs/CORE/MEDIA_MODELS.md`.

### Modelo nuevo (sin tocar código)
1. **Entrada en el elenco** (`~/.config/red-pill/media_profiles.yaml`): `modality`,
   `task`, **`backend`** (dispatch del harness: `diffusers` / `bonsai` / `sd_cpp`…),
   `pipeline`, `runtime`, `weights`, `quant`, `sampler`, `vram_footprint`,
   `capabilities` (tipo de arte/sonido), `constraints` (`dim_multiple`,
   `max_pixels`/`max_vram_mb`…), `adapters` (`snap_dims`, `reject_oversize`…),
   `not_capable_for`, `priority`, `license`, `notes`.
2. **Cascade**: añádelo a `media_roles.<task>` (orden = preferencia).
3. **Verifica**: `${RED_PILL_CMD} media validate --model <id> --width W --height H` (JSON)
   y `${RED_PILL_CMD} media resolve --task <t>`.

```yaml
mi_modelo:
  modality: image
  task: text2image
  backend: diffusers            # dispatch del harness (docs/CORE/MEDIA_MODELS.md §4)
  runtime: diffusers_cuda
  pipeline: MiPipeline
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
Referencia de campos: `examples/media_profiles.yaml.example`.

### Runtime nuevo (engine)
Si el modelo necesita un engine que no está en `runtimes.yaml` (p.ej. GGUF vía
`stable-diffusion.cpp`):
1. **Declara el engine** en `~/.config/red-pill/runtimes.yaml` (`kind`, `binary`/
   `venv`, `env`, `build`, `status`). Un runtime declarado y no disponible = fallo
   limpio (sin fallback silencioso).
2. **Backend del harness**: asegura que existe un `backend` para ese `kind`. Si es
   nuevo, añade su loader en `scripts/<area>/` — el único sitio con código (patrón
   registro+plugin, `CONVENTIONS.md` §10.8.3). Ejemplo real, backend `sd_cpp`:
   `docs/CORE/MEDIA_MODELS.md` §5.

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
