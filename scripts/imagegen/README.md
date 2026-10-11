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

Modelos (todos **Apache-2.0**):

- `flux2_klein` — `Flux2KleinPipeline` (diffusers), FLUX.2 klein 4B, 4-bit NF4.
- `zimage_turbo` — `ZImagePipeline` (diffusers), Z-Image-Turbo 6B.
- `bonsai_ternary` — `GpuPipeline` (image-studio/backend_gpu), Bonsai Image 4B ternario (gemlite INT2).

## Rutas configurables (opción por defecto del puesto; override por entorno)

```
IMAGE_FORGE_HOME          ~/opt/image-forge         # venv + image-studio + caches
REDPILL_IMAGE_MODELS_DIR  $XDG_DATA_HOME/red-pill/models/image
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
