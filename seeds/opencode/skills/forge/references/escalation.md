# Dynamic L0-L3 Escalation — Forge

v3.0 escalates **dynamically**: the Orchestrator (main loop) picks an initial level by scoring, then **raises or lowers during execution** based on what happens. Escalation adjusts parallelism and redundancy — **never the gates**: the 9 Zero-Trust rules apply identically at every level.

---

## The ladder

| Level | Name | Mechanism (opencode) | Devil's Advocate | Monitor |
|-------|------|----------------------|------------------|---------|
| **L0** | Inline | Main loop does everything; Zero-Trust rules applied inline; minimal state.json (registry + evidence) | Auto-challenge (checklist in `zero-trust-rules.md`) | No |
| **L1** | Loose agents | `task` subagent per role, sequential: Impl → Valid → Smoke; main loop consolidates into state.json | 1 generalist refuter | No |
| **L2** | Cycle | Phase cycle: main-loop sequential `task` per step, OR headless driver `cycle-run.mjs` (`opencode run --agent <role> --auto` per role, zero context pollution) + validated schemas + deterministic recomputation + `budget` | Panel of 3 independent lenses (`task` in parallel, single message) + deterministic vote | Sentinel polling + usage-probe between tasks |
| **L3** | Mission | Blocks with per-phase worktrees (O4) + checkpoints. **In Mission Mode the default pattern is canonical mode** (`mission-mode.md` Pillar 2: implementor per task in background + Orchestrator validation), NOT a full-mission workflow | Panel of 5 lenses + judge + loop-until-dry (2 dry rounds, max 3) | Checkpoints per task + main loop always free |

**Mission Mode** is orthogonal: it mounts on L3 and adds the autonomy contract, resumable checkpoints and the debt sweep (see `mission-mode.md`).

---

## Initial level — scoring

```
function initialLevel(task):
  score = 0
  score += (phases >= 3) + (phases >= 6) + (phases >= 10)      # 0..3
  score += touches_multiple_systems_or_environments ? 1 : 0     # Rules 7/9
  score += affects_production_or_shared_config ? 1 : 0
  score += operator_asks_full_autonomy ? 1 : 0                  # "non-stop", "mission"
  score += modelProfile == 'standard' ? 1 : 0                   # non-frontier model → more redundancy
  level  = score==0 ? L0 : score==1 ? L1 : score<=3 ? L2 : L3
  floor  = affects_production ? L2 : L0                         # criticality floor
  return { level: max(level, floor), floor }
```

**Model profile** (`modelProfile`): with a standard model (instead of frontier) the team compensates with structure: **+1 to scoring**, adversarial panel **always 5 lenses**, **strict mode** in prompts (plan to the letter, zero improvisation — details in `mission-mode.md` §Model profile). Gates and schemas are identical: they do not know which model wrote the JSON.

The chosen level, the floor and every later transition are recorded in `escalation_log[]` of state.json (with reason). The Operator can always reconstruct why the team had the size it had.

---

## RAISE triggers (evaluated by the main loop after each phase/block)

| Trigger | Action |
|---------|--------|
| A phase fails validation **2 times** | `escalate(+1)` — more redundancy for that phase and the following |
| Devil's Advocate votes **BLOCKER** | Expand panel (L1→3 lenses; L2→5) and minimum L2 |
| **Critical** assumption becomes **DISPROVEN** | `escalate(+1)` + reopen the phases affected by the false assumption |
| Final QA finds **coverage < 100%** | `escalate(+1)` + re-run ONLY the SIN_CUBRIR points (subset, not full mission) |

```
guard escalate(delta, reason):
  cost = estimated_cost(level + delta)
  if budget.remaining() < cost:
    report_honestly("Escalation to L{n} blocked by budget: " + reason)
    # NEVER escalate in silence or fake the escalation
  else:
    level += delta
    escalation_log.push({from, to, reason})
```

## LOWER triggers

```
on phase_gate_passes_first_try and adversarial_round_dry:   # 0 new refutations
  streak += 1
  if streak >= 2 and level > floor: level -= 1; streak = 0
else: streak = 0
```

