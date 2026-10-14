# Media Models & Runtimes — How to Add a Model or an Engine

How the **media generation** harness (image/audio) discovers *what* models exist
and *how* to run them. Companion of
[`examples/media_profiles.yaml.example`](../../examples/media_profiles.yaml.example)
and [`examples/runtimes.yaml.example`](../../examples/runtimes.yaml.example).
Status: enforced. Scope: `scripts/<area>/`, `configs/jobs/`, machine config.

---

## 1. Two registries, one machine

Media generation is driven by **declarative data**, never by hardcoded model
lists (CONVENTIONS §10.8.2 *data over branches*):

| Registry (machine config, seeded copy-if-absent) | Holds | Consumed by |
|---|---|---|
| `~/.config/red-pill/media_profiles.yaml` | **what** each model is: `modality`, `capabilities`, `constraints`/`adapters`, `license`, `priority`, **`backend`**, `pipeline`/`weights`/`sampler`, and per-backend blocks (`sd_cpp:`…) | the **router** (`src/red_pill/core/media_router.py`) **and the harness** (`scripts/<area>/*.py`) |
| `~/.config/red-pill/runtimes.yaml` | **the engines**: `kind`, `binary`/`venv`, `env`, `build`, `capabilities`, `status` — for LLM *and* media (`diffusers_cuda`, `pipeline_custom`, `sd_cpp`…) | `model_runtime` (LLM) and the media harness |

There is **one source of truth per concern**: the elenco says what a model *is*
and which `backend` loads it; the runtime registry says *where the engine lives*.
`media_profiles.yaml` is seeded from `examples/media_profiles.yaml.example`;
`runtimes.yaml` from `examples/runtimes.yaml.example`. The live copies are
per-machine and **never committed** (recalibrate timings/VRAM per box).

> The harness (`bench_imagegen.py`) reads the elenco at run time and translates
> each `modality: image` entry into its loader shape. **There is no `MODELS` dict
> in code** — adding a model is editing the YAML, nothing else.

---

## 2. Add a MODEL (the common case — no code)

1. Add an entry under `media_profiles:` in `media_profiles.yaml`:

   ```yaml
   my_model:
     modality: image
     task: text2image
     backend: diffusers                 # dispatch del harness (ver §4)
     runtime: diffusers_cuda
     pipeline: MyFancyPipeline          # clase diffusers (o backend propio)
     weights: "org/my-model"            # repo HF (o ruta local, según backend)
     quant: { scheme: bnb4 }
     sampler: { steps: 8, guidance: 1.0, size: 1024 }
     vram_footprint: { peak_mb: 4000 }
     capabilities: ["photorealism"]     # vocabulario de media_roles
     not_capable_for: []
     priority: 2
     constraints: { dim_multiple: 16 }  # divisor de resolución del VAE/patch
     adapters: ["snap_dims", "reject_oversize"]
     license:                           # obligatorio (gate de compliance)
       id: "apache-2.0"
       commercial_ok: true
       redistribution_ok: true
       attribution_required: false
       share_alike: false
       source: "https://huggingface.co/org/my-model"
     notes: "…"
   ```

2. (Opcional) Añádelo a la **cascade** `media_roles.<task>` (orden = preferencia).

3. Verifica sin cargar pesos:

   ```sh
   red-pill media validate --model my_model --width 1920 --height 1080   # JSON
   red-pill media resolve  --task photoreal
   ```

That is all: the router routes it, the harness loads it, the license gate sees it.

---

## 3. Add a RUNTIME (new engine)

When the model needs an engine that is not yet declared in `runtimes.yaml`
(e.g. a GGUF runner, a new backend), two pieces — **declaration + loader**:

**a) Declare the engine in `runtimes.yaml`** (seeded from the example):

```yaml
runtimes:
  my_engine:
    kind: sd_cpp                       # familia del engine
    description: "…"
    binary: "~/opt/my-engine/bin/run"  # ~/absoluta o relativa al repo
    env: { LD_LIBRARY_PATH: "/usr/local/cuda-13.0/lib64" }
    capabilities: { modalities: ["image"], backends: ["cuda"] }
    quirks: { notes: "recalibrar por equipo" }
    status: active                     # active | verified | experimental | incompatible
```

A declared-but-unavailable runtime is a **clean failure** (never a silent
fallback to another engine).

**b) Ensure a harness `backend` exists for its `kind`.** `backend` is the
dispatch key the harness resolves (see §4). If the `kind` is genuinely new, add
one loader function/module in `scripts/<area>/` — this is the only place that is
code, per the *registry + module-per-implementation* rule (CONVENTIONS §10.8.3).

---

## 4. The harness `backend` — dispatch registry

`scripts/imagegen/bench_imagegen.py` maps each elenco `backend` to a loader:

