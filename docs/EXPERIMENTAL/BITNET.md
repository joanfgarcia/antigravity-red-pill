# 🧊 BitNet: Ternary Inference Research (1.58-bit)

**Project Internal ID**: B760-BITNET
**Status**: Prototype / Active Research (v6.3.4)

## 🎯 Objective
Achieve high-performance LLM inference on consumer-grade CPU/NPU hardware by leveraging 1.58-bit ternary quantization.

## 🧪 Current Vector
- **Hardware Integration**: Target AMD Ryzen AI (NPU) and RTX 5070 CUDA kernels for BitBLAS acceleration.
- **Quantization Theory**: Researching `IQ1_M` and `IQ1_S` GGUF formats from llama.cpp.
- **Goal**: Persistent background agents running on < 2GB RAM with near-zero idle impact.

## 🛠️ Testing Environment
```bash
# Verify ternary runtime
uv run python src/red_pill/experimental/validate_bitnet.py --model BitNet-7B-v1
```

## 📋 Road Map
- [ ] Benchmark BitNet-7B vs. Llama-3-8B-Q4.
- [ ] Implement BitBLAS kernel loading in `core/providers.py`.
- [ ] Measure NPU vs. GPU overhead on OMEN hardware.
