# Mission Mode — Running huge plans non-stop

> **Goal:** the Operator hands over an implementation plan of 15+ phases, says "full mission" and returns hours later to find the plan executed top-down, verified, with the best decisions taken and documented, and a final report where the ONLY pending items are punctual human interventions with exact instructions.

Mission Mode is **orthogonal to the ladder**: it mounts on L3 and adds seven pillars. It activates when the Operator asks to run a complete plan autonomously: **"execute the whole plan"**, **"full mission"**, **"non-stop"**, **"do not stop until finished"**, **"top to bottom"**.

---

## Pillar 1 — Autonomy contract (zero questions during the mission)

**Assembly phase (before touching code):**
1. The Orchestrator reads the complete **anchor plan** (e.g. `MISSION_PLAN.md`), the `CONVENTIONS.md` resolved by hierarchy, the project memory and the ecosystem rules.
2. The Documentation Anchor (Plan/Explore-style agent) extracts **every plan point** as `coverage_entry` (P-nn) and detects ambiguities.
3. Every detected ambiguity is **resolved at assembly** from the sources — never mid-mission.

**During the mission:**
- Every decision that in normal mode would be a question to the Operator is taken with **the best available option** and registered in `decisions[]` of state.json (schema `decision`: question, options with trade-offs, chosen, rationale, reversible, consulted sources). Never decide in silence.
- **Golden rule** (permanent Operator order): if a better solution exists than the literal plan, apply the best one and document the deviation (`deviates_from_plan: true`). The plan is the law (Rule 8), but the law admits documented jurisprudence.
- **Only two categories are deferred, never blocked:**
  1. **Irreversible out-of-plan actions**: deploys to PRE/PRO, data deletion, external publication, credential rotation. (If the plan includes them explicitly and the enforcement rules allow it, they execute; if not, they go to pending_human.)
  2. **Credentials/permissions the team does not have** (portal approvals, OTPs, interactive logins).
- Deferred items enter `pending_human[]` with step-by-step instructions, and the mission **continues around them**: the phase graph is reordered to advance everything not depending on the blocked item.

## Pillar 2 — Canonical execution mode + per-task checkpoints (guarantee of reaching the end)

The guarantee of completing a very long mission is not "an infinite session": it is that **no failure can lose work or context**. Real mission post-mortems proved that the full Zero-Trust cycle inside ONE workflow (high-effort implementor + validator + smoke + 5-lens panel × up to 5 iterations × 2+ phases) consumes hundreds of thousands of tokens, **does not fit in a session window** and dies halfway: port zombies, eternally RUNNING workflows, disk ≠ state.json. The hot-applied solution (decision D-12 of that mission) is the **canonical mode**:

**Canonical mode (default in every mission):**
- **ONE implementor per task**, launched as a background `task` subagent (high effort, worktree if it mutates files in parallel — O4). The main loop stays free while it works (Pillar 4).
- **Validation, smoke and the adversarial panel are executed DIRECTLY BY THE ORCHESTRATOR** with real evidence (real commands: `mvn verify`, `curl`, Testcontainers...). Long commands also go to background bash.
- **Full state.json checkpoint after EACH task**, including `disk_facts` captured by the Orchestrator with git (see `controlled-stop.md` §5) — the worst case of any disaster is repeating the task in progress, not the block.
- **The Zero-Trust gates and schemas do NOT change**: they recompute identically. Only WHO orchestrates the steps changes — short, checkpointed steps instead of one long unrecoverable workflow.

**When to use a workflow instead:** a full phase-cycle script is reserved for **short bursts** — non-mission task, or a 1-phase block with ≤10 estimated agent calls (≈1 complete iteration: impl + valid + smoke + 3-5 lenses). A full-mission workflow is **discouraged for real missions** (demos or small supervised missions only).

- The plan is still split into **blocks of 3-5 phases** respecting dependencies (unit of commit/merge and of mini-gate); the run IDs of any scripts used persist in `workflow_runs[]`.
- **Anchoring does NOT depend on conversation context: it depends on the disk.** The main loop can compact or the session can die; `.cell/state.json` contains everything needed to resume.

**Resumption protocol** (after a pause, network cut, kill or restart): the canonical prompt and steps live in `controlled-stop.md` §4-§5. Summary: **reconcile from disk FIRST** (git status + live processes + run journal BEFORE trusting state.json), then locate `resume_block`/`resume_task` (or the first block without DONE) and continue in canonical mode.

