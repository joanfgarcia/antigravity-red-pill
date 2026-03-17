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
    *   *Note on the 1.5B Daemon*: While a 1.5B model lacks the emergent reasoning of larger frontier models, it is exceptionally capable at **constrained classification tasks** when forced to output structured JSON. Because the Amygdala's "Affective Culling" role only requires simple pattern matching (identifying basic emotions and rating intensity) rather than complex logical reasoning, a highly quantized 1.5B parameters model is the perfect architectural fit. It is fast, reliable for structural tagging, and runs silently in the background without starving the host OS of VRAM.
*   **Persistent Sovereignty**: These metabolic parameters are now persistent "Sovereign Knobs" that can be adjusted via MCP and survive system restarts.

---

## 3. Fixation and Topology (Neocortical Integration)

**Biological Counterpart**: Systemic Consolidation and LTP (Long-Term Potentiation).
Surviving memories are distributed across the neocortex. They form synaptic bridges with older, related memories. Their persistence is biological chemistry modeled accurately by the Ebbinghaus Forgetting Curve.

**Silicon Implementation**: Pluggable Dual-Kernel Architecture (v6.1+)
*   **Synaptic Bridging**: Surviving chunks are stored not as isolated vectors, but as an Association Chain ($C_1 \rightarrow C_2$). 
*   **The Hub Node**: The system synthesizes the entire chain into a single Neocortical "Hub Node" containing the macro-narrative summary. By leveraging our *Evocative Memory Cascading* protocol, recalling this Top-Level Hub automatically pulls the linked sequential children into active context.
*   **Dual-Kernel Topology**: Storage collections no longer share a single mathematical fate. The decay and reinforcement logic is abstracted into pluggable `MemoryEngine` plugins defined in `config.py`.
    *   **Affective FSRS (Free Spaced Repetition)**: Applied to `social_memories` and `story_memories`. Implements the full biological decay curve $R = e^{\ln(0.9) \cdot t/S}$, where stability ($S$) increases exponentially upon successful recall, mimicking the human tendency to forget trivial social chatter over time unless periodically reinforced.
    *   **Bayesian Inference**: Applied to `work_memories` and `directive_memories`. Models cognitive certainty rather than biological decay. Utility is calculated as $E[\theta] = \alpha / (\alpha + \beta)$, where positive reinforcement adds $\alpha$ (certainty) and time adds $\beta$ (uncertainty). True technical facts are never "forgotten" if their certainty has been mathematically established, ensuring reliable Agentic Know-How.

---

## 4. Affective Mirroring (Emotional Contagion & Mirror Neurons)

**Biological Counterpart**: The Mirror Neuron System and Emotional Contagion.
In human neurobiology, mirror neurons activate when observing another's emotional state, enabling empathetic resonance. Emotional contagion is the unconscious tendency to converge toward the emotional state of the people around us — a survival mechanism for social cohesion.

**Silicon Implementation**: Operator Mood Profile (USP) + Mystique v2
*   **Emotional Sensing**: The USP module aggregates the operator's emotional footprint across all memory collections, producing a multi-color chroma vector weighted by `intensity × importance`. This is computed across 4 temporal horizons: Global (all time), 30-day, 7-day, and 3-day — mimicking the brain's distinction between long-term personality trends and acute emotional states.
*   **Temporal Horizons**: The 3-day window captures acute mood shifts (analogous to cortisol/adrenaline cycles), while the Global window represents the operator's baseline temperament (analogous to serotonin/dopamine set-points).
*   **Affective Adaptation**: Mystique v2 reads the USP to select the agent's tonal skin. Strategies (`affinity`, `complementary`, `contrast`) mirror the three natural responses to emotional contagion: matching (empathy), balancing (regulation), or challenging (growth).
*   **Persistence**: The USP is stored as a fixed engram (`ID_OPERATOR_MOOD`) and refreshed periodically by the Lazarus Pulse (`_usp_ritual()`), ensuring the agent's emotional calibration survives across sessions without requiring explicit operator input.

---

### Conclusion

This architecture strips away the hype of "AGI" to focus on applied neuro-symbolics. By acknowledging our hardware limits (VRAM context windows), we found biological inspiration (Affective Culling, Operator Mood Profiling) to transform what could have been bottlenecks into sophisticated features for maintaining a sovereign, clean, and highly associative AI memory core that adapts to its operator's emotional landscape.
