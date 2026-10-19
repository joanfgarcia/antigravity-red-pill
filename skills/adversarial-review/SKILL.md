---
name: adversarial-review
version: 1.0.0
description: >-
  Institutionalizes the multi-round adversarial audit ritual that surfaced real
  bugs before shipping (the "R5" pattern): cold context, re-executed ground truth,
  scope = the delta prior rounds did NOT cover, materialized rules first,
  per-lens Scout findings, [branch]/[pre-existing] classification, remediation by
  waves, one shard = one commit. Activate with "auditoría adversarial", "revisión
  adversarial", "ronda N", "zero-trust review", or before/after implementing a
  branch. Sibling of the scout (finds) and forge (verifies) skills.
---

# Adversarial Review — zero-trust audit ritual

> The ritual is deterministic prose, not a new engine: it composes **scout**
> (open/find) and **forge** (verify/close) over a **cold-context** audit of a
> branch or plan. It exists because the same audit, re-invented each session,
> drifts and misses what previous rounds already covered.

## 1. When it activates

- Operator says: *"auditoría adversarial"*, *"revisión adversarial"*, *"ronda N"*,
  *"zero-trust review"*, *"ataca esto"*.
- Natural moment: **before** implementing a design (validate the plan) or **after**
  implementing a branch (hunt bugs before shipping), in a **new session**.

If it is a 1-2 file change, this ritual is overkill — run plain execution (Forge L0
triage `NOT_NEEDED`). The gate that decides is `forge-triage`.

## 2. Protocol (the ritual)

1. **Cold context.** New session; do not inherit the author's narrative. Read the
   real tree, not the summary.
2. **Ground truth, re-executed.** Run the repo's own checks YOURSELF and record the
   literal output — never trust the last measured figure: `ruff format --check .`,
   `ruff check .`, `mypy <pkg>/`, `pytest …`. This is the baseline the audit defends.
3. **Scope = the uncovered delta.** Read `git log main..HEAD` and the prior shards
   register (`.cell/shards.json`, `provenance`). Audit **what previous rounds did NOT
   cover** — never re-litigate a settled round.
4. **Materialize the rules BEFORE analyzing.** Load `CONVENTIONS.md`, `AGENTS.md`,
   `.agent/rules/*`, `.editorconfig`, CI config, schemas. *The standard must be
   materialized or the lens is only as good as the reader.*
5. **Lenses (one `forge-scout` per lens, cold).** `standards`, `consistency`,
   `architecture`, `security`, `verification`, **`decision_gaps`** (open design
   decisions / holes — see `scout`). Each lens agent gets ONLY its lens + target
   paths + rule sources.
6. **Findings → shards, classified.** One shard per finding (schema `shard`):
   `location`, `standard_violated` (+ source), `evidence` (**an executable command +
   output**, ≥20 chars), `suggested_action`, `priority`, `consent_level`, `provenance`.
   Tag each **[branch]** (introduced by the delta) vs **[pre-existing]** (repo debt).
   No executed evidence → not a shard.
7. **Remediation by waves, dependency-aware.** Order from **least to most impactful**
   with a **dependency topology**: cosmetic/global sweeps AFTER the logic fixes of the
   same file; structural refactors LAST. **One shard = one atomic commit**
   (`fix|docs|test|refactor(area): … — SHARD-nn`).
8. **Validate per commit (soft gate).** After each fix: `ruff format --check`,
   `ruff check`, `mypy` (if src), a **directed probe** (command + output) of the
   finding, and a **no-regression** test on the affected cluster.
9. **Report + ledger.** What was audited, shards found/closed/pending, what was
   deliberately left. Closing a shard requires a validated `execution_ref` (evidence),
   never intention. Operator-level shards are listed, never auto-executed.

## 3. Hard rules

- **No invented standards.** If the project has none materialized, say so and limit
  to internal consistency — do not import foreign conventions.
- **No code changes during the audit phase.** The audit *records* (shards); the fix
  phase is a separate, ordered pass.
- **Honesty over closure.** A shard stays `OPEN` until executed; a round ends with its
  real state, not a rounded-up "all green".
- **Provenance per round.** Shards carry the round id so the next round computes its
  scope as the delta automatically (`reaudit=N`).

## 4. Federation

- Analysis roles run as `forge-scout` (cold, per lens); fixes with a single Forge role
  per shard (`forge-implementor`/`forge-validator`), never a full team.
- Long audits run through the Job Manager as an `agentic_job`/`dag_job` (see the
  `job-manager`/`dag` skills); the main loop stays free.

## 5. References

- `scout` skill — lenses, shards register, consent policy.
- `forge` skill — roles, deterministic gate, Rule 10 (`GAP`, not invent).
- The project's **Implementation Contract (IC)** convention — the "what" that removes
  design holes *before* implementation (kept with the design record, per the
  project↔desk separation).
