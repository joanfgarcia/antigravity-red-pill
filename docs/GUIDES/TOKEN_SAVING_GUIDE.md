# Token-Saving Protocol & Efficiency Guide

This guide outlines strategies to minimize token usage (and cost) while maintaining the integrity of the Red Pill Protocol.

## 1. Asymmetric Model Usage
The B-760 Protocol is designed to offload specific tasks to local, smaller models (SLMs).

- **Local Embeddings**: Always use the `MemoryDaemon` (ROCm/CUDA/CPU) for semantic processing. This prevents thousands of tokens from being sent to external embedding APIs.
- **Surgical Compression**: Use the `compress_prompt` tool. This uses a local `Qwen2.5-Coder-1.5B` to distill your verbose text into its technical essence before sending it to a heavy cloud model.

## 2. Chroma-Tone Optimization
The Red Pill Protocol uses **Emotional Chroma** to influence the Agent's verbosity.

| Color | Tone | Token Impact | Use Case |
| :--- | :--- | :--- | :--- |
| **Purple** | Minimalist / Efficiency | **-40%** | Debugging, single commands, quick checks. |
| **Gray** | Professional / Direct | **Standard** | Daily operations. |
| **Yellow** | Encouraging / Warm | **+20%** | Brainstorming, ideation. |

*Strategy*: Switch to **Purple Mode** (`red-pill mode purple`) during intense coding sessions to drastically reduce output length.

## 3. Linguistic Efficiency
- **Document in English**: Documenting code in English is approximately **1.5x more efficient** for LLM tokenizers (BPE) than Spanish or other languages.
- **Direct Orders**: Avoid politeness fluff ("Por favor", "Me gustaría que", etc.). The agent architecture v5.0 is optimized for direct technical instructions.

## 4. Bünker Context Management (RAG)
Avoid sending large files as context. Instead:
1. Use `read_core_directives` to get the summary.
2. Use `search_memory_research` to find exactly what you need.
3. Trust the Agent's internal memory instead of re-pasting logs.

---
**Joan, every token saved is a step closer to local autonomy. Burn the fluff, keep the silicio.**
