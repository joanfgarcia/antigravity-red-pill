---
name: image-gen
description: Genera imágenes locales con el arnés de media de Red-Pill (RFC-HARNESS-004) — router por tarea, adaptadores por modelo, staging y promoción. Úsala cuando haya que crear una imagen (pantalla, ilustración, concepto, tipografía) en este equipo.
capability: image_gen
---

# Image generation (local)

Generación de imagen local (diffusers / backend propio) sobre la GPU del puesto.
El **elenco** vive en `~/.config/red-pill/media_profiles.yaml` (plantilla:
`examples/media_profiles.yaml.example`).

## 0. ¿Está disponible? ¿Cómo se monta?
Dos piezas independientes: **runtime** (venv/torch/diffusers/gemlite) y **elenco**.

```bash
${RED_PILL_CMD} media validate --task typography --width 1920 --height 1080   # JSON: status/model/adapted/warnings/errors
```

- **Sin runtime** (no hay forge) → `bash scripts/imagegen/bootstrap.sh` (o job
  `configs/jobs/imagegen_setup.yaml`). Monta el venv + torch/diffusers; **NO** siembra el elenco.
- **Runtime sí, pero `media validate` falla con "media_profiles.yaml no encontrado"**
  → **siembra el elenco antes de validar** (bootstrap no lo hace):
  ```bash
  cp examples/media_profiles.yaml.example ~/.config/red-pill/media_profiles.yaml
  ```
  (modelos sugeridos en esa plantilla). Sin elenco, el forge tiene modelos pero el
  router no sabe qué hay.
- La raíz del forge es **configurable**: `IMAGE_FORGE_HOME` (def `~/opt/image-forge`)
  — cámbiala en `.env` si tu equipo/SO lo requiere.

## 1. Pide por TAREA — tokens EXACTOS (sin alias)
El router resuelve **tarea → modelo** vía la cascade `media_roles` del elenco. Los
tokens deben ser **exactos** (no hay normalización): `photorealism` es un **valor de
`capabilities`**, NO una tarea. Tareas válidas de imagen:

| token (`--task`) | resuelve a | para |
|---|---|---|
| `typography` | `zimage_turbo` | texto legible (único que lo escribe bien) |
| `product` | `zimage_turbo` | producto/estudio |
| `concept` | `flux2_klein` | concepto/abstracto, épico |
| `landscape` | `flux2_klein` | paisaje/entorno |
| `illustration` | `flux2_klein` | ilustración/estilizado |
| `photoreal` | `flux2_klein` | fotorrealismo/retrato |

```bash
${RED_PILL_CMD} media resolve --task typography      # -> zimage_turbo
```
Si pasas un `--task` que no está en `media_roles` → **error** (no hay alias).

## 2. El tamaño lo ADAPTA el router (no lo fijes a mano)
Cada modelo declara `constraints.dim_multiple`; el router ajusta con **warning**
(p.ej. `zimage ÷16`: 1080→1088) o **error limpio** si es imposible (bonsai OOM).
**No edites código ni el múltiplo.**

## 3. Lanzar la generación
### 3.a Receta existente (playground de referencia)
`configs/jobs/imagegen_playground.yaml` es un `element_job` fail-soft **concreto**
(pantalla de carga de Joel). Sirve de plantilla, pero para un encargo arbitrario
escribe la tuya (§3.b).

### 3.b Receta propia — "prompt libre, un modelo" (recomendado)
Vive en **`.red-pill/jobs/<nombre>.yaml`** (**créalo si no existe**; no versionado;
ver skill `job-manager`). **El intérprete sale del forge; el script, del repo** — no
todo cuelga del forge. Esqueleto exacto (rutas por **env**, sin defaults):

```yaml
source: element_job
media: { model: flux2_klein, width: 1920, height: 1080 }   # o task: <token de §1>
priority: 3
title: mi-encargo
elements_command: ["sh", "-c", 'OUT="$RP_MEDIA_STAGING/mi-encargo"; mkdir -p "$OUT"; "$IMAGE_FORGE_HOME/venv/bin/python" "$IA_DIR/scripts/imagegen/gen_image.py" --list-elements --models flux2_klein --prompt "un gato astronauta" --name mi-encargo --out "$OUT" --width 1920 --height 1080']
step_command: ["sh", "-c", 'OUT="$RP_MEDIA_STAGING/mi-encargo"; mkdir -p "$OUT"; "$IMAGE_FORGE_HOME/venv/bin/python" -u "$IA_DIR/scripts/imagegen/gen_image.py" --element --out "$OUT"; rc=$?; if [ $rc -ne 0 ]; then echo "$RP_ELEMENT rc=$rc" >> "$OUT/failures.jsonl"; exit 79; fi; exit 0']
skip_exit_code: 79
```

Reglas de la plantilla (**fail-clean**):
- **Sin rutas absolutas ni `${VAR:-default}`.** El valor sale del **entorno**: el runner
  exporta el `.env` y, si una var no está, su **default canónico de `paths.py`**
  (`$IA_DIR`, `$IMAGE_FORGE_HOME`, `$RP_MEDIA_STAGING`…). No las fijes a mano.
- **`$IA_DIR`** = raíz del repo (bunker); **`$IMAGE_FORGE_HOME`** = forge (venv).
  Usa **env, no rutas relativas**: una receta en `.red-pill/jobs/` hereda **cwd = raíz
  del workspace** (no el repo).
- **`.red-pill/jobs/`** puede no existir → **créalo** antes (`mkdir -p .red-pill/jobs`).

`gen_image.py` acepta `--prompt` (o `--prompt-file`), `--models <csv>`, `--name`
(exacto) / `--tag` (patrón `<modelo>__<tag>__s<seed>`), `--width/--height`, `--seed`.
El **tamaño lo adapta el router** (bloque `media:`); el harness lo recibe por env.

```bash
${RED_PILL_CMD} job submit --recipe mi-encargo --kick
```

## 4. Salida: STAGING → promoción
La generación va a **staging** (`$RP_MEDIA_STAGING`, o `$RP_TMP_DIR/red-pill/media/staging`
por defecto), en `<staging>/<title>/` — **nunca** al repo ni al desk. Al aprobar:
```bash
${RED_PILL_CMD} media promote <title> --to /ruta/definitiva    # copia (o --move) el artefacto elegido
```

## Modelos del elenco (referencia)
`flux2_klein` (apache-2.0, ÷16, rápido) · `zimage_turbo` (÷16, tipografía) ·
`bonsai_ternary` (÷32, OOM a resolución ancha — el router lo rechaza limpio).
