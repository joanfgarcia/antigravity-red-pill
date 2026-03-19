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