## Reconciliation protocol (mandatory on every start/resume)

On EVERY start over an existing `.cell/state.json`, BEFORE trusting it: (1) `git status` + `git log` against the `disk_facts` of the last checkpoint; (2) `ps -p` over `live_processes[]` and sweep ONLY of the registered PIDs; (3) journal of the open `workflow_runs[]`; (4) correct state.json with what the disk says. **The disk is the source of truth; agent self-report is advisory.** Full detail: `controlled-stop.md` §5.

## Pillar 3 — Phase anti-abandonment (replaces "PARCIAL and move on")

In v2.0, exhausting the 5 iterations marked the phase `⚠️ PARCIAL` and moved on — in a 15+ phase plan that buries failures. In Mission Mode:

1. Exhausting MAX_ITER does **not** mark PARCIAL: it fires the **anti-abandonment ladder** (see `escalation.md`): directed retry → judge panel of 2-3 alternative approaches in separate worktrees → decomposition of the phase into sub-phases by a Plan agent.
2. Only after the full ladder does the phase enter the **mission debt**, with the evidence of EVERYTHING tried (each attempt, each approach, each failure with its literal output).
3. **Final debt sweep:** before Final QA, the Orchestrator re-attacks all debt one last time — late phases often unlock early failures (a missing dependency, a service that now starts).
4. What survives the sweep goes to the report as debt with **diagnosis** and instructions if it requires the human.

## Pillar 4 — Mission watch and main thread ALWAYS available

- **The main loop must stay free most of the time**: every step of >2 minutes (implementor, `mvn verify`, smokes with server, cycles) is launched in **background** (`task` subagent / background bash); the Orchestrator only consolidates short results. Thus the Operator can **hot-inject instructions at any time** — including the canonical order **"stop in a controlled way"** (`controlled-stop.md` §2), which is processed as soon as the main loop consolidates the step in progress, not hours later.
- The main loop receives the completion notification of each background step, evaluates the escalation triggers (see `escalation.md`), persists the checkpoint and launches the next. **The Orchestrator is never blind for more than one task.**
- **Budget:** at assembly the cost per block is estimated. If `budget` runs out halfway: checkpoint + **honest partial report** with the resumption protocol ready. **Never** degrade the gates to "arrive" — a truly verified 60% is worth more than a lied 100% (Rule 5).
- The `escalation_log[]` and the checkpoint journal leave the narrative trace: the Operator can reconstruct the full movie of the mission afterwards.

## Pillar 5 — Final mission report

At close (or when budget runs out), the Orchestrator generates `MISSION_REPORT.md` (render of schema `mission_report` via `render-artifacts.mjs`):

- **Executive verdict** — `COMPLETE` / `COMPLETE_WITH_PENDING` / `PARTIAL` — **recomputed by `gate-check.mjs`**, never self-declared.
- **Anchor-plan coverage point by point** (the P-nn extracted at assembly): what is covered, with what evidence.
- **Autonomous decisions table** — each decision with rationale and sources, for the Operator's post-hoc review.
- **Residual debt** — what exhausted the ladder, everything attempted, diagnosis.
- **"Requires your intervention"** — the only section with work for the Operator: each item with what, why the team could not, and exact instructions solvable in minutes.
- Honest totals (pass/fail/pending_human), verified/disproven assumptions, budget spent and lessons.

---

## Pillar 6 — Survival to token limits

A 15+ phase mission can hit the session/weekly limit mid-work. The guarantee is **not** an in-session watcher — it is that no failure can lose work:

1. **Job-manager missions survive cuts natively**: when the mission runs as a `forge_job` (or its roles as `agentic_job`s), the driver's checkpoint (`checkpoint_data`) is persisted in the queue DB after every step. A subscription/API dry cut kills the session window, NOT the job: it resumes from the exact step (`job_manager_api.job_resume`), and the kernel job-monitor detects stuck (`PROCESSING` without heartbeat) and frustrated (circuit breaker) jobs and surfaces them as signals.
2. **Non-job missions**: covered by the per-step checkpoint, the §2 controlled stop (Pillar 7) and the §4 resume prompt on screen. The heartbeats (`updated_at` pre/post each long step) feed the journal that the reconciliation protocol reads on resume.
3. **Rate-limit fire drill** (`controlled-stop.md` §3): on the FIRST dead agent with a limit/credits error, relaunch NOTHING and retry NOTHING — checkpoint, `INTERRUPTED_RATE_LIMIT`, parse `resets HH:MM` if present, and end the turn with the resume prompt. Every token after the first symptom is burned margin.

