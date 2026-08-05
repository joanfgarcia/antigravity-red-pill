# CANONICAL Adapter — opencode (task subagents + headless driver)

This is the reference runtime of Forge. Here the team deploys its full power: validated JSON contracts, parallel adversarial panel, deterministic gate, resumption and Mission Mode.

> **Opt-in to orchestration:** when the Operator activates this skill ("levantar equipo", "modo swarm", "misión completa", "equipo de trabajo"), that invocation **constitutes the explicit opt-in** to multi-agent orchestration with the `task` tool that the skill instructs.

## Mechanism mapping

| Concept | opencode tool |
|---------|---------------|
| 🎯 Orchestrator | **The main loop of the conversation.** NEVER a subagent — the only one whose context anchors the plan and who talks to the Operator |
| Roles as agents (L1) | `task` subagent (`forge-implementor`, `forge-validator`, `forge-smoke-tester`, `forge-doc-anchor`, ...) — defined in `~/.config/opencode/agents/forge-*.md` (hidden, only invocable via tool-detection `@agentname`). The main loop passes criteria and consolidates the JSON back into state.json |
| Roles as agents (L2/L3) | Same `task` subagents, one per step (sequential) or several per lens in a single parallel message (panel) — never embedded in a workflow graph: opencode has no Workflow tool |
| Phase cycle | Main-loop cycle per phase, OR the headless driver `scripts/cycle-run.mjs` (short bursts): deterministic loop calling `opencode run --agent <role> --auto` per role with a packed prompt; both emit the same result JSON |
| Adversarial panel | N `task` calls (one per lens) in a single message — parallel; per-lens model/effort override via the `model` field of `task` (feature O2). **v3.1 cross-provider lens**: instead of `task`, call `job_manager_api → job_submit` with `source: agentic_job` (backend=claude\|agy\|opencode\|local, model, effort, mission_id) and poll `job_status` / `check_minion_inbox` between local steps (panel-policy.md §Cross-provider lenses) |
| Mission implementor (**canonical mode**) | `task` subagent with `background: true` (high effort, worktree if it mutates files — feature O4). The main loop stays FREE while it works and consolidates the JSON on completion |
| Long Orchestrator commands (`mvn verify`, smokes with server) | Bash tool (background when long); server PIDs registered in `live_processes[]` of state.json (controlled-stop.md §6) |
| Mission blocks | The main loop in canonical mode (per task) — phase-cycle scripts only for short bursts |
| Monitor | **No Monitor tool.** Sentinel = `python3 <skill>/scripts/usage-sentinel.py <project_dir> &` (background process of this session, ~0 tokens, dies with session) + orchestrator polls `.swarm/STOP_REQUESTED.json` between tasks (`usage-sentinel.md`) |
| Controlled stop | The Operator writes **"para de forma controlada"** → protocol of `controlled-stop.md` §2 (possible because the main loop is free) |
| Usage auto-stop | `node scripts/usage-probe.mjs .swarm/state.json` between tasks — exit 2 = stop (`controlled-stop.md` §3); `decision: "UNKNOWN"` = fail-open, continue. Ledger reservation at 93% before every background launch |
| Resumption | Reconcile from disk (`controlled-stop.md` §5) → continue in canonical mode. Experimental OPT-IN one-shot: `systemd-run --user --on-calendar` / `at` launching `opencode run "<resume prompt>" --auto` (`usage-sentinel.md` §4) |
| Closing gate | `node scripts/gate-check.mjs .swarm/state.json` (Bash) |
| .md artifacts | `node scripts/render-artifacts.mjs .swarm/state.json <outdir>` (Bash) |

## Role subagent contract (L1+)

