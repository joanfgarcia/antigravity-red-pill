---
version: 1.4.0
name: forge
description: >-
  Multi-agent Zero-Trust execution composer. Orchestrates 9 composable role pieces (orchestrator, implementor, validator, smoke,
  devil's advocate panel, judge, doc anchor, QA, triage) with JSON contracts
  validated, dynamic L0-L3 escalation, self-accounting usage ledger, mission
  mode for huge plans (15+ phases) with controlled stop, and a feature matrix
  resolved by the orchestrator per task scope. Federation via the red-pill Job
  Manager (v1.3.0): headless roles run as agentic_jobs and full missions as a
  resumable forge_job with transferable control (main loop ↔ driver); survival
  to token limits is native (per-step checkpoint + job-monitor). Sibling
  of the scout skill (analysis + satellite shards). Activate when the operator
  says "levantar equipo", "cell mode", "team up", "full mission", "ejecuta el
  plan entero", or on any multi-phase task requiring exhaustive validation. Skill
  invocation is the explicit operator opt-in to multi-agent orchestration.
---

# Forge v1.4.0 (opencode) — Zero-Trust Multi-Agent Composer

> The composer skill: 9 composable role pieces (agents + portable specs in `references/roles/`), orchestrated by the main loop. Scout (`~/.config/opencode/skills/scout/`) is the sibling analysis skill — its shards execute on individual Forge pieces.

> Design history and versioned deltas: `references/PORT_NOTES.md`.

## 1. Four non-negotiable premises

1. **Context anchoring** — The Orchestrator IS the main loop of the conversation, NEVER a subagent. Its anchor persists on disk (`.cell/state.json`).
2. **Flank division** — Each flank of the task (implementation, validation, real behavior, adversarial, plan coverage, QA) is covered by a dedicated role.
3. **Maximum honesty** — Every report lands in 3 categories (PASS / FAIL / PENDING_HUMAN) with literal evidence. Lying about test state is the team's worst offense.
4. **Completion guarantee** — In long tasks (Mission Mode) the team reaches the end of the plan without stopping or asking; only operator-only items land in the final report.

## 2. When it activates — and the activation gate

> ⚠️ **This skill is for HEAVYWEIGHT tasks.** If the task is a small fix or a 1-2 file change, the answer is normally "no team": plain execution (L0 inline at most) is the right protocol. The skill's own Triage step (Step 0) says so out loud.

- Operator says: "levantar equipo", "modo cell", "equipo de trabajo", "tarea compleja".
- Mission Mode: "misión completa", "ejecuta el plan entero", "sin parar", "de arriba abajo".
- Task has 3+ phases, requires exhaustive validation, or touches env/MCP/integration config.

**Every activation runs Step 0 (Triage) first** — the specialized agent that scores the task (phases, multi-system, production, autonomy, model profile) and proposes the protocol shape. Its `NOT_NEEDED` verdict is a success, not a failure: respecting the gate is a feature. `--force` (explicit operator override) skips Triage; not recommended — Triage catches blind spots.

## 3. Feature Matrix — orchestrator-resolved knobs

Every protocol step is a feature. The orchestrator resolves each feature at assembly time into `.cell/state.json` (`features{}` + `feature_rationale[]`), and re-evaluates at every escalation trigger.

**Rule (preserves Zero-Trust):** a feature set to `off` NEVER skips a gate check. It degrades the MECHANISM (agent → orchestrator-inline → deterministic script). What was not executed is never claimed as PASS; the report shows it unclaimed.

| ID | Feature | Class | Default |
|----|---------|-------|---------|
| K1 | Disk anchoring (state.json, checkpoints, `disk_facts`) | KERNEL | fixed |
| K2 | Mandatory evidence + `validate-report.mjs` (Rule 6) | KERNEL | fixed |
| K3 | Deterministic gate `gate-check.mjs` + `render-artifacts.mjs` | KERNEL | fixed |
| K4 | Assumption Registry + Plan Coverage Matrix (Rules 2,3) | KERNEL | fixed |
| K5 | Verification=Execution (Rule 1) + runtime nudge | KERNEL | fixed |
| K6 | Honest 3-category reporting (Rule 5) | KERNEL | fixed |
| K7 | Disk reconciliation on every start/resume | KERNEL | fixed |
| O1 | E2E smoke (Rule 4) | optional | `on` (off for doc-only) |
| O2 | Adversarial panel, multi-model lenses + judge (3/5 lenses) — as a dag_job compound `parallel: true` stage (RFC_JOB_DAG step 5) | optional | `auto` (on ≥L2) |
| O3 | Dynamic L0-L3 escalation + anti-abandonment ladder | optional | `on` |
| O4 | Git-worktree isolation for parallel implementors | optional | `auto` (on if parallel) |
| O5 | Mission Mode (autonomy contract, pillars 1-7) | optional | only 15+ phases |
| O7 | Documentation Anchor agent for plan extraction | optional | `auto` (on for big plans) |
| F1 | ASK boundary (non-mission: ladder exhausted → ask operator) | optional | `off` |
| F2 | usageAudit (skill/tool usage per role in ledger) | optional | `off` |
| F3 | Human approval markers (`-approved.md` for pending_human) | optional | `off` |

Resolution rules per level and full catalogue: `references/features.md`.

## 4. The pieces — composable roles (this SKILL.md is the composer)

Every role is an independent, versioned piece: an opencode subagent (the executable unit) + a portable spec in `references/roles/<role>.md` (Agent Skills format — runnable from any harness or backend, v1.2.0). The Orchestrator (main loop) composes them per the protocol below; each piece is also usable standalone.

| Piece | opencode agent | Portable spec |
|-------|----------------|---------------|
| 🔍 Triage | `forge-triage` | `references/roles/triage.md` |
| 🎯 Orchestrator | The main loop — anchors the plan, resolves features, decides level, invokes the pieces, consolidates state.json, reports (emits `decision` in mission) | — |
| 🔨 Implementor | `forge-implementor` | `references/roles/implementor.md` |
| ✅ Validator | `forge-validator` | `references/roles/validator.md` |
| 🔥 Smoke Tester | `forge-smoke-tester` | `references/roles/smoke_tester.md` |
| 😈 Devil's Advocate | `forge-devils-advocate` (one per lens) | `references/roles/devils_advocate.md` |
| ⚖️ Judge (L3) | `forge-judge` | `references/roles/judge.md` |
| 📌 Documentation Anchor | `forge-doc-anchor` | `references/roles/doc_anchor.md` |
| 🧪 QA Final | `forge-qa` | `references/roles/qa_final.md` |

**Cross-cutting (v1.2.0)**: scout (skill) composes the same pieces — shards from a scout analysis execute on individual roles without assembling the full team. Every piece emits provenance v3.1; the orchestrator stamps it at consolidation.

**Source of truth: `.cell/state.json`.** Human renders (`execution-tracker.md`, `assumption_registry.md`, `coverage_matrix.md`, `implementation-report.md`, `qa-report.md`, `MISSION_REPORT.md`) are regenerated by `scripts/render-artifacts.mjs`. Never edit them by hand.

Schemas: `references/schemas/` — transversal rule: *agent verdict is advisory; the gate recomputes*.

## 5. Execution protocol (7 steps)

### Step 0 — Triage (activation gate + first proposal)
1. Orchestrator packs the task (and the anchor plan if one exists) into a `task` call to `forge-triage` → `triage_plan` JSON at `.cell/reports/triage.json`, validated with `validate-report.mjs` against `triage_plan.schema.json`.
2. **`recommendation: "NOT_NEEDED"`** → the cell protocol does NOT engage. The task runs plain (L0 inline at most). Nothing else to do — this is the gate doing its job.
3. **`PROCEED` / `PROCEED_CONDENSED`** → the Orchestrator presents the Operator a 3-4 line proposal: recommendation, complexity score, level, panel size, budget estimate. The Operator accepts, pins any feature (Section 3), or says `--force` (skip Triage on re-runs).
4. The triage proposal is ADVISORY: final resolution is the Orchestrator's, recorded in `features{}` + `feature_rationale[]` (the triage rationale seeds it).

### Step 1 — Assemble and anchor the plan
1. Break the task into phases with verifiable acceptance criteria (`C-nn`) and define how each is verified with real execution.
2. Extract plan points (`P-nn`) → `coverage[]` (Documentation Anchor via `forge-doc-anchor` if the plan is big).
3. Resolve the Feature Matrix (Section 3) → `features{}` + `feature_rationale[]`.
4. Initialize `.cell/state.json` and render the initial tracker.

### Step 2 — Choose the escalation level
Apply the scoring of `references/escalation.md`: phase count + multi-system/env + touches production + requested autonomy + `modelProfile` → L0/L1/L2/L3, floor L2 if production is touched. Record level and reason in `escalation_log[]`.

### Step 3 — Execute per level
- **L0**: main loop executes inline with zero-trust rules (auto-challenge checklist).
- **L1**: one `task` subagent per role (Impl → Valid → Smoke → 1 Devil), consolidating each JSON into state.json.
- **L2**: short bursts — main-loop cycle (sequential `task` per step; panel lenses in parallel in a single message) OR the headless driver `scripts/cycle-run.mjs` (deterministic loop, `opencode run --agent <role> --auto` per role, zero context pollution). Both emit the same result JSON.
- **L3 / Mission**: canonical mode — ONE implementor per task as background `task` + validation/smoke/panel executed by the orchestrator with real evidence + checkpoint after every task. `cycle-run.mjs` only for short bursts (1 phase, ≤10 estimated agent calls). See `references/mission-mode.md`.

Rules: copy-and-adapt, never run blind. Role prompts must pack ALL context (cold context inherits nothing) and instruct emitting the schema-conforming JSON to `.cell/reports/<role>-<phase>.json`; the orchestrator validates with `validate-report.mjs` before trusting.

### Step 4 — Evaluate escalation triggers (after each phase/block)
| Trigger | Action |
|---------|--------|
| Phase fails validation 2× | +1 level |
| Devil votes BLOCKER | expand panel, minimum L2 |
| Critical assumption DISPROVEN | +1 and reopen affected phases |
| Coverage <100% after QA | +1 and re-run only the SIN_CUBRIR subset |
| 2 clean phases in a row at first try | −1 (never below floor) |

If the budget cannot afford escalation: report it honestly — never escalate in silence. A phase exhausting iterations is NOT marked PARCIAL: it fires the anti-abandonment ladder (directed retry → judge panel of approaches → decomposition). Exception: an `INTERRUPTED` phase (agents down by rate-limit/API) does NOT fire the ladder — resume, never escalate. Re-resolve the Feature Matrix here too.

### Step 5 — Final QA + deterministic gate
QA Final (`task` subagent `forge-qa`, preconditions read from state.json), then:
```bash
node <skill>/scripts/gate-check.mjs .cell/state.json
```
The gate recomputes the official verdict (7 checks, 10 in mission). If CLOSED → fix violations and repeat. **The team cannot close what the gate does not open.**

### Step 6 — Render and honest delivery
```bash
node <skill>/scripts/render-artifacts.mjs .cell/state.json .cell
```
Report real totals (PASS/FAIL/PENDING_HUMAN), decisions taken, and the "Requires your intervention" section when applicable.

## 6. Mission Mode (15+ phases, non-stop)

Seven pillars — full detail in `references/mission-mode.md`:

1. **Autonomy contract**: zero questions during the mission; every decision taken with the best option and recorded (`decision`); only irreversible out-of-plan actions and credentials go to `pending_human[]` with instructions, and the mission continues around them.
2. **Canonical mode + per-task checkpoints**: one implementor per task in background + validation/smoke/panel by the orchestrator with real evidence + checkpoint (with git `disk_facts`) after EVERY task. Anchoring depends on disk, not context. Every resume starts by reconciling from disk.
3. **Anti-abandonment**: no phase gives up without exhausting the ladder; residual debt is re-attacked in a final sweep. `INTERRUPTED` phases resume, never escalate.
4. **Main loop ALWAYS free**: every step >2 min goes to background (task/bash); the main loop only consolidates. Operator can hot-inject instructions anytime — including "para de forma controlada". Budget exhausted → checkpoint + honest partial report (never degrade gates to "arrive").
5. **Final report** (`MISSION_REPORT.md`): verdict recomputed by the gate, point-by-point coverage, decisions, debt with diagnosis, and a "Requires your intervention" section solvable in minutes.
6. **Token-limit survival**: canonical states `RUNNING | PAUSED_BY_OPERATOR | INTERRUPTED_RATE_LIMIT | COMPLETE*| PARTIAL`. Missions that run through the red-pill Job Manager survive dry cuts natively: the driver's checkpoint (`checkpoint_data`) is persisted after every step in the queue DB, so a subscription/API cut never loses the mission — the job resumes from the exact step (`job resume`), and the kernel job-monitor detects stuck/frustrated jobs. A mission NOT running as a job is covered by: per-step checkpoint, the §2 controlled stop, and the §4 resume prompt on screen. `PAUSED_BY_OPERATOR` resumes manually only.
7. **Controlled stop**: operator writes "para de forma controlada" → team freezes the front, kills ONLY registered PIDs from `live_processes[]`, checkpoints everything (and writes the job checkpoint if running as a job), and presents a self-contained resume prompt in the chat.

**Model profile** (`modelProfile: 'frontier'|'standard'`): with `standard` → strict mode (plan to the letter, zero improvisation, improvements registered as PROPOSAL), always 5-lens panel, escalation scoring +1. Gates are identical: they do not know which model wrote the JSON.

## 7. The 9 Zero-Trust Rules

Full text with enforcement in `references/zero-trust-rules.md`:

| # | Rule | Enforcement |
|---|------|-------------|
| 1 | Verification is Execution | anti-trivial regex in gate (check 6) + K5 runtime nudge |
| 2 | Assumption Registry | schema `assumption` + gate check 2 (0 ASSUMED at close) |
| 3 | Plan Coverage Matrix | deterministic reducer + gate check 4 (0 SIN_CUBRIR) |
| 4 | Smoke E2E before close | schema `smoke_report`: PASS impossible without evidence |
| 5 | Fail-Fast Honesty | `qa_final.totals` requires all 3 numbers; gate recomputes |
| 6 | No "Verified" without Output | mandatory `Evidence` (command+exit_code+output) |
| 7 | Environment Segregation | panel lens `env_segregation` |
| 8 | The Plan is the Law | lens `plan_completeness` + coverage vs anchor plan; deviations only via documented `decision` |
| 9 | Environment Symmetry | `parity_table` in smoke; asymmetry → critical assumption |

Rules do not change with level: they apply identically from L0 to L3 and mission.

## 8. Runtimes

| Environment | Status | Adapter |
|-------------|--------|---------|
| **opencode** | ✅ CANONICAL — task subagents, parallel calls, background tasks, headless `cycle-run.mjs` | `references/runtime-adapters/opencode.md` |
| **red-pill Job Manager** | 🔀 Federation channel (v1.3.0) — every headless role runs as an `agentic_job` (sabor A) or a full mission as a resumable `dag_job` (sabor B, **transferable control**; legacy `forge_job` still accepted), via `job_manager_api` MCP + recipes per role, `mission_id` isolation | `references/runtime-adapters/red-pill.md` |

## 9. Closing checklist (Final Gate)

Verified deterministically by `scripts/gate-check.mjs` — the orchestrator cannot skip it:

- [ ] Every phase in `DONE` or documented `PARCIAL` (check 1)
- [ ] ZERO `ASSUMED`/`INVESTIGATING` assumptions (check 2), all `DISPROVEN` with fix (check 3)
- [ ] Coverage without `SIN_CUBRIR`; PENDING_HUMAN/BLOCKED documented (check 4)
- [ ] ZERO FAIL without fix (check 5) and ZERO PASS with trivial/absent evidence (check 6)
- [ ] Final adversarial panel = `CLEARED` (check 7)
- [ ] *(Mission)* decisions with rationale and sources (check 8); actionable pending_human (check 9)
- [ ] *(Mission)* `live_processes[]` empty — zero zombies (check 10)

**If the gate is CLOSED → the task is NOT reported as DONE.** It is reported with its real state: partial, with pending items, with documented blockers.
