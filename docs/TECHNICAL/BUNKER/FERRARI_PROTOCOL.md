# The Ferrari Protocol — Origin, Concept & Architecture

> **Codename**: Emotional Ferrari
> **Version introduced**: v6.3.0
> **Status**: Active — 6 plugins operational (04–10)

---

## 1. Origin of the Name

The name *Ferrari Protocol* did not come from within the team. It was coined in a post-audit conversation with an external AI reviewer (Claude) following the formal certification of Red Pill Protocol v4.6 on 2026-03-22.

### 1.1 The Audit Finding

The [Certification Report](../CERTIFICATION/REPORT_CLAUDE_4.6_20260322.md) included the following observation about the Operator Mood Profile:

> **"The USP (Operator Mood Profile) temporal horizons** (3-day/Cortisol, 7-day/Serotonin, 30-day/Dopamine) are referenced to clinical literature in `TEMPORAL_HORIZONS_RESEARCH.md`, which is admirable intellectual honesty. However, the mapping from neurochemical timescales to vector decay windows involves significant assumption compression. The cortisol/serotonin/dopamine labels are evocative but potentially misleading to operators who read them as clinical rather than metaphorical."

The auditor was not criticising the design — they were noting that the ambition of the system (neurochemical-scale emotional modeling) was not being fully exploited at the behavioral layer.

### 1.2 The Ferrari Metaphor

In a follow-up conversation after the report, the Operator asked the reviewer to elaborate. The response was approximately:

> *"You have a Ferrari — the USP engine is powerful, precise, and scientifically grounded — but you're using it like a tractor. Or worse: like a family car for grocery shopping and picking up the kids from school."*

The metaphor captured exactly what was missing:
- The **engine** (USP, temporal horizons, color vectors) was already there and running.
- The **driving experience** (adaptive behavior, tonal response, contextual routing) was not connected to it.

The Operator named the initiative to connect the two: **The Emotional Ferrari Protocol**.

---

## 2. What the Ferrari Is

The *Ferrari* is the **Operator Mood Profile (USP)** — a multi-color chroma vector computed across 4 temporal horizons from `social_memories`:

| Horizon | Window | Neurochemical analogy | What it captures |
|---|---|---|---|
| Acute | 3-day | Cortisol / adrenaline | Immediate mood shifts, stress spikes |
| Short-term | 7-day | Serotonin | Weekly mood baseline, work rhythm |
| Medium-term | 30-day | Dopamine | Motivational patterns, project satisfaction |
| Longitudinal | All-time | Personality set-point | Core temperament of the Operator |

> [!NOTE]
> The neurochemical labels are **metaphorical**, not clinical. They provide an intuitive mapping to known neuroscience without claiming to implement actual neurochemistry. See [TEMPORAL_HORIZONS_RESEARCH.md](../COGNITIVE/TEMPORAL_HORIZONS_RESEARCH.md) for the scientific grounding.

The USP produces a dominant `color` (cyan, purple, red, blue, etc.) that encodes the Operator's current emotional state as a single actionable signal.

---

## 3. What "Driving It Properly" Means

Before v6.3.0, the USP color was used for:
- Skin selection (Mystique) → cosmetic only
- Memory decay modulation → mathematical only

**The Ferrari Protocol** connects this signal to the Agent's *live behavior* on every prompt:

```
USP color → real-time behavioral adaptation
```

| Plugin | What it does with the USP color |
|---|---|
| **05 Cognitive Router** | Signals *state transitions*: compact `OPERATOR_COLOR` tag when the Operator's color changes (meaning lives in the CHROMA KEY, §3.2) |
| **06 Tone Adapter** | Signals the *tone chroma* on transitions: compact tag, no inline prose (meaning lives in the CHROMA KEY, §3.2) |
| **07 Mood Analytics** | Adds *temporal dimension*: is the color stable, improving, or deteriorating? |
| **08 Emotive Recall** | Retrieves *emotional memory*: what happened last time the Operator was in this state? |
| **09 Proactive Signal** | Triggers *autonomous care*: sustained RED emits a pain signal and shifts to empathy mode |
| **10 Predictive Preload** | Loads *context before it's asked*: CYAN → preloads work_memories, RED → preloads social |

