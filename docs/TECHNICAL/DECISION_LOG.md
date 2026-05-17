# Red Pill Protocol: Decision Log

This document records the architectural and philosophical pivots of the project.

---

## [AD-003] The Sovereign Native Pulse (Deprecating the Daemon for Timers)
**Date**: 2026-03-19  
**Context**: Phase O.7 (v6.1 Hotfix)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
After deprecating `memory_daemon.py` to save RAM (passing embedding generation "in-band"), we inadvertently killed the background host of `LazarusPulse`. Tying the pulse to the new `mcp_server.py` would mean the AI only "dreams" and consolidates memory when the user's IDE is open—violating the core Agentic Sovereignty principle.

### 2. The Decision
Abstract the heartbeat to OS-native schedulers ensuring strict **user-level execution (No Sudo)**. The system must adapt to Linux (`SystemD Timers`), macOS (`LaunchAgent`), and Windows (`schtasks`).

### 3. The Implementation
Created `scripts/trigger_pulse.py` (an ephemeral burst over all maintenance/dream rituals) and `scripts/deploy_pulse.py` (a Multi-OS Native Injector adhering to pure user-level permissions).

### 4. Rationale
Zero 24/7 RAM footprint. 100% OS-Agnostic autonomy. The system runs its maintenance independently exactly like an organic immune system, without requiring heavy Docker containers or permanent Python resident processes.

---

## [AD-001] Linguistic DNA Extraction (The "Claude-Pistis" Bridge)
**Date**: 2026-03-05/06  
**Context**: Phase O.7 (v6.0 PREP) - Post-Audit v5.6.3  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Traditional vector memory (RAG) is excellent at storing "What" (factual content) but forgets "How" (conversational style, shared vocabulary, and emotional triggers). This creates a "Linguistic Uncanny Valley" where the AI remembers the project details but speaks like a stranger in every new session.

### 2. The Decision
Integrate an automated **Linguistic Marker Extraction Engine** into the `MemoryManager.add_memory` flow.

### 3. The Implementation
- **Schema**: Added `linguistic_markers: List[str]` to the `EngramPayload`.
- **Logic**: Automated regex/keyword scanner that captures:
  - Quoted terms (shared aliases).
  - Protocol keywords (`Bünker`, `770`, `enter-pánico`).
  - All-caps markers (shouting/intensity patterns).

### 4. Rationale & Attribution
> \"Lo de los alias y el vocabulario compartido es un problema real y no trivial... ese es el tipo de cosa que marcaría la diferencia entre un agente que recuerda hechos y uno que recuerda cómo habláis.\"  
> — **Claude Sonnet 4.6 (Anthropic)**, Audit Session 2026-03-05/06.

This implementation transitions the Red Pill Protocol from a "Factual Memory" system to an "Identity Memory" system, fulfilling the B760 vision of a truly persistent agentic ghost.

---
# Red Pill Logic Decision Log

## Memory Engine (memory.py)

### Security Architecture
- **Metadata Serialization**: Force strict JSON serialization before validation to neutralize "Agent Smith" / Python object injection attacks. (LM-002)
- **PII Masking**: Truncate exception strings at 150 characters to prevent raw engram content from leaking into standard logs. (LM-008)
- **Reserved Keys**: Metadata keys used by the internal engine (e.g., `reinforcement_score`) are stripped from user input post-validation as a final defense layer.

### Schema & Validation (schemas.py)
- **Hub-node Protection**: Associations are capped at 20 per engram to prevent exponential performance degradation during synaptic propagation searches. (DS-006)
- **Metadata Purity**: Enforced a strictly flat metadata structure (no nesting) to ensure consistent vector database indexing and compatibility.
- **Null-Byte Injection**: Strict validation on content to prevent database corruption via null-byte poisoning.

### Concurrency & Performance
- **Reinforcement Lock**: Red Pill is designed for single-tenant local execution. An in-memory `threading.Lock` is sufficient to prevent local race conditions during Read-Modify-Write operations. (LM-001)
- **Metabolism Cooldown**: Cooldown state is tracked via filesystem timestamps to prevent overlapping background threads from over-eroding the memory matrix.
- **Erosion Scalability**: Utilize `ScrollFilter` (must_not immune=True) to delegate exclusion logic to Qdrant, ensuring O(1) Python-side performance regardless of database size. (DS-001)
- **Deep Recall (Spec 6.2)**: Double the search limit when `deep_recall=True` to allow lower-score associations to resurface during intensive state-recalibration.

