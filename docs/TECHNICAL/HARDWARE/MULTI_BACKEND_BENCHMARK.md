# Multi-Backend Inference Benchmark

**Date:** 2026-05-22 | **Platform:** OMEN 16 (AMD Ryzen AI 9 365)

---

## Hardware Inventory

| Component | Device | Memory | Driver / Stack |
|-----------|--------|--------|----------------|
| **dGPU** | NVIDIA RTX 5070 Laptop | 8 GB GDDR7 | CUDA 13.0 |
| **iGPU** | AMD Radeon 880M (GFX1150) | Shared (32 GB DDR5) | RADV (Mesa Vulkan) |
| **CPU** | AMD Ryzen AI 9 365 | 32 GB DDR5 | 20 threads, AVX-512/VNNI |
| **NPU** | AMD XDNA2 Strix (8 columns) | Dedicated SRAM | amdxdna 0.6, FW 1.1.2.64 |

---

## Models Tested

### BitNet — Falcon3-10B-Instruct-1.58bit (GGUF I2_S)

| Property | Value |
|----------|-------|
| Parameters | 10.31B |
| Quantization | I2_S — 2 bpw ternary ({-1, 0, +1}) |
| Weights size | 3.99 GiB (3.33 BPW) |
| Max context | 32768 tokens |
| Backends | CUDA, Vulkan, CPU |
| NPU compatible | ❌ No (ternary format unsupported) |

### FastFlowLM — NPU Models (INT4 q4nx)

| Model | Parameters | Size | Backend |
|-------|:----------:|:----:|---------|
| Qwen3-0.6B-NPU2 | 0.6B | 663 MB | NPU (XDNA2) |
| Qwen3-8B-NPU2 | 8B | ~5 GB | NPU (XDNA2) |

---

## Benchmark Results

### Falcon3-10B — BitNet I2_S (llama.cpp)

**Test conditions:** Prompt = "What is quantum computing? Answer in exactly 3 sentences.", `-n 64`, `-c 2048` unless noted.

| Backend | Device | `-ngl` | `-c` | Gen (tok/s) | Prompt (tok/s) | Total | Status |
|---------|--------|:------:|:----:|:-----------:|:--------------:|:-----:|:------:|
| **CUDA** | RTX 5070 | 99 | 2048 | **23.06** | **54.08** | 2.96s | ✅ Reference |
| **CPU** | Ryzen AI 9 (16T) | 0 | 2048 | **12.87** | **18.82** | 5.54s | ✅ build_vulkan |
| **CUDA split** | RTX 5070 + CPU | 30 | **32768** | **8.59** | **29.63** | 7.75s | ✅ Full context |
| **Vulkan** | Radeon 880M | 99 | 2048 | **4.83** | **15.43** | 13.83s | ✅ iGPU |
| **Vulkan** | RTX 5070 | 99 | 2048 | 3.23 | 14.83 | 20.30s | ✅ Slower than CUDA |

### NPU — FastFlowLM (XDNA2)

| Model | Params | Gen (tok/s) | Prefill (tok/s) | Total tokens | Total time |
|-------|:------:|:-----------:|:---------------:|:------------:|:----------:|
| **Qwen3-0.6B** | 0.6B | **96.31** | **47.09** | 177 | 2.19s |
| **Qwen3-8B** | 8B | **10.60** | **13.51** | 2373 | 224.4s |

### Energy Efficiency Comparison (estimated)

| Backend | Model | tok/s | Power (est.) | Efficiency (tok/s/W) |
|---------|-------|:-----:|:------------:|:--------------------:|
| **NPU** | Qwen3-0.6B | 96.31 | ~2W | **~48.2** |
| **NPU** | Qwen3-8B | 10.60 | ~2W | **~5.3** |
| **CUDA** | Falcon3-10B | 23.06 | ~80W | ~0.29 |
| **CPU** | Falcon3-10B | 12.87 | ~45W | ~0.29 |
| **Vulkan** | Falcon3-10B | 4.83 | ~15W | ~0.32 |

> [!IMPORTANT]
> The NPU is **18x more energy-efficient** than CUDA for comparable model sizes (8B vs 10B), producing similar tok/s at a fraction of the power.

---

## Key Findings

### 1. CUDA is the fastest for BitNet (23 tok/s)
All 41 layers offloaded to GPU. 3.3 GB weights + 320 MB KV cache = ~3.6 GB VRAM at ctx=2048.

### 2. NPU delivers surprising performance (10.6–96 tok/s)
FastFlowLM on the XDNA2 NPU runs INT4-quantized models at competitive speeds:
- Small models (0.6B): **96 tok/s** — faster than any other backend
- Large models (8B): **10.6 tok/s** — comparable to CPU, at 1/22 the power

```bash
# NPU setup
sudo prlimit --memlock=unlimited --pid $$
flm run qwen3:0.6b   # 96 tok/s
flm run qwen3:8b     # 10.6 tok/s
```

### 3. CPU works at 12.87 tok/s (via Vulkan build)
The CPU path crashes with `build_cuda` due to CUDA backend allocator interference. Use `build_vulkan` binary:
```bash
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json \
  build_vulkan/bin/llama-cli -m model.gguf -ngl 0 -t 16 -c 2048
```

