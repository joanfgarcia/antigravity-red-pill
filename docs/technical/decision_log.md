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

