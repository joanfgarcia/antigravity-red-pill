# Model Storage & Deduplication

How models are stored on this machine and the rules that keep **no duplicated
gigabytes**. Covers LLM (text), image and audio models, and future non-Hugging
Face sources.

Status: enforced. Scope: `~/opt/*-forge`, `~/.local/share/red-pill`, machine config.

---

## 1. Where things live

| Kind | Location | Notes |
|---|---|---|
| **LLM (text) models** | `~/.local/share/red-pill/models/` (`get_models_dir()`) | single-file `.gguf`; kernel models (Granite, Qwen, …) |
| **Image models** | `~/opt/image-forge/` | **multi-part** (denoiser + text encoder + VAE + vision) → own harness |
| **Audio models** | `~/opt/audio-forge/` | multi-part; four venvs (stacks clash) |
| **Music (symbolic)** | `~/opt/music-forge/` | tool-chain, not a model |
| **HF cache (media)** | `~/opt/<area>-forge/hf-cache` (`HF_HOME`, pinned) | HF downloads; **never** `~/.cache/huggingface` |
| **uv cache** | `~/.cache/uv` | hardlink source for venvs (prunable) |

**Why media ≠ LLM layout:** media models are **families of several files** with a
bespoke harness on top; keeping each family in its own forge folder is cleaner
than mixing them with the single-file LLM `.gguf`s. (`REDPILL_IMAGE_MODELS_DIR`
= `~/.local/share/red-pill/models/image` exists as the declared canonical but the
media harness does not use it — see §5.)

---

## 2. Deduplication already in place

- **Hugging Face cache — content-addressed blob store.** Each forge's
  `hf-cache/hub/blobs/` is a **global** store keyed by content hash; each model's
  `snapshots/<rev>/…` are **symlinks** into it. A component shared by several
  models (tokenizer, VAE, configs, shared encoders) is stored **once**. Verified:
  a blob referenced by Z-Image-Turbo + FLUX.2-klein + Bonsai simultaneously.
- **uv venvs — hardlinks.** Packages are hardlinked from `~/.cache/uv` into each
  venv: `libtorch_cuda.so` (~1 GB) shows **5 links, same inode** across venvs →
  the bytes exist **once** on disk. `du` on individual venvs is misleading.

So "many copies of torch" and "shared components duplicated" are **already
avoided** by the tooling — do not "fix" them by hand.

---

## 3. Rules (the contract)

1. **One HF cache per area**, pinned: `HF_HOME=~/opt/<area>-forge/hf-cache`
   (set by `_setup_caches()` / `bootstrap.sh`). Never download media models into
   `~/.cache/huggingface` — a second cache means a second copy of every model.
2. **Shared components → `~/opt/<area>-forge/models/_shared/<component>`**.
   When two models of a family reuse the same piece (e.g. a Qwen3-VL text
   encoder for several Qwen-Image models), store it **once** in `_shared/` and
   point every elenco entry (`text_encoder:` / `vae:` / `vision:`) at that path.
   Per-model parts (the denoiser) stay in the model's own folder.
3. **Non-HF sources** (future): store inside the area's `models/<model>/`
   directory too, and record the source + content hash in a small manifest so the
   storage checker (§4) can detect cross-source duplicates. Do not re-download a
   component you already have under another name — reference the existing path.
4. **No orphan blobs / partial downloads.** Interrupted HF downloads leave
   `<hash>.<etag>.incomplete` files. They are garbage — remove them
   (`find <cache> -name '*.incomplete' -delete`). A model whose snapshot is
   incomplete is **not** usable offline.
5. **Prune the uv cache** periodically: `uv cache prune` (it only holds the
   hardlink source; pruning never breaks installed venvs).

---

## 4. Storage checker (proposed)

A `red-pill media storage` (or `scripts/imagegen/storage_check.py`) that:
- walks the model dirs (`~/opt/*-forge`, `~/.local/share/red-pill/models`);
- clusters files by size, then confirms by hash;
- reports **real** duplicates (same inode = hardlink → ignore), reclaimable space,
  `.incomplete` leftovers, and models present in more than one cache.
Goal: "no duplicated gigabytes" is checkable, not just a promise.

---

## 5. Custom / non-HF models — `REDPILL_IMAGE_MODELS_DIR`

Models that are **not a single HF repo** — non-HF sources (tar/zip/direct web) and
**multi-repo compositions** (e.g. Sakura image = denoiser + text encoder + VAE +
mmproj pulled from three different repos) — cannot live in the HF cache. They go to:

```
REDPILL_IMAGE_MODELS_DIR  =  ~/opt/red-pill-custom-image-models/<modelo>/
```

(Fixed as the default; overridable by env. Composed/converted models are placed
here with **explicit file paths** referenced from the elenco `sd_cpp:` block.)

The rule of thumb: a **single HF repo** → HF cache (`HF_HOME`, §2); anything we
**compose ourselves** → `REDPILL_IMAGE_MODELS_DIR`. Both are in `~/opt`, each family
in its own folder, and `storage_check` audits **all** of them for duplicates.

---

## 5b. Registro de procedencia (proceso — `model_approve.py`)

El valor de "instalar" no es reescribir el almacenamiento, sino **dejar constancia**.
Tras **probar** un modelo, se registra su **procedencia** con revisión **pinada**:

```sh
# repo HF: fija el commit + sha256 (lfs.oid) de cada fichero, desde la metadata de HF
scripts/model_approve.py --repo Tongyi-MAI/Z-Image-Turbo --note "probado 1024²"

# custom / composición multi-repo: hashea los ficheros locales
scripts/model_approve.py --name qwen-image-2.1 --file diffusion_model=ruta.gguf \
  --file text_encoder=ruta.gguf --file vae=ruta.safetensors --note "probado"

scripts/model_approve.py --list
```

Manifiesto: `~/.local/share/red-pill/model_manifest.json` (o `$REDPILL_MODEL_MANIFEST`).
**No** mueve ni limpia nada — solo registra (el `<hash>.incomplete`/limpieza de
cachés sigue siendo responsabilidad de `storage_check` + `uv cache prune`).

## 6. Reference numbers (this box, 2026-10-14)

- `~/.local/share/red-pill/models` — 84 GB (LLM `.gguf`).
- `~/opt/image-forge/hf-cache` — 50 GB (image blobs, deduped); `models/` 15 GB (Qwen/Sakura parts).
- `~/opt/audio-forge/hf-cache` — 43 GB.
- `~/.cache/uv` — 30 GB (hardlink source; prunable).
- Venvs share torch/CUDA via hardlinks → not counted as duplicates.