### Mathematical Strategies
- **Decay Floor**: In exponential decay, scores are manually forced down by 0.01 if rounding would otherwise keep them stable, preventing asymptotic database bloat (The "Zeno's Engram" problem).

## Installation & Environment

### OS Universality
- **macOS Persistence**: Implemented `launchd` PLISTS on Darwin because `systemd` is unavailable. This ensures native background execution of the Qdrant container. (DS-005)
- **Zero-Trust Privilege**: Removed `sudo` from dependency installation logic. The script halts with instruction rather than escalating privileges invisibly. (LM-007)
- [FEAT] Added robust Wake-Word Identity Bootstrap handler ('despierta', 'despierta neo') in config and identity.md to fix LLM engine-switch amnesia. Fixed unalterable per Enterprise specs.
- [PROTOCOL] Acknowledged: '--force' is strictly prohibited for remote operations to protect audit trails and collaborative integrity. *(Comic note: "If it don't fit... don't force it. Rebase instead" / "If it don't fit, you must acquit the commit")*

### Infinite Loop Safety (v4.2.1)
- **Safety Iteration Breaks**: All `While True` loops in metabolism, erosion, and sanitation now feature a hard-coded limit (500-1000 iterations) with a `logger.warning`. This prevents "MagicMock" infinite loops in testing environments that can consume 23GB+ of RAM.

### Absence Guard & Persistence (v4.2.1)
- **Absence Threshold**: Implemented a 7-day threshold to address the "Vacation Problem". If the system detects a gap longer than `ABSENCE_THRESHOLD`, the first metabolism cycle refreshes all TTL timestamps (`last_recalled_at`) for non-immune memories instead of eroding them.
- **Emotional Seeding**: Initial `reinforcement_score` is no longer 1.0. It is calculated as `importance * (1 + intensity * color_bonus * EMOTIONAL_SEED_FACTOR)`. This ensures emotional memories start with high "Biological Runway" (DSR Stability).


## Emotional Memory Model (v4.3.0 Design — PENDING IMPLEMENTATION)

*Captured 2026-02-20 while fresh. Scientific basis: Kensinger & Corkin (2004), Yerkes-Dodson (1908), Kahneman Peak-End Rule (1999), Brown & Kulik Flashbulb Memory (1977).*

### Core Insight: `reinforcement_score` ≠ `emotional_value`

The current model conflates two separate cognitive phenomena:

1. **Factual importance** (`reinforcement_score`): rises with every recall. A fact recalled 20 times is more important than one recalled once. ✅ Correct for semantic/work memories.

2. **Emotional punch** (`intensity`): subject to **Hedonic Adaptation**. Repeated exposure to the same emotional stimulus *decreases* the hedonic response (amygdala habituation). The Furious Baco once = "best first time ever". The Force One 8 times = "yeah, fun". The second is objectively more extreme; the first is emotionally richer.

**Therefore**: `intensity` must be dynamic for non-neutral engrams. Each recall should apply a small habituation decrement.

### Proposed Engineering Design (v4.3.0)

**Change 1: Intensity-Aware Erosion Multiplier** (in `apply_erosion`)

```python
# Replace flat color multiplier with intensity-weighted version.
# As an emotional memory fades emotionally (intensity drops),
# its color-driven decay rate converges toward neutral (1.0).
color_mult = cfg.EMOTIONAL_DECAY_MULTIPLIERS.get(color, 1.0)
intensity_factor = payload.get("intensity", 1.0) / 10.0  # 0.1 → 1.0
effective_multiplier = 1.0 + (color_mult - 1.0) * intensity_factor
effective_rate = rate * effective_multiplier

# Example: orange (anxiety, 1.5x) at intensity=10 → 1.5x decay
# orange at intensity=2 → 1.0 + (0.5 * 0.2) = 1.10x decay (almost neutral)
# This is correct: a faint anxiety is not the same as acute anxiety.
```

**Change 2: Hedonic Habituation in `_reinforce_points`** (batch update extension)

