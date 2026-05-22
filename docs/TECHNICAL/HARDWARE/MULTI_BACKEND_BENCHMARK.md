# Falcon3-10B-1.58bit Multi-Backend Benchmark

**Date:** 2026-05-22 | **Platform:** OMEN 16 (AMD Ryzen AI 9 365)

---

## Hardware Inventory

| Component | Device | Memory | Driver |
|-----------|--------|--------|--------|
| **dGPU** | NVIDIA RTX 5070 Laptop | 8 GB GDDR7 | CUDA 12.x |
| **iGPU** | AMD Radeon 880M (GFX1150) | Shared (system RAM) | RADV (Mesa Vulkan) |
| **CPU** | AMD Ryzen AI 9 365 | 32 GB DDR5 | 20 threads |
| **NPU** | AMD XDNA2 Strix | — | 50 TOPS (INT8) |

## Model

| Property | Value |
|----------|-------|
| Name | Falcon3-10B-Instruct-1.58bit |
| Format | GGUF (I2_S — 2 bpw ternary) |
| Parameters | 10.31B |
| Weights size | 3.99 GiB (3.33 BPW) |
| Max context | 32768 tokens |
| Path | `models/Falcon3-10B-Instruct-1.58bit/ggml-model-i2_s.gguf` |

---

## Benchmark Results

### Test Conditions
- Prompt: `"What is quantum computing? Answer in exactly 3 sentences."`
- Generation: 64 tokens (`-n 64`)
- Context: 2048 unless noted (`-c 2048`)
- Binary: `build_cuda/bin/llama-cli` (CUDA) or `build_vulkan/bin/llama-cli` (Vulkan)

### Performance Matrix

| Backend | Device | `-ngl` | `-c` | Gen (tok/s) | Prompt (tok/s) | Total | Status |
|---------|--------|:------:|:----:|:-----------:|:--------------:|:-----:|:------:|
| **CUDA** | RTX 5070 | 99 | 2048 | **23.06** | **54.08** | 2.96s | ✅ Reference |
| **CPU** | Ryzen AI 9 (16T) | 0 | 2048 | **12.87** | **18.82** | 5.54s | ✅ build_vulkan |
| **CUDA split** | RTX 5070 + CPU | 30 | **32768** | **8.59** | **29.63** | 7.75s | ✅ Full context |
| **Vulkan** | Radeon 880M | 99 | 2048 | **4.83** | **15.43** | 13.83s | ✅ iGPU |
| **Vulkan** | RTX 5070 | 99 | 2048 | 3.23 | 14.83 | 20.30s | ✅ Slower than CUDA |
| **NPU** | XDNA2 | — | — | — | — | — | ❌ Incompatible |

### Key Findings

#### 1. CUDA is the fastest backend (23 tok/s)
All 41 layers offloaded to GPU. 3.3 GB weights + 320 MB KV cache = ~3.6 GB VRAM at ctx=2048.

#### 2. Radeon 880M iGPU works via Vulkan (4.83 tok/s)
Requires forcing the ICD loader to exclude NVIDIA:
```bash
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json \
  build_vulkan/bin/llama-cli -m model.gguf -ngl 99 ...
```
Without this, llama.cpp selects the NVIDIA device by default even in Vulkan mode.

#### 3. Full 32K context is achievable with layer splitting
By reducing GPU layers from 41 to 30, the KV cache for 32768 tokens fits in VRAM:

| VRAM allocation | ctx=2048 (ngl=99) | ctx=32768 (ngl=30) |
|----------------|:-:|:-:|
| Weights | 3317 MiB | 1912 MiB |
| KV cache | 320 MiB | 5120 MiB |
| Compute | 262 MiB | ~262 MiB |
| **Total** | **3899 MiB** | **7294 MiB** |

Tradeoff: ~8.59 tok/s instead of 23 tok/s, but full 32K context window.

#### 4. CPU works at 12.87 tok/s (via Vulkan build)
The CPU path crashes with `build_cuda` binary due to CUDA backend allocator interference when `-ngl 0`. The `build_vulkan` binary handles CPU fallback correctly:
```bash
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json \
  build_vulkan/bin/llama-cli -m model.gguf -ngl 0 -t 16 -c 2048
# → 12.87 tok/s — 56% of CUDA speed, no GPU needed
```

> [!TIP]
> For CPU-only inference, always use `build_vulkan/bin/llama-cli` with `-ngl 0`. The CUDA build's CPU path is broken due to backend allocator mixing.

#### 5. NPU cannot run BitNet 1.58-bit
The AMD XDNA2 NPU supports INT4, INT8, BFP16, and BFloat16 quantization — but **not** the ternary weight format ({-1, 0, +1}) used by BitNet 1.58-bit. The custom `BitLinear` operators are not supported by any NPU software stack.

**Alternative path**: Re-quantize the standard Falcon3-10B-Instruct (FP16) model with AMD Quark to INT4, then run via FastFlowLM on Linux. This would be a **separate model file**, not a replacement of the current 1.58-bit GGUF.

---

## Recommended Configurations

### Production (default)
```bash
# Maximum speed, 16K context
build_cuda/bin/llama-cli -m model.gguf -ngl 99 -c 16384
# → 23 tok/s, 5.8 GB VRAM
```

### Large Context
```bash
# Full 32K context, moderate speed
build_cuda/bin/llama-cli -m model.gguf -ngl 30 -c 32768
# → 8.59 tok/s, 7.3 GB VRAM
```

### Low Power (iGPU)
```bash
# When dGPU is busy or for battery savings
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json \
  build_vulkan/bin/llama-cli -m model.gguf -ngl 99 -c 2048
# → 4.83 tok/s, uses shared system RAM
```

---

## Working Binaries

Verified working binaries are backed up at:
```
3rdparty/BitNet-1.58b/.backup/
├── llama-cli-cuda-working     # CUDA build — reference
└── llama-cli-vulkan-working   # Vulkan build — Radeon 880M compatible
```

## Open Issues

- [ ] **CPU crash**: `GGML_ASSERT` in `ggml.c:14199` with `-ngl 0`. Needs investigation — likely bug in I2_S dequantization kernel CPU path.
- [ ] **NPU INT4 variant**: Consider re-quantizing standard Falcon3-10B to INT4 for NPU via AMD Quark. Must be a separate model file.
- [ ] **model_profiles.yaml**: Add `max_context`, `recommended_ngl`, and `backend` properties per model variant.