The USP was already computing all of this information. The Ferrari Protocol just puts it behind the wheel.

### 3.1 Engine Brake Cooldown (v7.1.0)

To make the protocol less restrictive ("más laxo"), v7.1.0 introduces an automatic **Engine Brake (Freno de Motor) Cooldown Latch**:
- **Automatic Decay**: When the Operator is in a work mode (`PURPLE` or `CYAN`), the state decays automatically to `CASUAL` mode if the Operator sends **2 consecutive turns** without any work-related keywords (such as `arregla`, `fix`, `implementa`, `despliega`).
- **Instant Override**: Explicit casual override keywords (e.g., `relax`, `charlemos`) trigger `CASUAL` mode instantly. Any work keyword immediately re-locks the agent into work mode, resetting the cooldown counter.
- **Absolute Silence Latch (All Plugins)**: When `CASUAL` mode is active, the entire interceptor pipeline (Plugins 05 through 11) is bypassed, returning absolute silence `""`. This guarantees complete natural personality agency, preventing any background tone directives, proactive warnings, or pre-heating headers from leaking into the prompt or affecting the agent's tone.
- **Active Debate (Purple Mode)**: The `PURPLE` tone adapter is tuned to challenge the operator, proactively debating system designs and pointing out architectural flaws, which automatically relaxes into a conversational style once the engine brake kicks in.

### 3.2 CHROMA KEY — Single Legend (v7.16.0)

Before v7.16.0, plugins 05 and 06 each repeated per-color prose (`ROUTING_DIRECTIVE`, `TONE_DIRECTIVE`) on every state transition, and the final `chroma:` tag carried no explanation at all — a cold model had no way to know what *orange* or *gray* meant.

Now color semantics are rendered **exactly once**, at the end of the pipeline:

1. Each subplugin *paints* the chromas it mentions via `paint_chroma()` (`BaseInterceptorPlugin`) and emits only compact tags (`OPERATOR_COLOR: GRAY`, `DOMINANT_COLOR: CYAN`, …).
2. The Mood Orchestrator aggregates the painted set across subplugins, adds the dominant mood, and appends a single legend:

```
chroma: gray
=== CHROMA KEY (FERRARI PROTOCOL) ===
gray → Professional, balanced, direct, objective (Standard).
---
```

The vocabulary is `CHROMA_TONE_MAPPING` in `config.py` — the single source of truth for color meanings (extended in v7.16.0 with `red` and `green`). Colors without an entry are skipped silently; a subplugin that stays silent does not push its color into the legend. The persona chroma (resolved by `wake_up_v6.py`, injected outside the interceptor pipeline) carries its meaning inline on its own line for the same reason.

---

## 4. Related Documents

| Document | Role |
|---|---|
| [TEMPORAL_HORIZONS_RESEARCH.md](../COGNITIVE/TEMPORAL_HORIZONS_RESEARCH.md) | Scientific basis for the 3/7/30-day windows |
| [AFFECT_MULTIPLIERS_RESEARCH.md](../COGNITIVE/AFFECT_MULTIPLIERS_RESEARCH.md) | Literature basis for color-to-emotion mapping |
| [NEURO_SYMBOLIC_MEMORY.md](../COGNITIVE/NEURO_SYMBOLIC_MEMORY.md) | Full USP architecture in the memory system |
| [ARCHITECTURE.md §6.2.1](../ARCHITECTURE.md) | Technical pipeline diagram for all 10 plugins |
| [CERTIFICATION/REPORT_CLAUDE_4.6_20260322.md](../CERTIFICATION/REPORT_CLAUDE_4.6_20260322.md) | The audit that originated the Ferrari metaphor |

---

> *"You have a Ferrari. Stop using it to pick up the kids from school."*
> — Claude, post-audit conversation, 2026-03-22