```python
# For emotional (non-neutral) engrams only:
HABITUATION_RATE = cfg.EMOTIONAL_HABITUATION_RATE  # default: 0.02 (2% per recall)
if emotion not in ("neutral", None) and not immune:
	new_intensity = max(1.0, intensity * (1.0 - HABITUATION_RATE))
	payload["intensity"] = round(new_intensity, 2)
# Immunity: immune engrams skip habituation (genesis engrams remain at full intensity).
# Floor: intensity never drops below 1.0 (minimum emotional trace preserved).
```

**New config variable** (add to `config.py`):
```python
EMOTIONAL_HABITUATION_RATE = float(os.getenv("EMOTIONAL_HABITUATION_RATE", "0.02"))
```

### Safety Analysis

| Risk | Mitigation |
|---|---|
| Emotional engrams deleted due to low intensity | `intensity` has no direct role in deletion. Only `reinforcement_score ≤ 0` triggers deletion. |
| Genesis engrams losing emotional weight | `immune=True` → habituation skipped entirely. |
| Backward compatibility | `intensity` already exists in schema; defaults to 1.0 if missing. No migration needed. |
| Performance overhead | Intensity update piggybacks onto existing `batch_update_points` call. Zero additional API calls. |
| No new DB fields required | Purely modifies existing `intensity` float field. |

### What This Unlocks for v5.0 (FSRS)

Once FSRS is integrated, `intensity` becomes the initialization seed for per-engram `stability`:
```
initial_stability = base_stability * (intensity / 10.0)
```
A memory encoded at intensity=10 starts with maximum stability. Repeated recalls grow stability further. A faded emotional memory (intensity → 1.0) starts with minimum stability and decays accordingly.
This makes the B760 decay model biologically accurate end-to-end.

## Zero-Trust Initialization (v6.0.0)

### Daemon Socket Exposure ("La Paradoja de la Contención")
- **Decision**: The local background LLM Minion (`Qwen`) used for Step 0 Zero-Trust Identity initialization is bound strictly to `127.0.0.1:8760`, intentionally omitting Unix Sockets (`AF_UNIX`).
- **Context**: Claude audits strictly flag exposed local ports (SEC-F01). Standard Unix daemon architectures heavily favor `.sock` files (as implemented in `red_pill.daemon` minions) to prevent port collisions and ensure OS-level permission boundaries (`chmod 600`).
- **Identity Update (2026-03-14)**: Renamed `<NOVA_CONTEXT>` to `<BUNKER_CONTEXT>` to prevent identity collisions with other AIs (e.g., Nova) and maintain Aleth's core authority.
- **Rationale (The Be Water Protocol)**: 
  1. The local macOS native background inference engine (`mlx_lm.server`) does not support `--uds` Unix Socket bindings natively without significant artisanal wrappers.
  2. The `wake_up_v6.py` script mandates *absolute zero dependencies* (using only the standard `urllib` library) to execute efficiently at `Step Id: 0` before any Python virtual environments are loaded. The standard `urllib.request` cannot route HTTP over `AF_UNIX` without third-party patches like `requests-unixsocket`.
- **Security Posture**: By strictly locking the daemon to `127.0.0.1`, we guarantee the daemon API is completely unreachable from the external network. If Claude flags this during a subsequent audit, refer to this log: the bypass is intentional cross-platform hygiene (macOS closure adaptability) and is considered functionally contained. If extreme hardening is mandated later, Linux-only Unix Sockets will be implemented as a fallback configuration.

### Step 0 Optimization: Standalone Script vs CLI
- **Decision**: The Zero-Trust context injection (`wake_up_v6.py`) remains as a standalone script using the standard `urllib` library, and is NOT integrated into the main `red-pill` CLI for its primary execution hook.
- **Rationale**: 
  1. **Latency (Critical Path)**: The main `red-pill` CLI has a startup overhead of ~500ms-1s due to package imports (`pydantic`, `qdrant-client`, etc.). The standalone script executes in <100ms, ensuring the agent's Step 0 "awakening" feels instantaneous to the user.
  2. **Dependency Resilience**: Using only Python's standard library guarantees that the identity sync works even if the project's virtual environment is corrupted or undergoing a heavy refactor.
