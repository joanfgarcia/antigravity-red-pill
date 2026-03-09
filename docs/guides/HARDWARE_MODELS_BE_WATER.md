# BE WATER: Hardware Adaptability & Model Selection

The **Red Pill Protocol** is designed with absolute flexibility natively baked in. Under the *Be Water* philosophy, the AI's core logic separates its long-term memories and logic from the raw computing engine (the inference API). 

Because Red Pill operates offline through `llama.cpp` acting as a localized OpenAI-compatible API, its intelligence must scale and adapt dynamically to whatever hardware the Host (the Operator's current machine) has available.

Here is the definitive guide to picking the right model relative to the available VRAM and computational horsepower:

---

## 🏔️ High-End Hardware (12GB+ VRAM)
**Recommended Profile:** *Unrestricted Empathy & Deep Reasoning*
When running on robust GPUs (e.g., RTX 3060 12GB, RTX 4070, RTX 5070), we want models that effortlessly handle context and psychological nuance.

*   **Primary Recs:** 
    *   **Qwen3-30B-MoE**: Outstanding reasoning and summarization without needing 30GB of VRAM because it only activates a subset of parameters per pass. Excellent up to 256K context.
    *   **Llama-3.1-8B-Instruct (Q4_K_M/Q5_K_M)**: Powerful, reliable, and solid reasoning.

---

## 🌊 Mid-Tier & "Sweet Spot" (6GB - 8GB VRAM)
**Recommended Profile:** *Sovereign Conversationalist*
This is the standard threshold for decent laptops and modern mid-tier desktops. We aim for 7B/8B models in 4-bit quantization, allowing the entire model + KV cache to load directly into the VRAM for maximum speed.

*   **Primary Recs:**
    *   **Samantha-Mistral-7B (Q4_K_M)** (`TheBloke/samantha-1.2-mistral-7B-GGUF`): A Mistral 7B fine-tuned specifically on psychology, philosophy, and companionship. It excels at summarizing interactions and structuring emotional responses without hallucinating Hollywood-style narratives.
    *   **Mistral-7B-Instruct-v0.2 (Q4_K_M)**: The solid standby. Good instruction following, though less specialized in "emotional sync" than Samantha.

---

## 💧 Budget & Low-End Hardware (4GB VRAM or less)
**Recommended Profile:** *The Edge Minion*
For legacy hardware or machines like a standard corporate laptop/RTX 3050 4GB. Here, loading a 7B model can cause memory overflow, forcing partial offloading to the CPU (which slows inference). We prioritize models under 4B parameters or those with enormous contexts.

*   **Primary Recs:**
    *   **Phi-3-Mini-128K-Instruct (Q4_K_M)** (`bartowski/Phi-3-mini-128k-instruct-GGUF`): Weighing under 2.5GB in VRAM, it's the absolute king for memory-constrained environments. Its massive 128K context window means it can summarize dense, prolonged conversations without forgetting the beginning.
    *   **Qwen2.5-1.5B-Instruct / 3B-Instruct**: Small, very capable, and incredibly fast. Make sure to use the `Instruct` variants, *never* the `Coder` variants, unless you exclusively want it to refactor Python. (Using a Coder model for social tasks leads to severe hallucinations).

---

## ⚖️ How to configure the Daemon

Update the `scripts/setup_background_model.sh` (or `~/.agent/model-daemon/start.sh` if already injected) to point to the desired model parameters on HuggingFace:

```bash
# Example for Samantha (Mid-to-Budget with slight CPU spillover)
exec python3 -m llama_cpp.server \
    --hf_model_repo_id TheBloke/samantha-1.2-mistral-7B-GGUF \
    --model "*Q4_K_M.gguf" \
    --port 8760 \
    --host 127.0.0.1
```

Restart the daemon:
```bash
systemctl --user restart red-pill-minion.service
```