> [!TIP]
> For CPU-only inference, always use `build_vulkan/bin/llama-cli` with `-ngl 0`.

#### CPU Crash Root Cause (build_cuda only)
The LUT kernels in `bitnet-lut-kernels.h` have hardcoded tile dimensions for Llama-7B (4096×14336). Falcon3-10B uses 3072×23040 which doesn't match → `bm=0` → division by zero → memory corruption. A guard was added but the CUDA build has a deeper backend allocator issue mixing CUDA/CPU tensors with `-ngl 0`.

### 4. Radeon 880M iGPU works via Vulkan (4.83 tok/s)
Requires forcing the ICD loader:
```bash
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json \
  build_vulkan/bin/llama-cli -m model.gguf -ngl 99 ...
```

### 5. Full 32K context via layer splitting (8.59 tok/s)
Reducing GPU layers from 41 to 30 frees VRAM for the KV cache:

| VRAM allocation | ctx=2048 (ngl=99) | ctx=32768 (ngl=30) |
|----------------|:-:|:-:|
| Weights | 3317 MiB | 1912 MiB |
| KV cache | 320 MiB | 5120 MiB |
| Compute | 262 MiB | ~262 MiB |
| **Total** | **3899 MiB** | **7294 MiB** |

### 6. NPU cannot run BitNet 1.58-bit
The XDNA2 NPU supports INT4/INT8/BFP16 — **not** the ternary format ({-1, 0, +1}). FastFlowLM provides pre-quantized INT4 models for NPU use.

### 7. ROCm/HIP not recommended for iGPU
Research confirmed Vulkan outperforms ROCm for the Radeon 880M:
- gfx1150 not officially supported, requires `HSA_OVERRIDE_GFX_VERSION` hacks
- Both backends DDR5-bandwidth-bound on iGPU → similar performance
- Vulkan works out-of-the-box, ROCm requires workarounds

---

## Recommended Configurations

### Production — Maximum Speed
```bash
build_cuda/bin/llama-cli -m model.gguf -ngl 99 -c 16384
# → 23 tok/s, ~5.8 GB VRAM
```

### Large Context — Full 32K Window
```bash
build_cuda/bin/llama-cli -m model.gguf -ngl 30 -c 32768
# → 8.59 tok/s, ~7.3 GB VRAM
```

### Low Power — NPU (background inference)
```bash
sudo prlimit --memlock=unlimited --pid $$
flm run qwen3:8b
# → 10.6 tok/s, ~2W power
```

### Ultra Low Power — NPU (small model)
```bash
flm run qwen3:0.6b
# → 96 tok/s, ~2W power
```

### Battery / dGPU Busy — iGPU Vulkan
```bash
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json \
  build_vulkan/bin/llama-cli -m model.gguf -ngl 99 -c 2048
# → 4.83 tok/s, shared system RAM
```

### CPU Only — No GPU Required
```bash
build_vulkan/bin/llama-cli -m model.gguf -ngl 0 -t 16 -c 2048
# → 12.87 tok/s, ~45W
```

---

## NPU Setup Reference

### Prerequisites
```bash
# Install XRT + amdxdna driver
sudo add-apt-repository ppa:lemonade-team/stable
sudo apt update
sudo apt install libxrt-npu2 amdxdna-dkms

# Install FastFlowLM (download .deb from GitHub releases)
sudo apt install /tmp/fastflowlm_0.9.42_ubuntu25.10_amd64.deb

# Configure memlock (permanent, requires re-login)
sudo bash -c 'echo "* soft memlock unlimited" >> /etc/security/limits.conf'
sudo bash -c 'echo "* hard memlock unlimited" >> /etc/security/limits.conf'
```

### Validation
```bash
flm validate
# Expected output:
# [Linux]  NPU: /dev/accel/accel0 with 8 columns
# [Linux]  NPU FW Version: 1.1.2.64
# [Linux]  amdxdna version: 0.6
# [Linux]  Memlock Limit: infinity
```

### Available NPU Models
```
deepseek-r1:8b, gemma3:4b, llama3.1:8b, llama3.2:1b/3b,
phi4-mini-it:4b, qwen3:0.6b/1.7b/4b/8b, qwen3.5:0.8b/2b/4b/9b,
whisper-v3:turbo, and more
```

---

## Working Binaries

```
3rdparty/BitNet-1.58b/.backup/
├── llama-cli-cuda-working     # CUDA build — reference (23 tok/s)
└── llama-cli-vulkan-working   # Vulkan build — Radeon 880M + CPU compatible
```

## Resolved Issues

- [x] **CPU crash**: Root cause identified — LUT kernel dimension mismatch + CUDA allocator mixing. Workaround: use `build_vulkan` binary for CPU inference.
- [x] **NPU setup**: FastFlowLM v0.9.42 installed, firmware updated to 1.1.2.64, amdxdna 0.6 loaded.
- [x] **model_profiles.yaml**: Updated with multi-backend configurations.

## Open Items

- [ ] **NPU larger models**: Test `deepseek-r1:8b`, `llama3.1:8b` on NPU for comparison
- [ ] **NPU as red-pill backend**: Integrate FastFlowLM serve mode as an inference provider
- [ ] **BitNet CPU fix upstream**: Submit PR to BitNet fork with the LUT dimension guard
