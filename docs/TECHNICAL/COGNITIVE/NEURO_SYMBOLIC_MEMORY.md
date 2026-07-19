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

*   **Phase Pipeline & Partial Deferral (ADR-SLEEP-001, extended in v7.7.0)**: `perform_sleep_cycle` is a thin, agnostic runner over an ordered `SleepPhase` pipeline (mirroring the JanitorPlugin / SentinelPlugin pattern), not a monolith. The v7.7.0 pipeline runs **eight ordered phases**:
    1. **Consolidation** (`requires_gpu`) — the coupled drain → staging → gamma logic, intact per ADR-SLEEP-001. Lone surviving chunks are promoted to `synthesis_hub` inline so every turn keeps a searchable representative.
    2. **OrphanPromotion** — idempotent safety net: any hub-less consolidated turn (from legacy data or a future synthesis failure) gets its newest chunk flipped to `synthesis_hub` (AD-023 §4).
    3. **Hygiene** — purges empty/whitespace engrams (zero recall value), re-stitching the `prev/next_raw_parent` temporal chain around each victim first; inherited-immunity fragment shrapnel is purged, deliberate immune empties and **murky pointers** (see §3.3) are only reported.
    4. **AxonWeaver** — weaves cross-collection synaptic axons (see §3.2). CPU-only; runs after Hygiene so it never weaves what is about to vanish.
    5. **Erosion** — Bayesian hub erosion (deletion threshold = the engine's own, single source of truth; see AD-023).
    6. **Washout** — RhizoDB washout/pruning for rhizome collections.
    7. **Revision** (`requires_gpu`, born dark) — batch re-classification of legacy engrams (Track R2): dry-run marks `revision_would_move_to`; execute moves leaf engrams preserving their ID and rewiring reciprocal axons. Hubs are flagged, never moved.
    8. **Evolution** — self-evolution bookkeeping.
    Because each phase declares whether it needs the GPU, the runner defers **only** the GPU-heavy phases when the card is committed (e.g. training) — emitting a benign, non-escalating `vram_busy` *status* signal that self-clears on the next successful cycle — while the CPU-only maintenance phases still run. Implementation lives in `metabolism/phases/` over the focused modules (`chunker`, `categorizer`, `distiller`, `ephemeral_server`, `thread_weaver`, `maintenance`, `axons`, `revision`).
*   **Anti-Template-Echo Guard**: distillation quality is no longer validated only by "is it parseable JSON". `_is_template_echo()` rejects any output that echoes the prompt/format spec back as content (observed in production hubs) or is empty; `distill_engram` retries then falls back, and `synthesize_hub`/`distill_session_anchors` refuse to persist the echo. There is deliberately no minimum-length heuristic, so legitimately short summaries survive.
*   **Hardware Constraint (Chunking)**: Because consumer GPUs and neural networks suffer from context-window degradation, interactions exceeding the configured `SLEEP_CHUNK_SIZE` must be split into chunks ($C_1$, $C_2$, $C_n$). This is a hardware necessity, not a biological one.
*   **Affective Culling & Noise Filtration**: Samantha assesses each chunk and assigns an `emotion` label, an `intensity` score (0.0 to 1.0), and a `category`. If a chunk is purely generic formatting or lacks narrative/technical value, it receives `emotion: neutral` and low `intensity`. Our engine actively **culls** these nodes. Only chunks with true cognitive or emotional weight survive the filter.
    *   *Note on Deep Distillation*: We explicitly replaced keyword-based heuristics with Samantha's deep reasoning. While heavier on compute, it acts as a "seal" against data corruption, ensuring Qdrant is populated exclusively with high-quality engrams rather than raw traceback noise.
*   **Texture Preservation — the Qualia of Engrams (v7.7.0, Eje 1)**: distillation no longer flattens the *how* into the *what*. The `COGNITIVE_DISTILLER_V3` contract is key-ordered (`summary → emotion → intensity → category → texture → relics → lang`) because committing to the factual metadata BEFORE writing the texture anchors it against hallucination (workshop-validated). Every fragment distills with: a `texture` (atmosphere, friction, tiredness, humor — written in the source language, gated below `MIN_TEXTURE_CHARS`), `relics` (verbatim quotes validated as literal substrings in code — typos preserved — and transported mechanically between generations, never re-distilled: LLMs paraphrase quotes within two generations), and `lang`. Hubs (`NEOCORTEX_SYNTHESIS_V2`) synthesize summary AND merged texture in the dominant fragment language, derive their affect from the full fragment history (intensity-weighted dominant emotion, not the accidental last-chunk rule) and persist the per-fragment `emotional_vector` `{child_id, emotion, intensity, category}` — the operator's deliberate historical record of how each atom felt.
*   **Chronicle Ingestion Hygiene (v7.7.0)**: session-transcript ingestion collapses tool payloads to self-evocative markers (`[TOOL: Edit file_path=...]`, result heads where verdicts live) instead of embedding megabytes of machine noise as immune verbatims (`CHRONICLE_STRIP_TOOL_PAYLOADS`).
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

### 3.2 Cross-Collection Synaptic Axons (Intuition Bridges — ADR-AXON-001, v7.7.0)

**Biological Counterpart**: the human tendency to bind a technical insight to the everyday moment it was born in — ideas surface on a walk and land in a data structure.

The physical separation of collections (needed for the dual decay engines) built a cognitive wall: searching `work_memories` could never evoke the relaxed conversation where a design decision was actually forged. **Synaptic axons** are typed, weighted, bidirectional links stored inside the existing `associations` payload (`{id, target_collection, weight, association_type}` — legacy plain-id links coexist via a retrocompatible reader):

*   **Weaving (sleep-time, CPU-only)**: the `AxonWeaver` sweeps a 48h window pairing engrams across collections within ±6h. Weight $W = \alpha \cdot \text{sim} + (1-\alpha)(1 - \Delta t/\Delta t_{max})$ with $\alpha = 0.7$; connect when $W \ge$ `AXON_GATE` (0.5 — live-calibrated: real cross-domain similarities on multilingual-384d run 0.28-0.35, so true same-session pairs weigh ≈0.50-0.53 while noise stays ≤0.41). Writes are idempotent and self-healing (a one-way link from a mid-write failure completes next cycle); dangling links are GC'd; a deferred soft cap (`AXON_MAX_CROSS`) prunes by weight with full-cycle information.
*   **Traversal (query-time, behind `AXON_READ_ENABLED`)**: the evocative cascade follows the top-2 axons by weight per direct hit into the other collection, checks the target is still active under its own engine, injects it tagged `_axon_weight`, and applies **reinforcement-on-traversal** ($W \cdot \beta$, a synthetic review routed through the destination engine). Reinforcement lives at traversal — never inside the erosion formula — because bidirectional links reinforced at erosion-time self-amplify without any real use.
*   **Shadow rollout**: the weaver ships ON but the read path ships dark; it unlocks after ≥4 *effective* weaver runs (persisted counter — runs with zero candidates don't count) and a telemetry review (`AxonWeaveEvent` carries accepted/rejected weight averages precisely so `AXON_GATE` is tuned from data).
*   **Texture shadows (T5, dark)**: each hub's texture can persist as a `texture_shadow` point (same collection, own embedding, excluded from factual search) enabling **evocation by resonance** — `search_space="texture"` answers "how did it feel" and resolves to the parent engram. A Spanish resonance query resolved an English-textured engram at 0.70 in the live test.

### 3.3 Recall Calibration & Self-Evocation (AD-023, v7.7.0)

*   **Born-dead calibration (fixed)**: the Bayesian deletion threshold must sit **strictly below the uniform-prior mean** E[Beta(1,1)] = 0.5, or every engram without reinforcement history is judged dead at birth (this silently starved 99% of `work_memories` for months). It is 0.2 (~19 recall-free days of grace) and the single source of truth for both the read path and sleep-side hub erosion.
*   **Reads never hide**: eroded hits return flagged `_eroded=True`, demoted in ranking and *reinforced* — organic rehabilitation. Hiding them starved the rescue loop by design (death spiral). Forgetting belongs to the sleep cycle, never to a lookup.
*   **Self-Evocation Principle (the Operator's book test)**: a memory must let you intuit what it pointed to even when the referenced artifact is gone — remembering you read a book without the book is a *good* memory if the engram keeps title and cover; a pointer with no semantic residue is a **murky memory** (*recuerdo turbio*). Ingestion markers are therefore self-evocative (tool + target + result head), and the HygienePhase audits murky pointers every cycle — **report-only**: the policy for existing murky memories (purge / enrich / "turbio" flag as erosion accelerator with loss of immunity) is an open operator decision (AD-024, PROPOSED).

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
