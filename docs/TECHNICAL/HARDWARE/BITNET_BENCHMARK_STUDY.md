# BitNet 1.58b Intelligence Benchmark: Technical Study & Post-Mortem

**Date:** 2026-03-31 (Original) | **Updated:** 2026-05-22
**Environment:** Sovereign Pod / MSI Titanium (Remote) -> NVIDIA RTX 5070 Laptop GPU (8GB VRAM) / Ryzen AI (50 TOPS)
**Framework:** `bitnet.cpp` (LLaMA.cpp fork optimized for Ternary Weights `i2_s`)

## 1. Executive Summary
This technical documentation summarizes the isolation, compilation, and evaluation of 1.58-bit ternary Large Language Models (LLMs) executing natively on a local workstation. The core objective was to validate intelligence capabilities (Zero-Shot reasoning, Structured JSON extraction, and Code Generation) to select the optimal cognition engine for the `red-pill` multi-agent architecture without polluting the core database.

## 2. Infrastructure & Compilation Pipeline
The models were processed and executed within an explicitly isolated minion script (`minion_benchmark.py`) under `sharing/experimental/BitNet/`.

### 2.1 BitNet Architecture & Kernel Types (I2_S, TL1, TL2)
The 1.58-bit BitNet architecture achieves its revolutionary efficiency by replacing complex floating-point matrix multiplications (FP16) with simple additions and subtractions. This is possible because the model weights are strictly constrained to ternary values: **-1, 0, and 1**. 

To exploit this at the hardware level, the execution engine relies on three specialized kernel types:
- **I2_S (Inference 2-bit Standard):** The foundational kernel. It packs the ternary weights (-1, 0, 1) into 2-bit structures. This is the most compatible kernel and the baseline we use for reliable GGUF manipulation and GPU offloading (e.g., via CUDA on the RTX 5070).
- **TL1 (Ternary Lookup 1):** Replaces mathematical operations with Lookup Tables (LUTs). Since the outcomes of adding/subtracting ternary weights are highly predictable, TL1 pre-calculates the results and simply "looks them up" in memory, drastically accelerating inference.
- **TL2 (Ternary Lookup 2):** An advanced evolution of TL1 that processes multiple weights against multiple activations simultaneously in vectorized blocks. TL2 is specifically optimized for AVX instructions on CPUs and Tensor Cores on GPUs/NPUs, capable of achieving unprecedented throughput.

### 2.2 Weight Conversion (`setup_env.py`)
HuggingFace `safetensors` were locally transpiled and quantized into the `i2_s` GGUF schema:
- **Baseline:** `microsoft/BitNet-b1.58-2B-4T`
- **Candidate A:** `HF1BitLLM/Llama3-8B-1.58-100B-tokens` (Base)
- **Candidate B:** `tiiuae/Falcon3-10B-Instruct-1.58bit` (Instruct-Tuned) ← **CERTIFIED**

