# Feature Matrix — Forge v1.0 (opencode port)

The protocol is a set of features. The Orchestrator resolves each one at assembly time into `.swarm/state.json` (`features{}` with `on|off|auto` values + `feature_rationale[]` with the reason per feature), and **re-evaluates at every escalation trigger** (escalation.md) — resolution is not a one-time event.

**The one rule that preserves Zero-Trust:** a feature set to `off` NEVER skips a gate check. It degrades the MECHANISM, not the control: the step that a missing agent would do is executed by the orchestrator inline (or by a deterministic script), and what was not executed is shown in the report as unclaimed (never as PASS). Verdicts and checks remain exactly the same.

## Catalogue

| ID | Feature | Class | Default | What it is |
|----|---------|-------|---------|------------|
| K1 | Disk anchoring | KERNEL | fixed | `.swarm/state.json` as source of truth, checkpoints after every task, `disk_facts` captured with git (controlled-stop.md §5). Not resolvable: always on |
| K2 | Mandatory evidence + `validate-report.mjs` | KERNEL | fixed | Every report validated against its schema before trusting (Rule 6). **v3.1 provenance**: every report carries `provenance` (harness/provider/model/timestamp) — the role emits it, or the orchestrator STAMPS it at consolidation; a report never lands in the ledger without provenance. Not resolvable |
| K3 | Deterministic gate + render | KERNEL | fixed | `gate-check.mjs` recomputes the official verdict (7 checks, 10 in mission); `render-artifacts.mjs` regenerates .md artifacts. Not resolvable |
| K4 | Assumption Registry + Plan Coverage Matrix | KERNEL | fixed | Rules 2 and 3, deterministic reducer, gate checks 2/3/4. Not resolvable |
| K5 | Verification=Execution + runtime nudge | KERNEL | fixed | Rule 1: anti-trivial evidence regex in gate check 6 + the nudge: before validating, ensure `commands_run` contains a non-trivial real command; if not, run one (opencode runtime nudge in validation steps and cycle-run) |
| K6 | Honest 3-category reporting | KERNEL | fixed | Rule 5: `qa_final.totals` requires the 3 numbers; verdict recomputed, never self-declared |
| K7 | Disk reconciliation on every start/resume | KERNEL | fixed | controlled-stop.md §4-§5: git/processes/journal BEFORE trusting state.json. Not resolvable |
| O1 | E2E smoke | optional | `on` | Rule 4: real user-flow smoke before close. `off` for doc-only tasks (then smoke is orchestrator-inline or documented as N/A — never skipped silently) |
| O2 | Adversarial panel, multi-model lenses + judge | optional | `auto` | `on` from L2 (3 lenses) / L3 (5 + judge + loop-until-dry); `auto` = `on` at ≥L2, L0-L1 uses auto-challenge/1 refuter. Multi-model: per-lens `model` override in `task` calls (heterogeneity = diversity). **v3.1 cross-provider**: per-lens `backend` override (panel-policy.md) — a lens may run on ANOTHER harness via `job_manager_api.job_submit` (`agentic_job`); same schema contract, same gate, provenance stamped in the ledger |
| O3 | Dynamic L0-L3 escalation + anti-abandonment ladder | optional | `on` | escalation.md scoring + triggers. `off` → locked at the initial level (never below floor) |
| O4 | Git-worktree isolation for parallel implementors | optional | `auto` | `auto` = `on` when ≥2 implementors mutate files in parallel; `on` = always isolate; `off` = sequential implementors only (no parallel mutation) |
| O5 | Mission Mode | optional | only 15+ phases | Autonomy contract + canonical mode + checkpoints + debt sweep (mission-mode.md). `off` → team asks instead of deciding (L0-L3 protocol only) |
| O6 | Usage sentinel + window ledger at 93% | optional | only long missions | usage-sentinel.md: Python sentinel (`usage-sentinel.py`, os-agnostic), usage-probe.mjs, ledger reservation, STOP_REQUESTED flag. `off` → no sentinel, no ledger; budget accounting only |
| O7 | Documentation Anchor for plan extraction | optional | `auto` | `auto` = `on` when the plan has ≥1 extracted point set; `on` = always extract P-nn via forge-doc-anchor; `off` = orchestrator extracts inline |
| F1 | ASK boundary | optional | `off` | Non-mission: when the ladder is exhausted, ask the Operator instead of deciding. `on` = ask after 2 escalations; `off` = best-effort decision documented in `decisions[]` |
| F2 | usageAudit | optional | `off` | Per-role skill/tool usage accounting in the ledger (`usage_audit[]` entries). `on` = track; `off` = aggregate only |
| F3 | Human approval markers | optional | `off` | `pending_human` items materialize as `-approved.md` markers next to the changes (superpowers pattern). `on` = write markers; `off` = pending_human in state.json/report only |

## Resolution rules (orchestrator, at assembly + at each escalation trigger)

0. **Triage seeds the resolution (Step 0)**: the `forge-triage` agent produces the FIRST proposal (`triage_plan`: scope score, recommendation, feature values, level, panel, budget). The orchestrator presents it to the Operator (accept / pin features / `--force` to skip) and records the final values in `feature_rationale[]` with the triage rationale as source.
1. **KERNEL (K1-K7)** is fixed: always on, no rationale needed (recorded as `kernel`).
2. **`auto` resolution**: the value depends on the task scope (table above). Record the computed value AND the condition that produced it.
3. **`on`/`off` override**: the Operator can pin any optional feature explicitly ("sin sentinel", "panel completo siempre"). Pinned values win over `auto`.
4. **Every resolution writes `feature_rationale[]`**: `{feature: "O4", value: "on", reason: "2 implementors parallel on F2"}`. The final report includes the full matrix — the Operator can audit why the team had the shape it had.
5. **Escalation re-evaluation**: on every `escalate()`/`deescalate()`, re-resolve O2 (panel size), O4 (parallel isolation) and O7 (anchor need). The other features stay unless the scope changed.
6. **`off` never skips checks**: the corresponding gate check still runs with the degraded mechanism (inline by the orchestrator or by script); if the mechanism cannot produce evidence, the report shows the item unclaimed. Feature flags change EXECUTION SHAPE, never VERIFICATION SEMANTICS.
7. **The activation gate is a feature**: `NOT_NEEDED` from Triage is recorded (`triage.recommendation`) and the swarm protocol does not engage. Overriding it is `--force` — the Operator's explicit call, never the orchestrator's.
