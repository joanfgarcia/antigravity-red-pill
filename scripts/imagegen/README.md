# scripts/imagegen — banco A/B de generación de imagen local

Herramienta para correr y **clasificar por tipo de arte** modelos texto→imagen
**locales** en GPUs de consumo. Análoga a `bench_local.py` (RFC-HARNESS-003) pero
para difusión en vez de LLM.

## Piezas

| fichero | papel |
|---|---|
| `bootstrap.sh` | provisiona el runtime **por-máquina** (venv uv py3.12, torch cu128, diffusers main, gemlite+hqq, backend_gpu). No se versiona lo que instala. |
| `bench_imagegen.py` | harness: carga cada modelo, recorre la matriz de géneros × seeds, mide tiempo/VRAM, guarda PNG + `metrics.jsonl` (reanudable por género). |
| `compat_image_studio.py` | shim para `image-studio/backend_gpu` bajo torch≥2.10 + gemlite 0.6.x (el tensor ternario se reconstruye y carga en bloque). |
| `benchgenres.json` | matriz fija de tipos de arte (congelada por versión). |

Modelos: **NO hardcodeados** — el harness los lee del elenco de máquina
(`~/.config/red-pill/media_profiles.yaml`, campo `backend`; ver
`docs/CORE/MEDIA_MODELS.md`). Ejemplo del puesto:

- `flux2_klein` — `Flux2KleinPipeline` (diffusers), FLUX.2 klein 4B, 4-bit NF4 (Apache-2.0).
- `zimage_turbo` — `ZImagePipeline` (diffusers), Z-Image-Turbo 6B (Apache-2.0).
- `bonsai_ternary` — `GpuPipeline` (image-studio/backend_gpu), Bonsai Image 4B ternario (gemlite INT2) (Apache-2.0).
- `qwen_image_2_1_turbo` — backend `sd_cpp` (stable-diffusion.cpp, GGUF), Qwen-Image-2.1-Turbo + encoder Qwen3-VL-8B (qwen-research, **no comercial**).

## Rutas configurables (opción por defecto del puesto; override por entorno)

```
IMAGE_FORGE_HOME          ~/opt/image-forge         # venv + image-studio + caches
REDPILL_IMAGE_MODELS_DIR  ~/opt/red-pill-custom-image-models
HF_HOME                   $IMAGE_FORGE_HOME/hf-cache
IMAGE_FORGE_PYTHON        3.12                       # el 3.14 del sistema no tiene wheels torch
IMG_DIFFUSERS_QUANT       bnb4 | seqoff | bf16
```

Otro operador puede instalar en otra ruta sin tocar el repo: exporta
`IMAGE_FORGE_HOME` antes de llamar a `bootstrap.sh` / las recetas.

## Uso

```sh
# 1) provisionar runtime (o vía job: configs/jobs/imagegen_setup.yaml)
bash scripts/imagegen/bootstrap.sh

# 2) banco A/B (o vía job: configs/jobs/imagegen_bench.yaml, element_job fail-soft)
IMAGE_FORGE_HOME/venv/bin/python scripts/imagegen/bench_imagegen.py --element    # RP_ELEMENT
IMAGE_FORGE_HOME/venv/bin/python scripts/imagegen/bench_imagegen.py --models flux2_klein,zimage_turbo,bonsai_ternary --out ./out
```

Salida: `<out>/<modelo>__<género>__s<seed>.png` + `<out>/metrics.jsonl`.
Un modelo (o un género) que falla se registra y **no tumba el resto** (fail-soft).

## Requisitos de hardware

GPU NVIDIA con ≥8 GB (probado en RTX 5070 Laptop, sm_120):
- 4B/6B → **4-bit** obligatorio (bf16 no cabe).
- Ternario Bonsai → cabe nativo (~6.7 GB pico a 1024²).

## Router, adaptadores y staging (docs/CORE/MEDIA_MODELS.md)

`gen_image.py` acepta prompt libre y tamaño no cuadrado y **no fija el múltiplo**:
el tamaño lo **adapta el router** (`red_pill/core/media_router.py`) según el modelo
(`constraints.dim_multiple`) → **warning** (`zimage ÷16`: 1080→1088) o **error
limpio** si es imposible (`bonsai` OOM). El job side inyecta los params ya
adaptados por env (`RP_MEDIA_WIDTH`/`RP_MEDIA_HEIGHT`/`RP_MEDIA_WARNINGS`).

La generación va a **staging** `${RP_MEDIA_STAGING:-~/tmp/red-pill/media/staging}/<title>/`,
**no** al desk. Al aprobar:

```sh
red-pill media validate --task typography --width 1920 --height 1080   # JSON
red-pill media promote <title> --to <destino>                          # copia (--move) el elegido
```

## Lanzador de consola — `gen.sh` (genérico, dirigido por el elenco)

Generar desde la terminal sin montar un job, por **modelo** (`--model ID`) o por
**familia/tarea** (`--role TASK`, resuelto por la cascade `media_roles`), con el
backend que declare el elenco:

```sh
scripts/imagegen/gen.sh --role photoreal "un gato astronauta, foto realista"
scripts/imagegen/gen.sh --model zimage_turbo "…" --width 832 --height 1216 --seed -1
W=1024 H=1536 SEED=7 scripts/imagegen/gen.sh "…"       # tamaño/seed por entorno
scripts/imagegen/gen.sh --role photoreal --dry-run     # resuelve, sin generar
```

- Libera la VRAM del LLM residente antes de generar (`--no-unload` lo evita).
- Resuelve modelo/rol del elenco (misma fuente que router y harness) y hace `snap`
  al `dim_multiple` del modelo.
- Salida: `<out>/<modelo>_<fecha>_s<seed>.png` (`--out` / `OUTDIR`).
- Wrapper delgado sobre `gen_cli.py` (usa el python del forge); en un job el
  entorno ya viene del runner — aquí el launcher fija los defaults canónicos
  por-máquina con `setdefault`.

También como **comando de consola del repo**: `uv run media-gen …` (entry point
`media-gen` → `red_pill.media_gen`, delega en `gen_cli.py` con el python del forge).

**Edición y composición** (backend `sd_cpp`; requieren el `vision`/mmproj en el
elenco — se resuelve del `sd_cpp:` block):

```sh
uv run media-gen --model qwen_image_2_1_turbo --image foto.png "cambia la taza a azul"
uv run media-gen --model qwen_image_2_1_turbo --image foto.png --mask zona.png "quita la taza"
uv run media-gen --model qwen_image_2_1_turbo --ref-image a.png --ref-image b.png "compón una escena"
uv run media-gen --model qwen_image_2_1_turbo --image foto.png --strength 0.6 "…"   # re-difusión parcial
```

Las **referencias múltiples** (`--ref-image`, repetible) usan `-r/--ref-image` de
sd.cpp; el soporte multi-ref completo de Qwen por esa vía está **por confirmar**.