| `backend` | Loads | Notes |
|---|---|---|
| `diffusers` | a diffusers `pipeline` (e.g. `Flux2KleinPipeline`, `ZImagePipeline`) | 4-bit NF4 + CPU offload en 8 GB (`IMG_DIFFUSERS_QUANT`) |
| `bonsai` | `image-studio/backend_gpu` (gemlite INT2) | requires the torch≥2.10 shim |
| `sd_cpp` | `stable-diffusion.cpp` (`sd-cli`), GGUF | encoder a CPU, DiT+VAE a GPU (`--backend te=cpu,diffusion=cuda0,vae=cuda0`) |

A model with no `backend` is skipped (the harness cannot load it) — declare it
if the model is meant to be generated with.

---

## 5. Worked example — `sd_cpp` (Qwen-Image-2.1-Turbo / Sakura)

The concrete case that motivated this doc: a 7B DiT in **GGUF** with an 8B text
encoder, run on an **8 GB** laptop GPU.

**a) Build the engine** (once per machine):

```sh
git clone --depth 1 https://github.com/leejet/stable-diffusion.cpp ~/opt/stable-diffusion.cpp
cd ~/opt/stable-diffusion.cpp && git submodule update --init --recursive --depth 1

# nvcc está en /usr/local/cuda-13.0 pero FUERA del PATH → CUDACXX explícito.
# CUDA 13 admite GCC ≤ 15. sm_120 = Blackwell (RTX 50).
CUDACXX=/usr/local/cuda-13.0/bin/nvcc cmake -B build -DCMAKE_BUILD_TYPE=Release \
  -DSD_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=120 -DCUDAToolkit_ROOT=/usr/local/cuda-13.0
CUDACXX=/usr/local/cuda-13.0/bin/nvcc cmake --build build --target sd-cli -j"$(nproc)"
```

**b) Declare the runtime** in `runtimes.yaml`: `sd_cpp` with
`binary: ~/opt/stable-diffusion.cpp/build/bin/sd-cli` and
`env.LD_LIBRARY_PATH: /usr/local/cuda-13.0/lib64` (see the example).

**c) Declare the model** in `media_profiles.yaml` — the `sd_cpp:` block carries
the three GGUF/safetensors files + the backend assignment:

```yaml
  qwen_image_2_1_turbo:
    modality: image
    task: text2image
    backend: sd_cpp
    runtime: sd_cpp
    weights: "webmp3/Sakura-Qwen-Image-2.1-Turbo-Uncensored-GGUF"
    sampler: { steps: 8, guidance: 1.0, size: 1024, sampler: euler }
    vram_footprint: { peak_mb: 4707 }
    capabilities: ["photorealism", "typography", "portrait"]
    constraints: { dim_multiple: 16, max_pixels: 4194304, max_vram_mb: 6500 }
    adapters: ["snap_dims", "reject_oversize"]
    sd_cpp:
      diffusion_model: "~/opt/image-forge/models/qwen-image-2.1/Sakura-Image-2.1-Turbo-Q5_K_M-4.60GiB.gguf"
      text_encoder:    "~/opt/image-forge/models/qwen-image-2.1/Sakura-TextEncoder-Qwen3VL-8B-Uncensored-8bit-8.11GiB.gguf"
      vae:             "~/opt/image-forge/models/qwen-image-2.1/qwen_image_2.1_vae_bf16.safetensors"
      backend_assign: "te=cpu,diffusion=cuda0,vae=cuda0"
      extra_args: ["--flash-attn", "on", "--vae-tiling"]
      sigmas: "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0"
    license:
      id: "qwen-research"
      commercial_ok: false               # Qwen Research → NO comercial
      redistribution_ok: true
      attribution_required: true
      share_alike: false
      source: "https://huggingface.co/webmp3/Sakura-Qwen-Image-2.1-Turbo-Uncensored-GGUF"
    notes: "…"
```

**d) Generate** (via a job, so the preflight frees VRAM and it is resumable):

```sh
# elements/step llaman a gen_image.py --element (lee el elenco, backend sd_cpp)
red-pill job submit --recipe <recipe.yaml> --kick
```

Measured on the reference box (RTX 5070 Laptop 8 GB): **~32 s/image at 1024²**,
DiT 4.7 GB in VRAM, encoder 8.3 GB in RAM. `min_free_vram_mb` must be ≥ the
DiT+VAE footprint; the runner **defers** the job while VRAM is occupied (it does
not evict a resident LLM).

---

## 6. License gate

Every model **must** declare a `license:` block; the compliance gate
(`src/red_pill/core/model_license.py`) reads `commercial_ok`. Models under a
non-commercial license (e.g. `qwen-research`) are usable in `local`/personal
contexts but flagged for commercial runs. Omitting the block is a failure, not a
default.

---

## 7. Where things live (never mix)

- **El elenco y los runtimes** → `~/.config/red-pill/*.yaml` (datos de máquina).
- **El "cómo orquestar"** (venv, pasos del job, staging) → `configs/jobs/*.yaml`.
- **El código del harness** (loaders por `backend`) → `scripts/<area>/`.
- **La salida** → *staging* (`$RP_MEDIA_STAGING`); nunca al repo ni al desk.
