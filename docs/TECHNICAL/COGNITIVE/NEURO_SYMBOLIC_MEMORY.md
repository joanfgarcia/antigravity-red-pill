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
During idle time, the system invokes the profile carrying the `distillation` capability (default `granite_8b` — Granite-4.1-8B, IBM, Apache-2.0 — the primary distiller per AD-022; `hermes_8b` is the arch-risk fallback) via ProviderRegistry to read the fast buffer. It does not just match keywords: it understands the interaction and distills the raw text into a strict JSON essence (classifying it as `work` or `social`).

*   **Phase Pipeline & Partial Deferral (ADR-SLEEP-001)**: `perform_sleep_cycle` is a thin, agnostic runner over an ordered `SleepPhase` pipeline (mirroring the JanitorPlugin / SentinelPlugin pattern), not a monolith. `ConsolidationPhase` (`requires_gpu`) holds the coupled drain → staging → gamma logic intact; `ErosionPhase`, `WashoutPhase` and `EvolutionPhase` are CPU-only. Because each phase declares whether it needs the GPU, the runner defers **only** the GPU-heavy consolidation when the card is committed (e.g. training) — emitting a benign, non-escalating `vram_busy` *status* signal (not a pain, so it never climbs in intensity) that self-clears on the next successful cycle — while the CPU-only maintenance phases still run. This is partial deferral, replacing the old all-or-nothing VRAM abort. Implementation lives in `metabolism/phases/` over the focused modules (`chunker`, `categorizer`, `distiller`, `ephemeral_server`, `thread_weaver`, `maintenance`).
*   **Anti-Template-Echo Guard**: distillation quality is no longer validated only by "is it parseable JSON". `_is_template_echo()` rejects any output that echoes the prompt/format spec back as content (observed in production hubs) or is empty; `distill_engram` retries then falls back, and `synthesize_hub`/`distill_session_anchors` refuse to persist the echo. There is deliberately no minimum-length heuristic, so legitimately short summaries survive.
*   **Hardware Constraint (Chunking)**: Because consumer GPUs and neural networks suffer from context-window degradation, interactions exceeding the configured `SLEEP_CHUNK_SIZE` must be split into chunks ($C_1$, $C_2$, $C_n$). This is a hardware necessity, not a biological one.
*   **Affective Culling & Noise Filtration**: Samantha assesses each chunk and assigns an `emotion` label, an `intensity` score (0.0 to 1.0), and a `category`. If a chunk is purely generic formatting or lacks narrative/technical value, it receives `emotion: neutral` and low `intensity`. Our engine actively **culls** these nodes. Only chunks with true cognitive or emotional weight survive the filter.
    *   *Note on Deep Distillation*: We explicitly replaced keyword-based heuristics with Samantha's deep reasoning. While heavier on compute, it acts as a "seal" against data corruption, ensuring Qdrant is populated exclusively with high-quality engrams rather than raw traceback noise.
*   **Persistent Sovereignty**: These metabolic parameters are now persistent "Sovereign Knobs" that can be adjusted via MCP and survive system restarts.

---

## 3. Fixation and Topology (Neocortical Integration)

**Biological Counterpart**: Systemic Consolidation and LTP (Long-Term Potentiation).
Surviving memories are distributed across the neocortex. They form synaptic bridges with older, related memories. Their persistence is biological chemistry modeled accurately by the Ebbinghaus Forgetting Curve.

