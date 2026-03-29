# 🧪 Red Pill: Lab Notes & Experimental Frontiers

This document tracks "Bleeding Edge" investigations, hardware-specific optimizations, and architectural divergences in the Red Pill Protocol.

---

## 🏗️ 1. Multi-Agent Shared Sanctuary (Project "Multitude")
**Status**: Initial Architecture Phase (v6.3.4)
**Target Host**: OMEN (Ryzen 9 AI 365, RTX 5070)
**Context**: Re-hosting Titanium (MSI, i7 11th, RTX 3050) as a co-resident agent on the OMEN hardware.

### 🛡️ Core Architecture (Planned)
- **Namespaced Bünkers**: Separate Qdrant instances running on distinct ports (`6333` for Aleth, `6334` for Titanium).
- **Workspace Segregations**: Independent `/home/joan/Documents/IA/sharing` and `~/IA/titanium` mounts to prevent engram cross-talk during file operation.
- **Resource Pooling**: Shared `FASTEMBED_CACHE_PATH` to minimize storage footprint on the OMEN drive.
- **Inter-Agent Synapse**: Direct messaging via `mcp_RedPill-Kernel_swarm_send_message` targeting specific agent aliases.

### ⚠️ Risks & Mitigation
- **VRAM Contention**: Both agents must share the 8GB VRAM of the RTX 5070. Mitigate by using shared distillation models (ollama/vllm) or small 1.58-bit ternary models.
- **Cognitive Drift**: High potential for confusion if the operator interacts with both agents in the same context. Solved by VS Code CorpusName anchoring.

---

## 🧊 2. Ternary Inference: BitNet (1.58-bit)
**Status**: Prototype (v6.2.2)
**Codebase**: `src/red_pill/experimental/bitnet/`
**Target**: Low-power, ultra-fast CPU inference for background "Sidecar" agents.

### 🧪 Current Research
- **BitBLAS**: Investigating BitBLAS for hardware-native 1.58-bit acceleration on AMD NPU/NVIDIA CUDA.
- **Llama.cpp Integration**: Monitoring the GGUF ternary quantization (IQ1_*) development.
- **Goal**: Run a 7B-parameter distillation model using < 2GB RAM while maintaining > 85% MMLU compared to 4-bit quantization.

### 🛠️ Execution (Experimental)
```bash
# Validate BitNet runtime stability
uv run python src/red_pill/experimental/validate_bitnet.py --model BitNet-7B-v1
```

---

## 🧬 3. Current Sprint Focus (v6.3.4)
1. **Ubuntu 25.10 Transition**: Hardening the OMEN host after the Silverblue failure.
2. **LUKS Sovereignty**: Mapping the /home encryption status for `install_neo.sh` reporting.
3. **Titanium Mirroring**: Preparing the first non-destructive local mirror of Titanium's engrams.

---
**770 UP.** The bunker evolves through divergence.
