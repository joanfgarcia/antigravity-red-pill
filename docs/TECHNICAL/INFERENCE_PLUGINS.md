# BitNet Inference Plugin System

> Multi-backend inference for Falcon 3 10B 1.58-bit (BitNet b1.58)
> on the HP OMEN (AMD Ryzen AI 9 HX 370 / NVIDIA RTX 5070 / 32GB RAM)

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Current Flavors](#current-flavors)
3. [Missing / Future Flavors](#missing--future-flavors)
4. [How to Add a New Flavor](#how-to-add-a-new-flavor)
5. [Activating & Deactivating Plugins](#activating--deactivating-plugins)
6. [Benchmark Integration](#benchmark-integration)
7. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
BitNet-1.58b/
├── 3rdparty/llama.cpp/          # Core engine (patched for I2_S support)
│   └── ggml/src/
│       ├── ggml-common.h        # block_i2_s struct (shared by all backends)
│       ├── ggml-cuda.cu         # CUDA + ROCm (HIP) backend
│       ├── ggml-cuda/           # GPU kernels (dequantize, DMMV, convert)
│       ├── ggml-vulkan.cpp      # Vulkan backend
│       └── ggml-bitnet-axon-*   # Custom Axon acceleration layer
├── src/
│   └── ggml-bitnet-mad.cpp      # CPU MAD (Multiply-Add) kernels (AVX2/ARM NEON)
├── build_cpu/                   # CPU-only build
├── build_cuda/                  # NVIDIA CUDA build
├── build_rocm/                  # AMD ROCm/HIP build (Radeon 880M iGPU)
├── build_vulkan/                # Vulkan build
└── build_npu/                   # AMD XDNA2 NPU build
```

### How It Works

Each **flavor** is an independent CMake build in its own `build_<name>/` directory. They all share:

- The **same source tree** (`3rdparty/llama.cpp/`)
- The **same model file** (`.gguf` format)
- The **same server binary API** (`llama-server` on port 8080)

The only differences are:
1. **CMake flags** that enable/disable GPU backends
2. **Environment variables** at runtime (library paths, GPU overrides)
3. **`-ngl` flag** (number of GPU layers: 0=CPU, 35=full GPU offload)

---

## Current Flavors

### ✅ CPU (`build_cpu`)

| Property | Value |
|---|---|
| **Status** | Stable |
| **Prompt eval** | 23.5 tok/s |
| **Generation** | 2.57 tok/s |
| **Build flag** | (none — default) |
| **`-ngl`** | `0` |
| **Env vars** | `GGML_BITNET_FORCE_AXON=CPU` |
| **Dependencies** | GCC/Clang with AVX2 support |

```bash
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
```

---

### ✅ CUDA (`build_cuda`) — NVIDIA RTX 5070

| Property | Value |
|---|---|
| **Status** | Stable |
| **Prompt eval** | 55.9 tok/s |
| **Generation** | 10.6 tok/s (4.1x vs CPU) |
| **Build flag** | `-DGGML_CUDA=ON` |
| **`-ngl`** | `35` |
| **Env vars** | `GGML_BITNET_FORCE_AXON=CUDA` |
| **Dependencies** | CUDA Toolkit 12.x, `nvcc` |

```bash
cmake .. -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
```

> **Note**: The `block_i2_s` struct in `ggml-common.h` was fixed to use
> `float d` (4 bytes) + `uint8_t qs[32]` (32 bytes) = 36 bytes / 128 elements.
> Without this fix, all GPU backends crash with illegal memory access.

---

### ✅ ROCm (`build_rocm`) — AMD Radeon 880M iGPU

| Property | Value |
|---|---|
| **Status** | Stable (with workarounds) |
| **Prompt eval** | 7.67 tok/s |
| **Generation** | 5.15 tok/s (2x vs CPU) |
| **Build flag** | `-DGGML_HIPBLAS=ON` |
| **`-ngl`** | `35` |
| **Env vars** | `HSA_OVERRIDE_GFX_VERSION=11.0.0` |
| **Dependencies** | ROCm 6.4.1 (`/opt/rocm-6.4.1/`), `libxml2.so.2` symlink |

```bash
cmake .. \
  -DGGML_HIPBLAS=ON \
  -DAMDGPU_TARGETS="gfx1100;gfx1150" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_HIP_COMPILER=/opt/rocm-6.4.1/lib/llvm/bin/clang++ \
  -DCMAKE_HIP_COMPILER_ROCM_ROOT=/opt/rocm-6.4.1 \
  -DCMAKE_PREFIX_PATH=/opt/rocm-6.4.1 \
  -DGGML_CUDA_FORCE_DMMV=ON
cmake --build . -j$(nproc)
```

**Runtime requirements:**
```bash
# Mandatory env vars
export HSA_OVERRIDE_GFX_VERSION=11.0.0
export LD_LIBRARY_PATH=/opt/rocm-6.4.1/lib:$LD_LIBRARY_PATH
```

**System prerequisites (one-time):**
```bash
# ROCm 6.4.1 from AMD
sudo apt install hip-runtime-amd6.4.1 hip-dev6.4.1 rocblas-dev6.4.1 hipblas-dev6.4.1

# libxml2 ABI compatibility
sudo ln -s /usr/lib/x86_64-linux-gnu/libxml2.so.16 /usr/lib/x86_64-linux-gnu/libxml2.so.2

# Tensile kernels for gfx1150
sudo ln -s /opt/rocm-6.4.1/lib/rocblas/library/TensileLibrary_lazy_gfx1100.dat \
           /opt/rocm-6.4.1/lib/rocblas/library/TensileLibrary_lazy_gfx1150.dat
```

---

### ✅ NPU (`build_npu`) — AMD XDNA2

| Property | Value |
|---|---|
| **Status** | Stable |
| **Prompt eval** | 18.2 tok/s |
| **Generation** | 15.8 tok/s (6.1x vs CPU) |
| **Build flag** | Custom (pre-built) |
| **`-ngl`** | `0` (NPU handles acceleration internally) |
| **Env vars** | (none) |
| **Dependencies** | `amdxdna` kernel driver (built-in 6.17+), `/dev/accel/accel0` |

The NPU build uses a custom integration path. The binary was pre-built and works
directly with the XDNA2 hardware via the DRM Accel subsystem.

**Alternative: FastFlowLM** (for non-BitNet models):
```bash
sudo add-apt-repository ppa:lemonade-team/stable
sudo apt install fastflowlm
flm run llama3.2:1b
```

---

### 🟡 Vulkan (`build_vulkan`)

| Property | Value |
|---|---|
| **Status** | Build exists, not benchmarked |
| **Build flag** | `-DGGML_VULKAN=ON` |
| **`-ngl`** | `35` |
| **Env vars** | `GGML_BITNET_FORCE_AXON=VULKAN` |
| **Dependencies** | Vulkan SDK, `libvulkan-dev` |

```bash
cmake .. -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
```

> **Assessment**: Vulkan is a universal fallback but typically 30-50% slower than
> native CUDA/ROCm. Worth keeping for portability but not a priority backend.

---

## Missing / Future Flavors

### 🔲 Metal (`build_metal`) — macOS (Apple Silicon)

| Priority | High (if targeting Mac deployment) |
|---|---|
| **Build flag** | `-DGGML_METAL=ON` |
| **How to add** | See [How to Add a New Flavor](#how-to-add-a-new-flavor) |
| **Notes** | llama.cpp has native Metal support. Block I2_S should work if `ggml-common.h` fix is applied. No Axon CUDA needed. |

```bash
# On macOS with Xcode
cmake .. -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release
```

---

### 🔲 oneAPI/SYCL (`build_sycl`) — Intel iGPU (Arc, UHD)

| Priority | Medium |
|---|---|
| **Build flag** | `-DGGML_SYCL=ON` |
| **Dependencies** | Intel oneAPI Base Toolkit, `icpx` compiler |
| **Notes** | llama.cpp supports SYCL for Intel GPUs. Useful for Intel-based laptops. |

```bash
source /opt/intel/oneapi/setvars.sh
cmake .. -DGGML_SYCL=ON -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx
```

---

### 🔲 OpenVINO (`build_openvino`) — Intel NPU/CPU

| Priority | Medium-Low |
|---|---|
| **How** | ONNX export → OpenVINO IR → NPU/CPU inference |
| **Dependencies** | OpenVINO Runtime 2024.x+ |
| **Notes** | Not a direct llama.cpp backend. Requires model conversion to ONNX → IR format. Better suited for Intel NPUs (Meteor Lake+). |

---

### 🔲 MUSA (`build_musa`) — Moore Threads GPU

| Priority | Low (China-specific hardware) |
|---|---|
| **Build flag** | `-DGGML_MUSA=ON` |
| **Notes** | llama.cpp has experimental MUSA support. |

---

### 🔲 CANN (`build_cann`) — Huawei Ascend NPU

| Priority | Low (Enterprise/China) |
|---|---|
| **Build flag** | `-DGGML_CANN=ON` |
| **Notes** | llama.cpp has experimental CANN support. |

---

## How to Add a New Flavor

### Step 1: Create the build directory

```bash
cd BitNet-1.58b
mkdir build_<name>
cd build_<name>
```

### Step 2: Configure with CMake

```bash
cmake .. -DGGML_<BACKEND>=ON -DCMAKE_BUILD_TYPE=Release [extra flags]
```

### Step 3: Build

```bash
cmake --build . -j$(nproc) --target llama-server llama-cli
```

### Step 4: Test manually

```bash
LD_LIBRARY_PATH=3rdparty/llama.cpp/src:3rdparty/llama.cpp/ggml/src \
  ./bin/llama-server -m /path/to/model.gguf -ngl <N> -c 512 --port 8080
```

### Step 5: Register in benchmark scripts

Edit **both** scripts in `scripts/`:

#### `bitnet_sovereign_bench.py`
```python
FLAVORS = {
    ...
    "<NAME>": {"dir": "build_<name>", "ngl": <N>},
}
```

Add env vars in the `run_flavor_bench()` function:
```python
elif flavor_name == "<NAME>":
    env["SOME_VAR"] = "value"
```

Add library paths if needed:
```python
if flavor_name == "<NAME>":
    libs.insert(0, "/path/to/backend/lib")
```

#### `test_all_bunker_flavors.py`
```python
FLAVORS = {
    ...
    "<NAME>": {"dir": "build_<name>", "flags": ["-ngl", "<N>"]},
}
```

### Step 6: Verify

```bash
python3 scripts/test_all_bunker_flavors.py
```

---

## Activating & Deactivating Plugins

### Quick toggle: Edit the FLAVORS dict

Comment out any flavor you don't want to test:

```python
FLAVORS = {
    "CPU":    {"dir": "build_cpu",    "ngl": 0},
    "CUDA":   {"dir": "build_cuda",   "ngl": 35},
    # "VULKAN": {"dir": "build_vulkan", "ngl": 35},  # disabled
    "ROCm":   {"dir": "build_rocm",   "ngl": 35},
    "NPU":    {"dir": "build_npu",    "ngl": 0},
}
```

### Auto-detection (not yet implemented)

A future improvement would be to auto-detect available backends:

```python
def detect_flavors():
    flavors = {"CPU": {"dir": "build_cpu", "ngl": 0}}

    if os.path.exists(f"{BITNET_DIR}/build_cuda/bin/llama-server"):
        flavors["CUDA"] = {"dir": "build_cuda", "ngl": 35}

    if os.path.exists(f"{BITNET_DIR}/build_rocm/bin/llama-server"):
        flavors["ROCm"] = {"dir": "build_rocm", "ngl": 35}

    if os.path.exists(f"{BITNET_DIR}/build_npu/bin/llama-server"):
        flavors["NPU"] = {"dir": "build_npu", "ngl": 0}

    return flavors
```

### Environment variable override

Run only specific flavors via command line:

```bash
BITNET_FLAVORS="CPU,CUDA" python3 scripts/bitnet_sovereign_bench.py
```

*(Not yet implemented — suggested enhancement)*

---

## Benchmark Integration

### Quick smoke test (1 query per flavor)
```bash
python3 scripts/test_all_bunker_flavors.py
```

### Full benchmark (4 queries × N flavors)
```bash
python3 scripts/bitnet_sovereign_bench.py
```

Output: `docs/BENCHMARKS/BITNET_QUAD_FLAVOR_REPORT.md`

### Performance Summary (April 2026)

```
═══════════════════════════════════════════
 INFORME FINAL DE ARMONÍA DEL BÜNKER
═══════════════════════════════════════════
 MOTOR     │ PROMPT (t/s) │ GEN (t/s) │ vs CPU
───────────┼──────────────┼───────────┼────────
 CPU       │ 23.5         │ 2.57      │ 1.0x
 ROCm iGPU │ 7.67         │ 5.15      │ 2.0x
 CUDA RTX  │ 55.9         │ 10.6      │ 4.1x
 NPU XDNA2 │ 18.2         │ 15.8      │ 6.1x
═══════════════════════════════════════════
```

---

## Troubleshooting

### ROCm: `free(): invalid size`
**Cause**: Ubuntu's `libamdhip64` 5.7 doesn't support gfx1150.
**Fix**: Install ROCm 6.4.1 from AMD's official repo and set `LD_LIBRARY_PATH=/opt/rocm-6.4.1/lib`.

### ROCm: `CUBLAS_STATUS_INTERNAL_ERROR`
**Cause**: Tensile (rocBLAS) lacks gfx1150 kernels.
**Fix**: `HSA_OVERRIDE_GFX_VERSION=11.0.0` + build with `-DAMDGPU_TARGETS="gfx1100;gfx1150"`.

### CUDA: `illegal memory access`
**Cause**: Wrong `block_i2_s` struct in `ggml-common.h`.
**Fix**: Ensure struct uses `float d` + `uint8_t qs[32]` (36 bytes total).

### Any backend: Binary not found
**Fix**: Build the missing target: `cmake --build build_<name> -j$(nproc) --target llama-server llama-cli`

### NPU: `/dev/accel/accel0` not found
**Fix**: Ensure kernel 6.17+ with `amdxdna` driver. Check: `lspci | grep -i "Neural Processing"`.