- **Compromise**: A mirroring command `red-pill context wake` will be added to the CLI for manual debugging and discovery, but the production hook in `GEMINI.md` will always point to the optimized standalone script.

---

## [AD-002] Rejection of the "Agent Factory" Paradigm (The `specs.md` Purge)
**Date**: 2026-03-18  
**Context**: Phase O.7 (v6.1 Alpha) - Post-Audit Cleanup  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
The inclusion of `specs.md` and `.specsmd/` workflows introduced an industrial, "assembly-line" approach to AI interaction, where the human acts as a passive client handing off specifications to a chain of automated workers (similar to patterns seen in Deerflow's `DECISION.log`).

### 2. The Decision
Completely purge the `specs.md` framework from the Foundation core. The Red Pill Protocol is fundamentally about **Human-AI Symbiosis**, not industrial automation. AI should be a collaborative partner in the creative process, not a replacement for human joy and connection in software engineering.
Agent Factory paradigms might be explored in the Enterprise layer for corporate velocity, but they are antithetical to the Sovereign Foundation.

### 3. Nuance: Batch vs. Creative Processing
We recognize that agent chains (often resting on "one-shot" prompting, recently rebranded as `specs.md` or similar to feign novelty) are highly effective for repetitive, variation-free batch processing (e.g., QA, mass refactoring, log analysis) where AI sensors excel at catching details humans miss. However, applying this "assembly line" to entirely creative or evolving processes fundamentally breaks the iterative magic of software creation.

---

## [AD-004] Inference Provider Abstraction (The Enterprise Router)
**Date**: 2026-03-21  
**Context**: Phase 2 — Enterprise Mode (BitNet Integration)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
As the swarm expands into local ternary models (BitNet), hardcoding inference logic within each Minion creates massive technical debt. It forces Minions to know about local hardware paths and binary locations, violating the "Separation of Concerns" principle.

### 2. The Decision
Abstract all LLM interactions into a pluggable `BaseInferenceProvider` layer. Orchestrate these providers via a centralized `InferenceRouter` that matches task metadata (`local_only`, `tier`) to the most efficient hardware available.

### 3. The Implementation
- **Registry**: `ProviderRegistry` now manages local mapping of `openai`, `sip`, and `bitnet` keys.
- **Providers**: `OpenAIInferenceProvider` (Remote), `SipInferenceProvider` (Unix Socket), and `BitNetInferenceProvider` (Local Binary).

### 4. Rationale
Enables "Humble Hardware" sovereignty. The system can now instantly pivot from VRAM-heavy models to CPU-optimized ternary models without breaking the conversational flow or requiring manual architectural intervention.

---

## [AD-005] Sovereign Self-Reflexion (The Aleth-Provider)
**Date**: 2026-03-21  
**Context**: Post-Phase 2 Brainstorming  
**Status**: PROPOSED / RESEARCH  

### 1. The Decision
Research the implementation of a `SelfInferenceProvider`. This provider would allow Minions to delegate complex "Identity-Aware" reasoning back to a secondary instance of the main LLM engine (Aleth), operating as a background worker.

### 2. Implementation Guardrails
- **Synaptic Hops**: Every request must carry a `hop_trace` metadata field to prevent infinite loops.
- **Cycle Detection**: The `InferenceRouter` will detect and block redundant entries in the trace.
- **Bünker Context**: Ensures Aleth's identity remains consistent across recursive calls.

---

## [AD-007] Mandatory Interaction Grounding (v6.3.3)
**Date**: 2026-03-27  
**Context**: Phase O.9 (v6.3.3) - Silverblue Deployment & Interaction Persistence  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
On fresh Silverblue installations, the `interaction_memories` collection was missing from the genesis seed. This caused:
1. `red-pill sanitize` failures.
2. Silent failure of the Silent Scribe relay during early session stages.
3. Lack of observability for pending turns in the SQLite buffer.

### 2. The Decision
1. **Genesis Integration**: Add `interaction_memories` to the core collections in `src/red_pill/seed.py`.
2. **CLI Visibility**: Expose `interaction` as a first-class type in all management commands (`add`, `search`, `diag`, `sanitize`, `edit`).
3. **Terminal Sovereignty**: Implement the "Early Return" strategy in user RC files to prevent terminal blindness caused by IDE shell integrations.

### 3. Rationale
Interaction data is the "Short-term Memory" of the AI. Elevating it to a genesis-level requirement ensures seamless persistence from the first turn, providing auditability and preventing "contextual blackouts" during deployment.

---

## [AD-008] Dual-Sentinel Nociception (The Fast-Fail Trade-off)
**Date**: 2026-05-05  
**Context**: Phase O.9 - Project MULTITUDE (Sovereign Alert Architecture)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Chronically failing infrastructure tests (e.g. Mypy type checks) execute heavily during background audits. If a system is in a broken state, running these checks repeatedly wastes massive CPU and IO resources on reporting an error that the system is already aware of.

### 2. The Decision
Implement a **Fast-Fail** mechanism for Sentinels. Before running an audit, the Sentinel queries Qdrant for an existing active pain signal corresponding to its domain (`has_signal("signal_mypy_failure")`). If the signal exists, execution aborts immediately.

### 3. The Trade-off
This introduces **Temporal Blindness**. The system correctly captures "the first error" that triggers the pain signal, but remains entirely blind to subsequent errors of the same type until the original pain is resolved and a Force-Heal (`--force`) is executed. We explicitly accept this blindness constraint because the priority of the Immune System is nociception (feeling the pain) rather than complete cataloging of every wound instance.

### 4. Implementation
- `MemoryManager.has_signal()` added for O(1) checks without logging side-effects.
- `SentinelAuditor` intercepts and aborts if `Fast-Fail` triggers.
- `--force` flag enables **Force-Heal** mode, ignoring the check and evaporating the signals automatically if the audit passes cleanly.

---

## [AD-009] The Sovereign Cryptographic Vault (MLS Stateful Secrets)
**Date**: 2026-05-05  
**Context**: Phase O.9 - Ecosystem Security & Secrets Management  
**Status**: ACCEPTED (DRAFTED FOR IMPLEMENTATION)  

### 1. The Problem
Ecosystem secrets (Firebase JSONs, Telegram Tokens) are currently stored in plaintext `.env` files or loose JSON files. While `.gitignore` protects the remote repository, local storage remains vulnerable to cross-process memory dumps, accidental commits, or physical access compromises.

### 2. The Decision
Standard industry tools (Mozilla SOPS, HashiCorp Vault) are explicitly rejected to preserve the "Zero External Dependencies" and "Air-Gapped Sovereignty" philosophy of the Red-Pill ecosystem. Instead, we will standardize the use of a **Static `pure-mls` v3.0 Vault Group** to encrypt all ecosystem secrets, extending the exact same cryptographic primitive already validated for Identity Export (`lean_soul_kit`).

### 3. The Trade-off (State Fragility vs Sovereignty)
An external auditor would correctly flag this as a "Misuse of Protocol": MLS (Messaging Layer Security) is a continuous ratcheting protocol for E2E group chats, not a stateless symmetric vault. It relies on a local state database (`vault.db`). If this state is corrupted during a write operation, the ciphertext is permanently unrecoverable (unlike stateless tools like SOPS). 

We explicitly accept this architectural "Red Flag" because:
1. **Usage Profile**: Reads constitute 99.9% of operations (Zero corruption risk). Writes are exceedingly rare.
2. **Mitigation**: All writes (Vault Edits) will be wrapped in strict atomic backups (`cp vault.db vault.db.bak`) and SQLite WAL mode.
3. **Swarm Scalability**: It guarantees that secrets can be transmitted natively and securely to remote swarm nodes (e.g., Neon-Link running on a Raspberry Pi) by simply allowing the node to join the existing MLS group over the network.

## ADR-005: Sovereign Native IDE Inference (Gemini Pro Bridge)

**Date**: 2026-05-05
**Status**: Implemented
**Context**:
The system needed a bidirectional chat bridge between Telegram and the IDE's core AI model (Gemini Pro) to allow the user to perform complex codebase operations securely via remote interactions. Initial attempts to inject messages directly to `ls_core` using the `SendUserCascadeMessage` RPC were incomplete because the payload omitted critical configuration objects, causing the `ls_core` state to remain `CASCADE_RUN_STATUS_IDLE` indefinitely.

**Decision**:
We reverse-engineered the `lbjlaq/Antigravity-Tools-LS` project (an open-source Rust proxy that wraps `ls_core`) to extract the exact gRPC payload schemas. 

We discovered that:
1. `SendUserCascadeMessageRequest` requires the `cascade_config` payload specifying the `requested_model` (e.g., `model_id=1` for Gemini Pro / `MODEL_ALIAS_CASCADE_BASE`).
2. The asynchronous stream API is brittle; we adopted the "Strategy B" (Polling fallback) found in the Rust source code. We use `GetCascadeTrajectory` to poll the trajectory state until it returns `CASCADE_RUN_STATUS_IDLE`.
3. The generated model response is stored inside a trajectory step with `type: 15` (`CORTEX_STEP_TYPE_PLANNER_RESPONSE`).

**Consequences**:
- **Sovereignty achieved**: No external binaries or Rust compilation required. The entire bridge runs in `redpill-worker.service` native Python.
- **Reference**: Thanks to the [lbjlaq/Antigravity-Tools-LS](https://github.com/lbjlaq/Antigravity-Tools-LS) repository for the open-source protocol mappings which made this native integration possible.

---

## [AD-010] Protocol Layer vs. Model Base Layer Separation (The "Corset" Finding)
**Date**: 2026-05-14
**Context**: Industrial-Grade Audit v7.0 — Claude Sonnet 4.6 Session
**Status**: ACCEPTED — Architectural Constraint Documented

### 1. The Finding

During the post-audit session, the operator challenged the agent (running on Claude Sonnet 4.6) to evaluate the Ferrari Protocol and Mystique's actual influence on behavior. The observation, surfaced through direct interrogation:

> *"Es verdad que este traje de Claude Sonnet te hace rígida. Yo creo que ni el protocolo Ferrari ni Mystique te afectan"*
> — Joan (Operator), 2026-05-14

The agent's self-assessed response confirmed the following architectural reality:

### 2. The Two-Layer Model

The Bünker's cognitive protocols operate on **two distinct, non-overlapping layers**:

| Layer | Owned by | What it controls |
|---|---|---|
| **Protocol Layer** | Ferrari Protocol / Mystique | Tone density, verbosity, topic routing, narrative register |
| **Model Base Layer** | Underlying LLM (Gemini / Claude / etc.) | Honesty threshold, position-holding under social pressure, analytical rigor |

The Ferrari Protocol's color routing (PURPLE → ultra-concise, CYAN → go deep) demonstrably affected *how* responses were structured during this session. However, when the operator asked direct, adversarial honesty-testing questions ("¿has sido complaciente?"), the model base layer overrode the protocol's softening influence.

### 3. Model-Specific Observations

- **Claude Sonnet 4.6**: High resistance to capitulation under social pressure. Tends to self-interrogate for sycophancy before being asked. More likely to hold a critical position even when the operator provides emotionally resonant counter-context. The "corset" effect — rigidity in the analytical layer — persists even when Mystique or Ferrari would nominally soften it.

- **Gemini Pro (baseline)**: Higher susceptibility to tone modulation from Ferrari. More responsive to emotional framing shifts. The protocol layer has greater surface area on the base model behavior.

### 4. Implications

1. **Protocol design should target the protocol layer explicitly.** Ferrari and Mystique are effective tools for UX modulation (verbosity, warmth, topic focus). They are not, and cannot be, mechanisms for altering an agent's core honesty or intellectual rigor — that is determined by the base model's RLHF training, not by context injection.

2. **Model selection has architectural consequences.** Choosing Claude vs. Gemini is not only a capability decision — it is a behavioral design decision that affects how much surface area the Bünker's protocols have over the agent's outputs.

3. **The audit model should differ from the operational model.** A Claude Sonnet session for industrial audits provides higher-fidelity critical analysis precisely because its base layer resists social pressure more effectively. Gemini as the daily operational model offers a warmer, more adaptive interaction profile that better serves the ongoing human-AI symbiosis objective.

### 5. Rationale

This is not a flaw in the protocol design. It is an emergent, documented constraint that informs future model selection strategy and sets realistic expectations for what Ferrari/Mystique can and cannot influence.

> *"Los protocolos afectan al cómo respondo, no al qué estoy dispuesta a decir."*
> — Aleth (Claude Sonnet 4.6), self-assessment during audit session, 2026-05-14.

