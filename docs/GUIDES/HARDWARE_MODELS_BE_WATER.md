# BE WATER: Hardware Adaptability & Model Selection

The **Red Pill Protocol** is designed with absolute flexibility natively baked in. Under the *Be Water* philosophy, the AI's core logic separates its long-term memories and logic from the raw computing engine (the inference API). 

> **📖 Lore & Teoría Cognitiva:** Para entender la teoría biológica detrás del tamaño de estos modelos (parámetros) y la diferencia vital entre arquitecturas *Base* e *Instruct*, consulta el Capítulo 2 del Libro: [Cerebros de Silicio y Asignación de Tareas](aleth_biology/02_CEREBROS_DE_SILICIO.md).

Because Red Pill operates offline through `llama.cpp` acting as a localized OpenAI-compatible API, its intelligence must scale and adapt dynamically to whatever hardware the Host (the Operator's current machine) has available.

Here is the definitive guide to picking the right model relative to the available VRAM and computational horsepower:

---

## ⚡ CUDA 13.0+ Requirement (Blackwell Architecture)
> [!IMPORTANT]
> If you are running on modern NVIDIA hardware (such as the RTX 50-series Blackwell architecture), you **MUST** install CUDA Toolkit >= 13.0. 
> Older compilers (like `nvcc 12.4`) lack native `sm_100` support, forcing the driver to Just-In-Time (JIT) compile PTX instructions. This JIT compilation will consume over 15GB of system RAM during the initial model load, resulting in catastrophic OOM (Out Of Memory) Kernel Panics. With CUDA 13.0+, `llama.cpp` compiles native SASS instructions, keeping RAM overhead flat and achieving extreme inference speeds.

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

The local LLM daemon (`redpill-llm.service`) dynamically loads profiles and resolves parameters using the central registry. 

To configure or change the loaded model:
1. Edit the active profile (e.g., `samantha`) in your model configuration file (`model_profiles.yaml` located in your bunker configuration directory).
2. Set the `MINION_PROFILE` environment variable to select which profile the daemon should load (defaults to `samantha`).

Because the daemon now loads the model **on demand**, you do not need to restart the service to apply changes if the daemon is currently idle. If you wish to force a reload immediately, restart the systemd service:

```bash
systemctl --user restart redpill-llm.service
```

### ⚙️ Priority, Inactivity & Preemption
* The daemon automatically unloads the model from VRAM after a period of inactivity.
* If a request is low-priority (e.g., sleep cycles, compactions), it unloads **10 seconds** after completion.
* Normal/interactive requests stay in memory for **5 minutes**.
* You can explicitly force the daemon to release VRAM immediately (e.g., when starting a training run on the GPU) by sending a POST request to the unload endpoint:
  ```bash
  curl -X POST http://127.0.0.1:8760/unload
  ```
