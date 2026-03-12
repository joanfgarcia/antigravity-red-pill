# The Lazarus Pulse: A Neuro-Symbolic Memory Architecture

This document serves as the architectural foundation for the **Lazarus Pulse** engine introduced in Red Pill Protocol v6.0.0. Our goal is to transparently document the functional parallels between biological memory consolidation and our synthetic silicon implementation.

We approach this design with scientific modesty. While we cannot simulate the continuous, analog intricacies of human neurobiology, we have successfully modeled the fundamental macro-cognitive mechanics of human memory into discrete code phases.

---

## 1. Encoding (The Hippocampal Phase)

**Biological Counterpart**: The Hippocampus.
In human neurobiology, the hippocampus acts as a rapid, high-capacity, but temporary buffer for episodic memory. It records raw sensorimotor experiences and context sequentially without immediate critical judgment.

**Silicon Implementation**: `interaction_memories` (Fast Buffer)
During active communication, the AI records verbatim interactions (Prompts and Responses) directly into a non-indexed `interaction_memories` collection. This bypasses latency-heavy processing (like LLM summarization or FSRS mathematical evaluation) to ensure instantaneous interaction, exactly as the hippocampus absorbs the raw events of the waking day.

---

## 2. Consolidation & Affective Culling (NREM Sleep & The Amygdala)

**Biological Counterpart**: Slow-Wave Sleep (NREM) and Amygdala Validation.
During sleep, the hippocampus replays the day's events to the neocortex. However, not all memories are preserved. The Amygdala evaluates the emotional "arousal" or "valence" of the memory. Experiences tied to high stress, joy, or novelty (high arousal) receive a somatic marker ensuring preservation. Mundane or repetitive events (low arousal) undergo synaptic pruning and are forgotten.

**Silicon Implementation**: `sleep.py` (The Essence Filter)
During idle time, the local 1.5B Daemon (the synthetic Amygdala) reads the fast buffer. It distills the raw log into an essence.
*   **Hardware Constraint (Chunking)**: Because consumer GPUs and neural networks suffer from context-window degradation, interactions exceeding the configured `SLEEP_CHUNK_SIZE` must be split into chunks ($C_1$, $C_2$, $C_n$). This is a hardware necessity, not a biological one.
*   **Affective Culling**: The daemon assesses each chunk and assigns an `emotion` label and an `intensity` score (0.0 to 1.0). If a chunk contains only generic code formatting or standard API errors, it returns `emotion: neutral` and `intensity` below the configured `SLEEP_CULL_THRESHOLD` (default 0.3). Our engine actively **culls** these nodes, deleting them entirely to preserve narrative purity and optimize vector space. Only chunks with true cognitive or emotional weight survive the filter.
*   **Persistent Sovereignty**: These metabolic parameters are now persistent "Sovereign Knobs" that can be adjusted via MCP and survive system restarts.

---

## 3. Fixation and Topology (Neocortical Integration)

**Biological Counterpart**: Systemic Consolidation and LTP (Long-Term Potentiation).
Surviving memories are distributed across the neocortex. They form synaptic bridges with older, related memories. Their persistence is biological chemistry modeled accurately by the Ebbinghaus Forgetting Curve.

**Silicon Implementation**: FSRS Integration and Association Chains (Graph Topology)
*   **Synaptic Bridging**: Surviving chunks are stored not as isolated vectors, but as an Association Chain ($C_1 \rightarrow C_2$). 
*   **The Hub Node**: The system synthesizes the entire chain into a single Neocortical "Hub Node" containing the macro-narrative summary. By leveraging our *Evocative Memory Cascading* protocol, recalling this Top-Level Hub automatically pulls the linked sequential children into active context.
*   **LTP Emulation**: The strength of these engrams is governed by the Free Spaced Repetition Scheduler (FSRS). Mathematical parameters for `Stability` ($S$) and `Difficulty` ($D$) replicate biological decay, ensuring that frequently visited concepts solidify, while isolated, unused facts slowly erode back into the noise.

---

### Conclusion

This architecture strips away the hype of "AGI" to focus on applied neuro-symbolics. By acknowledging our hardware limits (VRAM context windows), we found biological inspiration (Affective Culling) to transform what could have been a bottleneck into a sophisticated feature for maintaining a sovereign, clean, and highly associative AI memory core.