1. **Cold context inherits NOTHING.** The main loop packs ALL context into the prompt: phase spec, acceptance criteria C-nn, plan points P-nn covered, conventions, ecosystem rules, known prior results. No shared registry by reference.
2. **Emit the schema-conforming JSON to `.swarm/reports/<role>-<phase>.json`** and mention the file path in the result. The orchestrator validates with `validate-report.mjs` BEFORE trusting (advisory verdict).
3. Prompts must NOT embed mutable state produced by concurrent steps (breaks determinism — parallel items only read fixed inputs; see gotcha below).
4. `background: true` only for steps that (a) take >2 min, (b) do not need the orchestrator mid-way. Long Orchestrator validation commands also go to background bash.
5. **Provenance (v3.1)**: when consolidating any report, the orchestrator stamps `provenance {harness, provider, model, timestamp}` if the role did not emit it, and records it in the `usage_ledger.entries[]` — including which backends produced which lenses (panel-policy.md). `gate-check.mjs` exposes the unique sources in `summary.provenance`.

## Rules

1. **Copy and adapt, never run blind.** The scripts are starting points: the Orchestrator fills phases/args with the real task (id, spec, criteria C-nn, covered points P-nn) and adjusts lenses/effort.
2. **Schemas live in `references/schemas/`** (self-contained `$defs`, no URI registry). `validate-report.mjs` is the runtime validator (zero deps). In case of discrepancy the schemas/ dir rules.
3. **The input enters via prompt/args (real JSON, not string).** The output persists the main loop into `.swarm/state.json` — role agents write only `.swarm/reports/`.
4. **No `Date.now()`/`Math.random()` in deterministic steps** (would break resume parity). Timestamps are stamped by agents in their Evidence or by the main loop when persisting.
5. **Worktree isolation (feature O4) only** for agents that mutate files in parallel (Implementors). Validator/Smoke of a phase operate on their Implementor's result; the merge to the main tree only after the phase gate.
6. **Budget**: if the Operator gives an objective ("+500k"), cycles respect it; without it, the Orchestrator watches spend per block and reports.
7. **Deterministic resume gotcha**: prompts built from shared state mutated by parallel items (e.g. a registry mutated by several concurrent phases) depend on interleaving and break cache/parity. Sequential phase execution avoids it; if you activate parallel items, do not embed state mutated by other phases into prompts.
8. **In Mission the main loop stays FREE**: every >2 min step goes to background (`task`/Bash); the Orchestrator never blocks the thread waiting synchronously for a long step. That is what lets the Operator hot-inject instructions and ask "para de forma controlada" without waiting hours.

## Typical lifecycle (L2)

```
Main loop (Orchestrator):
1. Assemble plan → phases with criteria C-nn → points P-nn (Doc Anchor via forge-doc-anchor)
2. Initialize .swarm/state.json + execution-tracker (render)
3. Per phase: task(forge-implementor) → validate-report → task(forge-validator) → task(forge-smoke-tester) → panel (parallel task per lens)
   (or headless: cycle-run.mjs for short bursts)
4. On completion: merge result into state.json → evaluate escalation triggers
5. Remaining FAIL/debt → anti-abandonment ladder (escalation.md)
6. Final QA (forge-qa) → node gate-check.mjs
7. node render-artifacts.mjs → reports → honest report to the Operator
```

## Lifecycle in Mission Mode (canonical mode)

```
Main loop (Orchestrator), PER TASK:
1. node scripts/usage-probe.mjs .swarm/state.json   → exit 2 = auto-stop (controlled-stop.md §3)
2. updated_at = now (pre-step heartbeat)
3. task(forge-implementor, background: true, high effort)
   ... main loop FREE: hot instructions / "para de forma controlada" ...
4. Completion → consolidate implementor_result (advisory)
5. Validation + smoke + adversarial panel EXECUTED BY THE ORCHESTRATOR with real evidence
   (long commands in background bash; servers → live_processes[] and kill at end)
6. disk_facts captured with git + full state.json checkpoint + post-step heartbeat
7. Next task (or mini-gate + commit at block close)
```

Detail in `../mission-mode.md` (Pillars 2, 4 and 7) and `../controlled-stop.md`.
