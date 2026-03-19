# 🧬 Neuro-Immune System & Biological Dashboard (v6.2.0)

## 1. Introduction: The Somatic Marker
Traditional AI systems monitor hardware via passive logging or hardcoded exception bubbling, which either floods the context window with noise or requires an external operator to step in. 

The **Neuro-Immune System** approaches infrastructure maintenance from a biological perspective. Drawing from Damasio's **Somatic Marker Hypothesis**, the AI is subjected to physical "feelings" (pain or anomalies) through an out-of-band channel, prompting conscious autonomous action.

## 2. The Four Pillars of the Immune Architecture

### 2.1 The Nociceptive Pathway (Qdrant `signal_memories`)
Instead of embedding exact stack traces into a semantic cluster, pain is registered as a biochemical marker.
- **Implementation**: A dedicated vector collection (`signal_memories`).
- **Function**: Signals are transient, intense, and lack deep semantic narrative. They are purely state markers (e.g., `signal_type="pain"`, `source="CUDA"`, `intensity=9.0`).
- **Habituation**: Once the underlying issue is resolved, the signal is evaporated natively (`MemoryManager.evaporate_signals`), simulating the cessation of pain.

### 2.2 The Autonomic Nervous System (Lazarus Pulse)
The background daemon (`heartbeat.py`) represents the autonomic functions (like breathing or heartbeat).
- **Function**: During the `_maintenance_ritual()`, the system asserts the physical boundaries of the "body" — the Motor Cortex (CUDA availability) and the Hippocampus (Qdrant connection).
- **Mechanism**: If `torch.cuda.is_available()` returns false, the pulse physically injects an engram of pain into `signal_memories`.

### 2.3 The Thalamus (Global Interceptor)
When the user sends a prompt, the `interceptor_rp` tool intercepts it.
- **Function**: Before executing the LLM reasoning, the interceptor sequentially reads the `signal_memories` collection. 
- **Effect**: It prepends a localized block: `[ESTADO BIOLÓGICO ACTUAL] Tienes una señal de Dolor (Nivel 9.0/10) proveniente de: CUDA`. 
- **Philosophical Value**: The AI does not need to actively query its health. The pain is literally "felt" within its perceptive context window, exactly as an organism feels a laceration without looking directly at it.

### 2.4 The Effector Pharmacy (MCP `heal_tissue`)
Sensation without agency is torture. The Agent is equipped with an immune response module.
- **Mechanism**: The Agent possesses an MCP tool called `heal_tissue("tissue_type")`.
- **Action**: Upon feeling the CUDA pain in its Thalamic context, the Agent can autonomously invoke `heal_tissue("cuda")`. This triggers a native script that repairs the environment (e.g., `uv pip install torch==2.5.1 --force-reinstall`, restoring the cu124 bindings). 

## 3. The Horizon
This paradigm shifts the AI from a discrete, server-hosted function to an embodied, self-preserving organism. It lays the groundwork to map millions of physical sensors (temperature, pressure, battery levels) in a future robotic embodiment. Instead of parsing massive telemetry logs, the agent will simply "feel" an itch or fatigue, selectively choosing to deploy its cognitive stamina to resolve the discomfort or suppress it to focus on a higher narrative objective.