```
mission ─▶ "stop in a controlled way" ─▶ PAUSED_BY_OPERATOR ─▶ resume prompt (manual)
        ├▶ dry cut / rate limit ─▶ checkpoint + INTERRUPTED_RATE_LIMIT ─▶ resume prompt
        └▶ job cut (forge_job) ─▶ checkpoint_data in queue DB ─▶ job_resume from exact step
```

## Pillar 7 — Controlled stop and canonical states

Full detail in [`controlled-stop.md`](controlled-stop.md). Contract summary:

- **Canonical Operator command**: **"stop in a controlled way"** (es: "para de forma controlada") → the team freezes the front, kills ONLY the processes registered in `live_processes[]`, checkpoints with `pause_context{}`, `mission_status: "PAUSED_BY_OPERATOR"` (writing the job checkpoint too if running as a job), and **presents a self-contained resume prompt in the chat** (valid in that chat or a new one) starting with "Reconcile from disk". It works because the main thread is free (Pillar 4).
- **Canonical states** (`controlled-stop.md` §1): `RUNNING | PAUSED_BY_OPERATOR | INTERRUPTED_RATE_LIMIT | COMPLETE | COMPLETE_WITH_PENDING | PARTIAL`. `PAUSED_BY_OPERATOR` resumes ONLY by hand; a dry-cut job resumes via `job resume` when the window is known to have reset; the on-screen prompt is always plan B.

## Model profile — guarantee with less powerful models

Plans are designed with the best available model (frontier-class), but **execution** must be trustable to a standard model. The guarantee does not come from the model: it comes from the **structure** — gates are code and do not degrade. At assembly, the Orchestrator declares the profile:

| | `modelProfile: 'frontier'` | `modelProfile: 'standard'` |
|--|--|--|
| **Plan fidelity** | Golden rule: may apply a better solution than the literal one, documenting it in `decisions[]` | **STRICT MODE: plan to the letter.** Zero improvisation; improvement ideas are registered as `PROPOSAL:` in the registry, NOT applied. On ambiguity → most literal interpretation |
| **Adversarial panel** | 3 lenses (L2) / 5 (L3) | **Always 5 lenses** — more pairs of eyes compensate less power per eye |
| **Initial escalation** | Normal scoring | Scoring **+1** (more redundancy by default) |
| **Plan deviations** | Via documented `decision` | Only if a **judge at max effort** confirms it; if in doubt, literal plan + proposal in the report |
| **Gates and schemas** | Identical | **Identical** — deterministic recomputation does not know which model wrote the JSON |

> The intuition: a frontier model with weak structure fails less than a standard one, but a standard model **inside this structure** (contracts that reject the invalid + adversarial tribunal + gate that recomputes + anti-abandonment ladder) cannot close anything that is not truly verified. The cost of a lesser model is not correctness — it is more iterations, and iterations are budgeted.

## Mission assembly checklist (the Orchestrator, before block 1)

- [ ] Anchor plan read IN FULL and P-nn points extracted to `coverage[]`
- [ ] CONVENTIONS resolved by hierarchy + enforcement rules identified (does any phase fire audit/test enforcement?)
- [ ] Plan ambiguities resolved and registered as the first `decisions[]`
- [ ] Dependency graph between phases drawn → split into blocks of 3-5
- [ ] Irreversible plan actions identified and classified (in-plan = execute with their gates; out-of-plan = pending_human)
- [ ] Budget estimated per block; escalation floor set (`floor`)
- [ ] **Model profile declared** (`modelProfile`: frontier/standard) — with standard model: strict mode + full panel + scoring +1
- [ ] **Canonical mode declared** (Pillar 2): one implementor per task in background + validation/smoke/panel by the Orchestrator + checkpoint per task (full phase-cycle scripts reserved for short bursts)
- [ ] **Survival path confirmed** (Pillar 6): job-manager checkpoint per step (if running as a job) or per-task checkpoint + resume prompt on screen for non-job missions
- [ ] `.cell/state.json` initialized with `mission`, `mission_status: "RUNNING"`, `plan_ref`, `coverage[]`, `blocks[]`, `live_processes: []`
- [ ] First checkpoint written BEFORE launching the first step

> **Ecosystem enforcement rules remain in force during a mission**: `test_enforcement` and `audit_enforcement` block deploys to PRE/PRO exactly the same. A mission is not an exception to ecosystem gates — it is their most disciplined execution.