Lowering saves tokens on calm stretches of a long mission without touching the gates. Never below the floor.

---

## Devil's Advocate by level: from lawyer to tribunal

| Level | Composition | Aggregation |
|-------|-------------|-------------|
| **L0** | Orchestrator auto-challenge (checklist) | — |
| **L1** | 1 generalist refuter (lens `general`, the 6 classic questions) | Its direct vote |
| **L2** | **3 independent refuters** (no shared context, parallel): lenses `correctness`, `env_segregation`, `plan_completeness` | Deterministic: BLOCKER if (a) majority votes BLOCKER, **or** (b) any `critical` refutation brings executed evidence — *one real proof beats two opinions* |
| **L3** | **5 refuters** (+ `security`, `perf_repro`) + **judge** adjudicating conflicting refutations (real evidence or speculation?) + **loop-until-dry**: rounds until 2 consecutive without new refutations (max 3 rounds; if it does not dry ⇒ escalated BLOCKER) | Same as L2 after the judge's filter |

Extra diversity recommended at L3: vary effort between refuters (judge always at high effort). Refuters receive already-known refutations to avoid repetition (dedup is against the SEEN, not the confirmed — prevents resurrecting already-rejected refutations).

### The lenses

| Lens | Central question |
|------|------------------|
| `general` | The 6 classic v2.0 questions (missing field, duplicate config, test passing for the wrong reason, outdated docs, local≠pro, cache) |
| `correctness` | Does the implementation do what the criterion says, or something that looks like it? Does the test pass for the right reason? |
| `env_segregation` | Rules 7+9: all environments/tabs/platforms verified separately? Parity between platforms? |
| `plan_completeness` | Rule 8: every plan point has implementation+test+smoke? Deviations documented in `decisions[]`? |
| `security` | Exposed credentials, unvalidated inputs, excessive permissions, open endpoints? |
| `perf_repro` | Is the result reproducible? Performance regressions (bulk, N+1, OOM)? |

---

## EXHAUSTED vs INTERRUPTED — what fires what

> **Lesson from real mission post-mortems:** when agents died from subscription/API limits, the workflow returned the phase as `EXHAUSTED` — indistinguishable from genuine failure. That would fire the anti-abandonment ladder (burning more agents against a dead API) when in reality it only required WAITING and resuming. They are now distinguished:

| Phase status | Meaning | Orchestrator response |
|---|---|---|
| `EXHAUSTED` | Spent `MAX_ITER` with **genuine failures** (validation/smoke/panel rejected the work) | **Anti-abandonment ladder** (below): directed retry → judge panel → decomposition |
| `INTERRUPTED` | ≥2 **consecutive agent deaths** (null result = API error / likely rate-limit) — carries `interrupted_reason` | **DO NOT escalate.** Run the usage probe: if there is margin → relaunch (completed agents come back cached); if not → controlled stop (`controlled-stop.md` §3). Agent deaths do NOT consume iterations |

## Phase anti-abandonment ladder (within a level)

The ladder fires **only** on `EXHAUSTED` (genuine failures); an `INTERRUPTED` phase follows the table above. In **canonical mode** (Mission Mode, see `mission-mode.md` Pillar 2) the Orchestrator runs the ladder with loose background agents, not workflows.

When a phase exhausts its 5 iterations it is NOT marked PARCIAL directly (that was v2.0). The internal ladder is exhausted first:

1. **Directed retry**: a fresh Implementor with the literal fail-reason of all previous attempts (included in the 5 iterations).
2. **Judge panel of approaches**: 2-3 Implementors with **distinct declared strategies**, in separate worktrees (O4), + a judge comparing results and picking the best (or combining).
3. **Decomposition**: a Plan agent splits the phase into smaller sub-phases with their own criteria; the cycle re-runs per sub-phase.

Only after all 3 rungs is the phase marked `PARCIAL` and enters the **debt** (in Mission Mode: mission debt with final sweep; see `mission-mode.md`). Debt always carries the evidence of EVERYTHING tried — the Operator never receives a "couldn't do it" without the detail of what was attempted and why it failed.
