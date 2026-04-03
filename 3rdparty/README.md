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
#    See: docs/TECHNICAL/HARDWARE/BITNET_1_58_SCALING_LAWS.md
huggingface-cli download 1bitLLM/bitnet_b1_58-3B --local-dir models/bitnet_b1_58-3B
huggingface-cli download HF1BitLLM/Llama3-8B-1.58-100B-tokens --local-dir models/Llama3-8B-1.58-100B-tokens

# 4. Convert to GGUF format
python 3rdparty/llama.cpp/convert_hf_to_gguf.py models/bitnet_b1_58-3B --outtype i2_s
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