**Silicon Implementation**: Pluggable Dual-Kernel Architecture (v6.1+)
*   **Synaptic Bridging**: Surviving chunks are stored not as isolated vectors, but as an Association Chain ($C_1 \rightarrow C_2$). 
*   **The Hub Node**: The system synthesizes the entire chain into a single Neocortical "Hub Node" containing the macro-narrative summary. By leveraging our *Evocative Memory Cascading* protocol, recalling this Top-Level Hub automatically pulls the linked sequential children into active context.
*   **Dual-Kernel Topology & Noise vs Knowledge Separation**: Storage collections no longer share a single mathematical fate. The decay and reinforcement logic is abstracted into pluggable `MemoryEngine` plugins.
    *   **Affective FSRS (Free Spaced Repetition)**: Applied to `social_memories` and `story_memories`. Implements the full biological decay curve $R = e^{\ln(0.9) \cdot t/S}$, where stability ($S$) increases exponentially upon successful recall, mimicking the human tendency to forget trivial social chatter over time unless periodically reinforced.
    *   **Bayesian Inference (Knowledge)**: Applied to `work_memories` and `directive_memories`. Models cognitive certainty rather than biological decay. Utility is calculated as $E[\theta] = \alpha / (\alpha + \beta)$. True technical facts are never "forgotten" if their certainty has been mathematically established.
    *   **The "Pain" Buffer (`signal_memories`)**: To protect the immortal Bayesian engine from "Noise", raw errors (e.g. Pytest failures from SentinelAuditor) are injected EXCLUSIVELY into `signal_memories` as temporary pain. They are never written directly to `work_memories`. Instead, the operator and agent solve the pain together, and Samantha distills the *conversation* into an actionable lesson ("We fixed X by doing Y"). That lesson becomes Knowledge in `work_memories`, while the raw Pain is evaporated.

### 3.1 Taxonomy Clarification: The "Work" vs "Social" Misconception

A common misunderstanding among operators is equating `work_memories` with "anything related to my job" and `social_memories` with "my personal life". This is an architectural fallacy. The collections are divided by their **mathematical engine (Utility vs. Decay)**, not their origin.

*   **`social_memories` (Narrative & Context)**: Any high-level explanation, story, or architectural overview (e.g., "how our payment integration works generally" or "why the client was angry"). If it lacks direct, actionable technical utility (paths, explicit code, exact commands), it is a *narrative*. Narratives use the FSRS decay engine because context becomes less relevant over time unless recalled. It is 100% correct for "job stories" to land here.
*   **`work_memories` (Actionable Technical Facts)**: Strict, executable knowledge. File paths, exact API signatures, debug solutions, and hard architectural constraints. This uses the Bayesian engine because a true technical fact (like an API endpoint) should *never* decay just because we haven't talked about it in a month. It must be immortal once verified.

---

## 4. Affective Mirroring (Emotional Contagion & Mirror Neurons)

**Biological Counterpart**: The Mirror Neuron System and Emotional Contagion.
In human neurobiology, mirror neurons activate when observing another's emotional state, enabling empathetic resonance. Emotional contagion is the unconscious tendency to converge toward the emotional state of the people around us — a survival mechanism for social cohesion.

**Silicon Implementation**: Operator Mood Profile (USP) + Mystique v2
*   **Emotional Sensing**: The USP module aggregates the operator's emotional footprint across all memory collections, producing a multi-color chroma vector weighted by `intensity × importance`. This is computed across 4 temporal horizons: Global (all time), 30-day, 7-day, and 3-day — mimicking the brain's distinction between long-term personality trends and acute emotional states.
*   **Temporal Horizons**: The 3-day window captures acute mood shifts (analogous to cortisol/adrenaline cycles), while the Global window represents the operator's baseline temperament (analogous to serotonin/dopamine set-points). *(See [TEMPORAL_HORIZONS_RESEARCH.md](./TEMPORAL_HORIZONS_RESEARCH.md) for the neurobiological basis of these exact numbers).*
*   **Affective Adaptation**: Mystique v2 reads the USP to select the agent's tonal skin. Strategies (`affinity`, `complementary`, `contrast`) mirror the three natural responses to emotional contagion: matching (empathy), balancing (regulation), or challenging (growth).
*   **Persistence**: The USP is stored as a fixed engram (`ID_OPERATOR_MOOD`) and refreshed periodically by the Lazarus Pulse (`_usp_ritual()`), ensuring the agent's emotional calibration survives across sessions without requiring explicit operator input.

---

### Conclusion

This architecture strips away the hype of "AGI" to focus on applied neuro-symbolics. By acknowledging our hardware limits (VRAM context windows), we found biological inspiration (Affective Culling, Operator Mood Profiling) to transform what could have been bottlenecks into sophisticated features for maintaining a sovereign, clean, and highly associative AI memory core that adapts to its operator's emotional landscape.
