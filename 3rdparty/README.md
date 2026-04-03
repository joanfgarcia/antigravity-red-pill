# 3rdparty/ — External Dependencies

This directory contains external projects used by the Red Pill Protocol as
build-time or runtime dependencies. They are managed as **git submodules**
and are **NOT included** in distribution ZIPs (`git archive` excludes submodules).

## Contents

| Submodule | Upstream | License | Purpose |
|-----------|----------|---------|---------|
| `BitNet-1.58b/` | [microsoft/BitNet](https://github.com/microsoft/BitNet) | MIT | 1.58-bit ternary LLM inference engine (bitnet.cpp) |

## BitNet-1.58b

Fork: [joanfgarcia/BitNet-1.58b](https://github.com/joanfgarcia/BitNet-1.58b)

Our fork includes custom patches on top of Microsoft's upstream:
- **GPU VRAM stabilization** for 1.58b models with unified cache
- **Custom LUT kernel** (`include/bitnet-lut-kernels.h`) for RTX 5070
- **Distillation envelope** for sovereign inference pipeline
- **API server** (`gpu/api_server.py`) for local inference serving
- **Benchmark tooling** (`minion_benchmark.py`) for performance validation

### Setup (after cloning the main repo)

```bash
# 1. Initialize and clone the submodule (~80 MB source code only)
git submodule init
git submodule update

# 2. Build bitnet.cpp with CUDA support
cd 3rdparty/BitNet-1.58b
python setup_env.py -md 3rdparty/llama.cpp -q i2_s

# 3. Download model weights from HuggingFace
#    Models are NOT stored in git — they must be fetched separately.
#    See: docs/TECHNICAL/HARDWARE/BITNET_BENCHMARK_STUDY.md for full evaluation.
```

### Model Recommendations (from benchmark study)

> **TL;DR**: Only download **Falcon3-10B-Instruct**. The others fail zero-shot tasks.

| Model | Score | Verdict | Download? |
|-------|-------|---------|-----------|
| `tiiuae/Falcon3-10B-Instruct-1.58bit` | **98/100** | ✅ Production certified | **YES** |
| `HF1BitLLM/Llama3-8B-1.58-100B-tokens` | 23/100 | ❌ Base model, fails zero-shot | No |
| `microsoft/BitNet-b1.58-2B-4T` | 20/100 | ❌ Base model, fails zero-shot | No |

Base (pre-trained) models lack instruction tuning and cannot follow prompts,
extract JSON, or stop generation cleanly. Only **Instruct-tuned** models are
viable for the sovereign reasoning pipeline.

**Download the production model:**
```bash
# Falcon3-10B-Instruct — the ONLY certified model (~3.8 GB on disk after conversion)
huggingface-cli download tiiuae/Falcon3-10B-Instruct-1.58bit \
  --local-dir models/Falcon3-10B-Instruct-1.58bit

# Convert to GGUF
python 3rdparty/llama.cpp/convert_hf_to_gguf.py \
  models/Falcon3-10B-Instruct-1.58bit --outtype i2_s
```

### What's NOT in git

The following are generated locally and excluded via `.gitignore`:
- `models/**/*.gguf` — Quantized model weights (multi-GB each)
- `models/**/*.safetensors` — Original HuggingFace weights
- `gpu/checkpoints/` — Converted GPU inference checkpoints
- `build/` — Compiled binaries (llama-server, llama-cli, etc.)

### For Distribution ZIP Recipients

If you received a ZIP package instead of cloning the repo, this directory
will be **empty**. To set up BitNet inference:

1. Ensure you have a local git repo (see AGENT_UPDATE_GUIDE §7.2.1)
2. Run `git submodule init && git submodule update`
3. Follow the setup steps above
4. Verify: `python -c "from red_pill.inference.bitnet.runner import BitNetRunner; print('OK')"`

> **Note**: BitNet inference is **optional**. The Red Pill Protocol functions
> fully without it — it only enables local 1.58-bit model inference for
> sovereign reasoning tasks.
