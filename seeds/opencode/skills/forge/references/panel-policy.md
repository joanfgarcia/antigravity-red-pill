# Adversarial Panel Policy — Forge v1.0 (feature O2)

Policy for assembling the multi-model adversarial panel (port feature O2 — multi-model heterogeneous lenses, inspired by the ecosystem survey: `opencode-agentic-workflows` consensus pattern). The aggregation is deterministic (escalation.md); this policy only decides WHO attacks.

## Composition by level

| Level | Lenses | Judge | Loop |
|-------|--------|-------|------|
| L0 | Orchestrator auto-challenge (checklist, zero-trust-rules.md) | — | — |
| L1 | 1 refuter, lens `general` | — | — |
| L2 | 3 independent refuters, parallel: `correctness`, `env_segregation`, `plan_completeness` | — | — |
| L3 | 5 refuters: + `security`, `perf_repro` | 1 judge (max effort) | loop-until-dry (2 dry rounds, max 3) |

`modelProfile: 'standard'` → panel ALWAYS 5 lenses at any level ≥L2 (mission-mode.md §Model profile).

## Model assignment (multi-model heterogeneity)

The orchestrator assigns models per lens. Principles:

1. **Diversity beats power**: assign at least 2 different models across the panel whenever available (`task` `model` override). Same-model lenses correlate errors; the panel exists to break correlation.
2. **The judge runs at the highest available effort**, and, when possible, a different model than the majority of refuters (the judge adjudicates their claims — independence matters).
3. **Lenses that verify the same evidence** (`correctness` vs `perf_repro`) may share a model; lenses attacking different surfaces (`security` vs `plan_completeness`) should not.
4. **Provider-agnostic**: models come from the configured providers; if only one model is available, vary effort/temperature instead (same-lens diversity degrades to effort diversity — documented in `feature_rationale[]`).
5. **Cold context**: every refuter receives ONLY its lens instructions + the reports to attack + the seen-refutations list (dedup). No shared mutable state in prompts (determinism gotcha, runtime-adapters/opencode.md rule 7).

## The seen-refutations list

Refuters receive the refutations already known (including previously rejected ones) and must NOT repeat them (dedup is against the SEEN, not the confirmed — prevents resurrecting rejected claims, escalation.md §Devil's Advocate). The judge receives the full list plus the conflicts.

## Cross-provider lenses (v3.1 — multi-backend panel)

Each lens may declare a `backend` in addition to `model`. The orchestrator assigns it at panel assembly and records it in the O2 rationale.

| Value | Meaning |
|-------|---------|
| `auto` (default) | Same harness: `task` subagent with per-lens `model` override |
| `opencode` / `claude-code` / `agy` / `local` / `codex` / `antigravity` / `kimi` | Run the lens on ANOTHER harness via `job_manager_api → job_submit {source: agentic_job, payload: {prompt, backend, model, effort}, mission_id}` → poll `job_status` / Minion Inbox |

Rules:

1. **The contract never changes**: the cross-provider lens emits the SAME schema-conforming JSON to `.swarm/reports/`, validated by the SAME `validate-report.mjs`, aggregated by the SAME deterministic rule. The gate does not know which backend produced the report — and does not care: evidence must stand on its own.
2. **The orchestrator stamps provenance**: if the remote report lacks `provenance`, the orchestrator stamps it (backend + model requested) when writing the ledger entry. `gate-check.mjs` summary shows the unique sources (`provenance.sources`) — the Operator can audit who attacked what.
3. **Fallback is mandatory**: if the remote backend fails (timeout, no response, invalid JSON), the lens runs LOCAL with the same prompt. A failed backend never silently reduces the panel; the fallback is recorded in `feature_rationale[]`.
4. **Scale discipline**: max 1 cross-provider lens at L2, max 2 at L3. The judge and the orchestrator always run local (the judge at the highest available effort, a different model than the refuter majority).
5. **Latency cost**: remote lenses run async (Minion Inbox) — the orchestrator polls between local steps, never blocks the main loop waiting synchronously.
6. **Only adversarial lenses go remote**: refuters (L2/L3) and, optionally, the validator. Implementors stay local (they mutate the workspace). Never the orchestrator.

## Aggregation (deterministic, NOT decided by the panel)

- BLOCKER if majority votes BLOCKER **or** any `critical` refutation carries executed evidence (*one real proof beats two opinions*).
- After the judge's filter (L3), the same rule applies to the surviving claims.
- The gate (check 7) requires the panel verdict `CLEARED` to open; a BLOCKER panel verdict escalates (escalation.md raise triggers).

## Resolution into state.json

At assembly (and on every escalation), the orchestrator writes into `features`/`feature_rationale[]`: `{feature: "O2", value: "on", panel: {lenses: [...], models: {lens: model}, judge: {...}}}` — the full panel composition is auditable post-mission.