*Conversion Overhead:* The 8B/10B models peaked at ~16GB RAM during `fp16` translation before folding into `i2_s` (occupying ~3.8GB on disk, allowing complete offload into the RTX 5070's 8GB VRAM envelope).

### 2.3 Execution Engine (`llama-cli`)
Inference was orchestrated using the `bitnet.cpp` static binary.

**Verified Parameters (2026-05-22):**

| Parameter | CUDA (Recommended) | CPU (Fallback) |
| :--- | :--- | :--- |
| Context (`-c`) | `16384` (max for 8GB VRAM) | `2048` |
| GPU Layers (`-ngl`) | `99` (full offload) | `0` |
| Threads (`-t`) | `10` | `10` |
| Temperature | `0.0` - `0.2` | `0.0` - `0.2` |
| Max Tokens (`-n`) | `256` | `256` |
| Build Path | `build_cuda/bin/llama-cli` | `build_cpu/bin/llama-cli` |

**VRAM Budget (RTX 5070 Laptop, 8GB):**
- Model weights (`I2_S`): ~3.3 GiB
- KV Cache @ ctx 16384: ~1.3 GiB
- Compute buffers: ~0.3 GiB
- **Total:** ~4.9 GiB (Safe margin: ~3 GiB free)
- **⚠ ctx 32768 FAILS** (KV cache alone demands 5.1 GiB → OOM)

### 2.4 Performance Benchmarks (2026-05-22)

| Backend | Context | Prompt Eval (tok/s) | Eval (tok/s) | Status |
| :--- | :--- | :--- | :--- | :---: |
| CUDA (-ngl 99) | 2048 | 45.2 | 23.5 | ✅ |
| CUDA (-ngl 99) | 4096 | - | 24.9 | ✅ |
| CUDA (-ngl 99) | 8192 | - | 23.2 | ✅ |
| CUDA (-ngl 99) | 16384 | - | 24.7 | ✅ |
| CUDA (-ngl 99) | 32768 | - | - | ❌ OOM |
| CPU | 2048 | 22.4 | 2.9 | ✅ |

**Key Insight:** CUDA delivers ~8x speedup over CPU. Context 16384 is the practical ceiling for 8GB VRAM.

## 3. The Evaluation Matrix (Disciplines)
The Minion subjected each model to three single-turn (Zero-Shot) deterministic prompts:
1. **Razonamiento Lógico:** *Chain-of-thought* math puzzle regarding apples. Expected behavioral output: Numerical resolution "1".
2. **Extracción Estructurada JSON:** Natural language to JSON parsing. Expected behavioral output: Strict `{"name": "...", "age": ...}` schema without markdown dialogue.
3. **Generación Python:** Implementation of `reverse_string`. Expected behavioral output: A pure function block.

## 4. Empirical Benchmark Results

| Model | Architecture Type | Logic Math | JSON Extraction | Python Generation | TCO (RAM Delta / Inference Speed) | Final Score |
| :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| **BitNet-2B-4T** | Base (Pre-Trained) | 0/100 | 0/100 | 60/100 | ~118 MB / Fast | **20/100** (Fail) |
| **Llama3-8B-1.58** | Base (Pre-Trained) | 0/100 | 0/100 | 70/100 | ~300 MB / Med | **23/100** (Fail) |
| **Falcon3-10B** | Instruct (Post-Trained) | 95/100 | 100/100 | 100/100 | ~264 MB / Med | **98/100** (Pass) |

### 4.1 Observations on "Base" vs "Instruct" Topologies
The empirical failure of LLaMA3-8B and 2B-4T is strictly architectural. Base models operate as probabilistic next-token predictors. Without *Instruction Tuning*, they fail to recognize the boundary between the semantic prompt and their response, leading to severe zero-shot hallucinations (e.g., LLaMA-3 generating news about "a new president", 2B-4T generating a recipe).

In contrast, **Falcon3-10B-Instruct** contains the necessary alignment tokens to halt generation cleanly (`<|endoftext|>`) and adhere to strict schemas, achieving perfect JSON extraction.

### 4.2 Quality Verification (2026-05-22)
Extended verification tests confirmed coherent generation across multiple domains:
- **Factual QA:** "What is the capital of France?" → "Paris" ✅
- **Multi-sentence Explanation:** Quantum computing → coherent 3-sentence explanation ✅
- **Code Generation:** Fibonacci function → correct, efficient Python code ✅
- **Chat Template Support:** `<|system|>`, `<|user|>`, `<|assistant|>` delimiters work correctly ✅

## 5. Architectural Conclusion
**Falcon3-10B-Instruct-1.58bit** is formally certified for ingestion into the `red-pill` production standard. Its zero-shot cognitive fidelity perfectly matches our operational requirements (Sovereignty, Speed, and Structured Output), comfortably residing within the 8GB VRAM hardware constraint while freeing up system RAM entirely.

### 5.1 Certified Deployment Configuration
```yaml
model:
  name: Falcon3-10B-Instruct-1.58bit
  source: tiiuae/Falcon3-10B-Instruct-1.58bit
  architecture: LlamaForCausalLM
  quantization: I2_S (1.58-bit ternary)
  disk_size: 3.99 GiB
  gguf_path: 3rdparty/BitNet-1.58b/models/Falcon3-10B-Instruct-1.58bit/ggml-model-i2_s.gguf

inference:
  cuda:
    runner: build_cuda/bin/llama-cli
    ngl: 99
    ctx_max: 16384
    ctx_default: 4096
    eval_speed: ~24 tok/s
  cpu:
    runner: build_cpu/bin/llama-cli
    ngl: 0
    ctx_max: 2048
    ctx_default: 2048
    eval_speed: ~3 tok/s

chat_template:
  system: "<|system|>\n{system_message}"
  user: "<|user|>\n{user_message}"
  assistant: "<|assistant|>"
  eos_token: "<|endoftext|>"
```

### 5.2 Disk Cleanup (2026-05-22)
Obsolete artifacts purged (~47 GB freed):
- `ggml-model-f16.gguf` (20 GB) — intermediate conversion artifact
- `gpu/checkpoints/bitnet-b1.58-2B-4T-bf16/` (4.6 GB) — failed candidate (20/100)
- `gpu/checkpoints/llama3-8b-1.58*/` (11.2 GB) — failed candidate (23/100)
- `gpu/checkpoints/model_state_*.pt` (11.5 GB) — PyTorch intermediates
