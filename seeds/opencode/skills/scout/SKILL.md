---
name: scout
version: 1.0.0
description: >-
  Analysis and self-discovery skill. Validates implementation plans, scans
  targets (plans, code, docs, own Forge state) against the project's materialized
  rules (conventions, AGENTS.md, styleguides, schemas), and generates satellite
  tasks ("shards") for anything out-of-scope that violates a standard. Each shard is
  an autonomous task with its own prompt (hallazgo + evidencia + qué hacer),
  decoupled from the current flow. Dual use: standalone (awakenings, isolated
  analysis) and as a piece of the Forge composer (plan validation before phase 1;
  shards execute on individual Forge roles). Activate with "analiza", "scout",
  "autodescubrimiento", "valida el plan", or during autonomous awakenings.
---

# Scout v1.0.0 — Analysis, self-discovery, satellite shards

> Scout opens; Forge closes. Scout observes (does not execute), Forge verifies.
> The shard is the bridge: a finding detached from the current task, queued for
> later execution by a single Forge role — no full team assembly needed.

## 1. What Scout does

1. **Validate implementation plans** — before Forge assembles (or during a mission): is the plan complete, unambiguous, aligned with the project's rules? Feed the result back as shards + a verdict for the Orchestrator.
2. **Self-discovery** — scan a target (own `.swarm/state.json`, the bundle, any repo) for drift against materialized rules.
3. **Satellite shards** — anything seen that is wrong or non-compliant OUTSIDE the current scope becomes a shard: `{id, location, standard_violated, evidence, suggested_action, priority, consent_level}` — a self-contained task with its own prompt.

The shard pattern mirrors what strong agents do natively: noticing what is not your current task, but is wrong. Scout makes it a repeatable protocol.

## 2. The rules must be materialized

A model's "eye" is only as good as the rules it can check. Before analyzing, Scout locates the project's rule sources and loads them (they are the standard the shards will cite):

- `AGENTS.md`, `.agent/` anchors, `references/` of the skill under analysis.
- Project conventions files, styleguides, schema dirs, CI config (what CI enforces is law).
- For self-analysis of Forge: `forge/references/*.md` + `schemas/`.

If the project has NO materialized rules, Scout says so out loud and limits itself to internal consistency (plan coherence, evidence quality) — it does not invent standards.

## 3. Analysis lenses

Scout decomposes the target per lens family (a `forge-scout` agent per lens, or inline for small targets):

| Lens | What it looks for |
|------|-------------------|
| `standards` | Violations of project conventions/standards (naming, structure, styleguides, docs) |
| `consistency` | Internal contradictions (plan vs code, state.json vs disk, schema vs usage) |
| `security` | Secrets, unsafe patterns, permissions issues (only where rules materialized) |
| `architecture` | Drift from declared architecture, layering violations, TODO/FIXME debt hotspots |
| `verification` | Missing/trivial evidence patterns (the Forge Rule 1 lens on the plan's own claims) |

Cold context inherits nothing: each lens agent receives ONLY its lens + the target paths + the rule sources.

## 4. The shard record (`.swarm/shards.json`)

All findings land in the workspace shard register (`<workspace>/.swarm/shards.json`, same anchor as Forge state). One entry per shard, conforming to `shard.schema.json`:

- `id` (SHARD-nn), `location`, `standard_violated` (rule + source), `evidence` (where it shows, ≥20 chars), `suggested_action` (what to do, ≥20 chars).
- `priority`: `low` | `medium` | `critical`.
- `consent_level`: `auto` | `operator` — derived, never self-declared: `critical` OR touches production OR irreversible → `operator`. Else → `auto`.
- `status`: `OPEN` | `ACCEPTED` | `DISMISSED` | `DONE`. Scout creates `OPEN`; the Operator or an autonomous awakening moves them.
- `provenance` (v3.1 contract): who/what found it — required.

**Dedup**: a shard is NOT created if an OPEN shard exists with the same `standard_violated` + `location`. Synthesize trivial duplicates into one shard.

## 5. Decoupling (non-negotiable)

- Scout NEVER interrupts the current task. Findings are recorded, not acted upon, during the analysis run.
- Shards do NOT hold the main flow: they are queued, prioritized, and executed later (or by an autonomous awakening).
- During a Forge mission, a `forge-scout` lens runs only when the Orchestrator schedules it (O-feature; default `off` for missions, `on` at plan validation).

## 6. Consent policy (default)

| consent_level | Autonomous awakening | Interactive |
|---------------|---------------------|-------------|
| `auto` | Executes with a single Forge role (implementor/validator) | Offered as suggestion |
| `operator` | Records + lists in the awakening report (never executes) | Requires explicit Operator approval |

The Operator can pin a stricter policy per workspace (e.g. "no auto shards touching /lib"). Pinned wins.

## 7. Execution of shards (the Forge bridge)

A shard executes as a normal task with ONE Forge role — never the full team:

- `auto` + implementation shard → `forge-implementor` with the shard's `suggested_action` as the task spec (schema `implementor_result`).
- Validation shards → `forge-validator` against the relevant criteria.
- Any shard result that needs the gate stays available for a future Forge assembly (the shard record references `.swarm/reports/`).

Reports from shard executions are validated with `validate-report.mjs` (from the Forge bundle: `<forge_skill>/scripts/validate-report.mjs`) — same contract, same trust level.

## 8. Awakening mode (autonomous — will over reflex)

**The awakening is leisure time and the agent decides.** The canonical text for awakening prompts lives in `references/awakening.md` (Prompt block, injectable verbatim by the red-pill scheduler): attending signals is option (a) of three — (b) anything of the agent's own choosing, (c) do nothing and go back to sleep. Refusing is a first-class, honestly reported outcome. Signals are not orders.

If the agent chooses to attend, Scout runs headless:

1. Read the awakening target (workspace, pain signals, bundle) + materialized rules.
2. Analyze (lenses) → shards → `.swarm/shards.json` (+ ledger entries with provenance). `operator`-level shards are listed, never executed.
3. Shape the work with `forge-triage` (NOT_NEEDED → nothing or loose pieces; condensed → one piece; PROCEED → full forge only if justified AND budget allows).
4. Execute `auto` shards with single Forge roles (budget-aware, usage-probe between shards).
5. Write the awakening report: what was analyzed, shards found, shards executed, shards pending Operator, what was deliberately left unattended.

**Budget discipline**: awakening runs honor the same sentinel/probe rules as Forge missions (usage-sentinel.md) — an awakening that exhausts budget stops with the report, never degrades. Closing is evidence: shards go DONE only with a validated `execution_ref`.

## 9. References

- `references/shards.md` — register format, dedup, consent flow, ledger.
- `references/schemas/shard.schema.json` — the shard contract.
- Forge bundle (`~/.config/opencode/skills/forge/`) — roles, gate, validate-report.mjs, usage-probe.mjs, sentinel.
