---
name: image-gen
description: Genera imágenes locales con el arnés de media de Red-Pill (RFC-HARNESS-004) — router por tarea, adaptadores por modelo, staging y promoción. Úsala cuando haya que crear una imagen (pantalla, ilustración, concepto, tipografía) en este equipo.
capability: image_gen
---

# Image generation (local)

Generación de imagen local (diffusers / backend propio) sobre la GPU del puesto.
El **elenco** vive en `~/.config/red-pill/media_profiles.yaml` (seed:
`examples/media_profiles.yaml.example`).

## 0. ¿Está disponible? ¿Cómo se monta?
```bash
${RED_PILL_CMD} media validate --task typography --width 1920 --height 1080   # JSON: status/model/adapted/warnings/errors
```
Sin forge montado → **instalable**. Receta de creación: `bash scripts/imagegen/bootstrap.sh`
(o job `configs/jobs/imagegen_setup.yaml`); **modelos sugeridos** en
`examples/media_profiles.yaml.example`. La raíz del forge es **configurable**:
`IMAGE_FORGE_HOME` (def `~/opt/image-forge`) — cámbiala en `.env` si tu equipo/SO lo requiere.

## 1. Pide por TAREA, no por modelo a pelo
El router resuelve **tarea → modelo** (clasificación del bakeoff):
`typography`→`zimage_turbo` (único con texto correcto); `concept`/`landscape`→`flux2_klein`;
`illustration`→`flux2_klein`/`bonsai_ternary`.
```bash
${RED_PILL_CMD} media resolve --task typography
```

## 2. El tamaño lo ADAPTA el router (no lo fijes a mano)
Cada modelo declara `constraints.dim_multiple`; el router ajusta con **warning**
(p.ej. zimage ÷16: 1080→1088) o **error limpio** si es imposible (bonsai OOM).
**No edites código ni el múltiplo.**

## 3. Lanzar (job)
Receta: `configs/jobs/imagegen_playground.yaml` (element_job fail-soft). Declara el
bloque `media:` (task/model + width/height); el job valida en el ensamblado y pasa
los params adaptados al harness por env (`RP_MEDIA_*`).
```bash
${RED_PILL_CMD} job submit --recipe imagegen_playground --kick
```

## 4. Salida: STAGING → promoción
La generación va a **staging** (`$RP_MEDIA_STAGING`, o `$RP_TMP_DIR/red-pill/media/staging`
por defecto), en `<staging>/<title>/` — **nunca** al repo ni al desk. Al aprobar:
```bash
${RED_PILL_CMD} media promote <title> --to /ruta/definitiva    # copia (o --move) el artefacto elegido
```

## Modelos del elenco (referencia)
`flux2_klein` (apache-2.0, ÷8, rápido) · `zimage_turbo` (÷16, tipografía) ·
`bonsai_ternary` (÷32, OOM a resolución ancha — el router lo rechaza limpio).
