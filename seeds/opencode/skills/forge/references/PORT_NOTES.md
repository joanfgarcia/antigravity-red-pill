# Design Notes — Forge

> Purpose: document the design evolution and every versioned delta so the
> bundle is auditable. Technical English applies to all authored files of this
> bundle.

## Design lineage

Forge is a zero-trust multi-agent composer designed for opencode and the
red-pill ecosystem. Its protocol kernel — schemas, deterministic gate, nine
zero-trust rules, escalation ladder, mission pillars — is the stable contract;
the mechanism layer adapts per harness (`references/runtime-adapters/`).

## Feature set v1.0 (resolved at assembly, re-evaluated at escalation triggers)

- Kernel K1-K7 (fixed): disk anchoring; mandatory evidence+validator; deterministic gate+render; assumption registry+coverage matrix; verification=execution+nudge; honest 3-category reporting; disk reconciliation.
- Optional O1-O7 (orchestrator-decided, defaults per features.md): E2E smoke, multi-model panel+judge, dynamic escalation+ladder, worktree isolation, mission mode, sentinel/ledger 93%, doc anchor.
- Optional F1-F3 (off by default, operator-pinned possible): askBoundary, usageAudit, humanApprovalMarkers (`-approved.md`).
- **Rule**: `off` never skips a gate check — degrades the mechanism, not the verification semantics.

## Ecosystem-informed features (web survey 2026-07)

1. **Multi-model heterogeneous panel** (inspired by `opencode-agentic-workflows` — ABIvan — consensus of free reviewers + consolidator): per-lens `model` override in `task` calls; aggregation stays deterministic (escalation.md). Decided by orchestrator per lens, default `auto`.
2. **Git-worktree isolation** (inspired by `opencode-orchestrator` — agnusdei1207 — parallel worktree isolation): feature O4; helper `scripts/worktree.mjs`; merge only after the phase gate.
3. **Verification nudge** (inspired by `opencode-swarm` — zaxbysauce — evidence-in-runtime): feature K5; before validation, ensure a non-trivial command ran (anti-grep list from gate check 6); if `commands_run` is empty/trivial, execute one first.

## Gotchas verified during development

- **opencode skill name regex** is `[a-z0-9]+(-[a-z0-9]+)*` → directory/name `forge` (hyphen). The `name:` frontmatter must match the directory name.
- **Cold-context subagents**: `task` starts with fresh context; ALL role context must be packed into the prompt. opencode subagents are also cold → the main-loop context contamination concern does not apply to role agents; it applies to the ORCHESTRATOR only (anchor on disk, not context).
- **`node -e require()` with relative paths fails** in `node -e` (resolves against the eval module, not CWD). The v1.0 shell sentinel had to normalize `PROJECT_DIR` to absolute before use; the v1.1 Python sentinel (`usage-sentinel.py`) resolves `os.path.abspath()` itself — no shell path pitfalls.
- **The sentinel is Python stdlib, not shell** (v1.1, OS-agnostic): same 93%/5-min/single-shot contract, runs on Linux/macOS/Windows. Do not reintroduce `.sh` here — the whole bundle must stay portable.
- **Schemas descriptions are metadata** — the runtime validator uses only the structural keywords; Spanish descriptions are doc-only (auditable, not functional).
- **`opencode run` headless — VERIFIED (2026-08-05, checkpoint P10)**: prompt is POSITIONAL (`opencode run "<prompt>" --agent <role> --auto`); `-p` is the server PASSWORD, not the prompt. `--auto` = auto-approve permissions. In early docs/scripts `-p` was used wrongly; all invocations fixed. Verified end-to-end: full cycle (impl→valid→smoke→panel) via cycle-run.mjs with a stubbed binary; real headless run with the `forge-qa` agent confirmed the agent loads and responds.
- **Gate check 7 field**: the final panel verdict lives at state.json top level as `final_panel` (or `last_panel`) with `vote: "CLEARED"` — per-phase `devil` entries do NOT satisfy it. Learned while building the gate-OPEN fixture; `render-artifacts.mjs` may rename on render (disk wins).
- **Injection into opencode config**: subagents in `~/.config/opencode/agents/` need `hidden: true`; `permission.task` must allow `forge-*` (opencode.jsonc) for the orchestrator to launch them without prompts.

## Red-pill packaging (seed)

- Bundle seeds to `red-pill/seeds/opencode/skills/forge/` (+ `seeds/opencode/agents/forge-*.md`).
- Extend `scripts/inject_opencode.py`: `deploy_skills()` currently copies ONLY `SKILL.md` → must full-copy (copytree) the skill dir; add `deploy_agents()`. Placeholder substitution applies only to `.md` files. Red-pill is a GUEST: only touches its marked regions of `opencode.jsonc`.
- Backend `opencode` in `run_agent_task` = `opencode run --auto` (OpenCodeBridge) — validated; role prompts get the schema-instruction line (red-pill.md). **Since v1.3.0 the canonical path is `job_manager_api.job_submit` (`agentic_job`/`forge_job`); `run_agent_task` remains as the raw single-shot substrate.**

## Activation gate + Triage (v1.0 addition, Operator-approved 2026-08-05)

- The skill warns it is for HEAVYWEIGHT tasks, and every activation runs **Step 0 — Triage** before assembly: `forge-triage` subagent scores the task (phases / multi-system / production / autonomy / model profile; cap 8) and proposes the protocol shape (`triage_plan.schema.json`): recommendation `PROCEED | PROCEED_CONDENSED | NOT_NEEDED`, first Feature-Matrix resolution (O1-O7, F1-F3), level, panel size, budget estimate.
- `NOT_NEEDED` (score 0-2) → the swarm protocol does NOT engage; plain execution. `PROCEED_CONDENSED` (3-4) → minimal mechanism, no mission. `PROCEED` (5-8) → full protocol; mission only 15+ phases.
- **`--force` flag**: operator override that skips Triage + operator confirmation (orchestrator resolves the matrix itself). Deliberately not recommended — Triage catches blind spots. Forward-looking: the future `/swarm` command (name TBD — the skill may be renamed) will expose `--force` and `--condensed` as explicit flags.
- Triage is advisory: final resolution is the Orchestrator's (`feature_rationale[]`), and the schemas/gate are unchanged by it. Validated 2/2 fixtures with validate-report.mjs.

## Usage signals by opencode tier (Zed vs GO)

- On this workstation only **opencode Zed** is enabled (API wallet, credit 0, Free models only). The `SWARM_USAGE_HOOK` contract is documented in `usage-sentinel.md` §2: one JSON line, `max_utilization` = WORST across the provider's windows (GO: 5h/weekly/monthly — the hook aggregates them).
- Zed caveat: a wallet reading 0 credits with Free models available must report the FREE-tier quota, not the wallet — otherwise a false STOP fires. Ledger + cut-calibration is the active defense until a real meter endpoint is known.
- Rename checklist (when the operator renames the skill): frontmatter `name`, directory name, `permission.task` pattern, agent filenames + references in SKILL.md/docs, red-pill seeds path + `inject_opencode.py` remove-list, and the future `/swarm` command alias.

## v1.3.0 — Job Manager federation + transferable control (2026-08-05, Operator request)

1. **Every headless role goes through the Centralized Job Manager.** New MCP entry `job_manager_api` (`job_submit`, `job_list`, `job_status`, `job_pause`, `job_resume`, `job_kill`, `job_checkpoint`, `job_transfer`). Two drivers: `agentic_job` (sabor A — one role per job, recipe per role) and the new **`forge_job`** driver (sabor B — full mission manifest with checkpoint).
2. **Transferable control (the new piece, RFC SleepJobDriver pattern)**: the DB checkpoint `{step_index, results[]}` is the shared currency. Main loop takes control via `job_transfer` (pause + return checkpoint), runs N steps inline, writes `job_checkpoint`, releases via `job_resume`. `on_fail` per step (`warn` continue-on-error without burning the circuit breaker / `stop`). Telemetry mirrors to `.swarm/forge_job_status.json` (never the resume source — RFC A2).
3. **`mission_id` isolation between forges**: new column on `cognitive_tasks`, set from the payload; `job list --mission <id>` and `job_manager_api.job_list` filter by it. A `forge_job` is REQUIRED to declare it (validate at submit).
4. **Recipes per role** (`configs/jobs/forge-*.yaml`, ×9): role profile (backend/model/effort/timeout/priority); `prompt`/`cwd` dynamic in the submit.
5. `runtime-adapters/red-pill.md` rewritten as the job-manager adapter; `run_agent_task` demoted to raw single-shot substrate.

## v1.2.1 — Sentinel OS-agnostic + drift-check fixes (2026-08-05, Operator request)

1. **Sentinel rewritten to Python stdlib** (`scripts/usage-sentinel.sh` → `scripts/usage-sentinel.py`): same 93%/5-min/single-shot contract, but pure `json/os/subprocess/time/datetime` — runs identically on **Linux, macOS and Windows** (no `.sh`, no shell-isms). Launch `python3 usage-sentinel.py <project_dir>` (or harness background Bash tool). `usage-sentinel.md`, `mission-mode.md`, `controlled-stop.md`, `features.md`, `SKILL.md` and both runtime-adapters updated; auto-resume documented per-platform (systemd/`at`, launchd, `schtasks`).
2. **Drift-check fixed** (`inject_opencode.py`): `_frontmatter_version()` now compiles `_VERSION_RE` with `re.MULTILINE` (the old `search(head, re.MULTILINE)` passed the flag as *pos*, so it always returned `None` and drift was never detected); `check_version_drift()` now takes a `kind` param and `main()` passes the correct seeds subdirs (`skills/`, `agents/`) instead of the `seeds/opencode` root.
3. **Residue fixed**: `runtime-adapters/opencode.md` still referenced `~/.config/opencode/agents/swarm-*.md` after the rename → now `forge-*.md`.

## v1.2.0 — Decomposition, versioning, Scout (2026-08-05, Operator-approved)

1. **Decomposition — composer + pieces**: `SKILL.md` is now the COMPOSER (assembly, cycle, gate, escalation, mission); each role is a versioned piece: opencode agent `forge-<rol>` (executable) + portable spec `references/roles/<rol>.md` (Agent Skills format — runnable from ANY harness/backend). Pieces are usable standalone. Schemas/gate/rules unchanged.
2. **Versioning (semver, no repo federation — Operator decision)**: `version:` in frontmatter of every skill + agent (forge 1.2.0, scout 1.0.0). `inject_opencode.py` gains `check_version_drift()` — read-only audit comparing seed vs deployed frontmatter versions. Federation of repos is overkill for a solo operator; criterion to federate later: a second external collaborator or a second consumer.
3. **Scout (new sibling skill, `skills/scout/`)**: analysis + self-discovery + satellite shards. Dual use: standalone (autonomous awakenings) and piece of the Forge composer. Shard = self-contained task `{id, location, standard_violated, evidence, suggested_action, priority, consent_level}` in `.swarm/shards.json`, dedup by rule+location, consent derived (never self-declared: critical/production/irreversible → `operator`). Shards execute with ONE Forge role — never the full team. Agent `forge-scout` (lens analyst). Validates with Forge's `validate-report.mjs` (single canonical validator).
4. **Tests**: Forge suite 23 cases (15 schema incl. provenance-required, 5 gate, 3 triage); Scout mini-suite (2 shard fixtures, shard_valid/shard_invalid) using the Forge validator.

## Per-vendor enablement policy (v1.2.0)

Enablement is PER-INSTANCE, never a design constant. Each machine/vendor picks its own combination; the bundle is harness-agnostic by design.

| Vendor / instance | Skills deployed | Note |
|-------------------|-----------------|------|
| opencode — this workstation (2026-08) | forge + scout + anchors (RED_PILL.md) | Canonical runtime |
| Claude Code — this workstation | forge/scout NOT deployed | **LOCAL DECISION of this instance** (operator, 2026-08-05): opencode is the canonical runtime; Claude Code can deploy the same bundle via the mechanism delta documented in `runtime-adapters/claude-code.md` |
| Gemini (future) | GEMINI.md + per-harness seeds | Undecided; same rule: seeds per harness |

Design rules:
1. **The seeds ARE the enablement**: `seeds/<harness>/` is the deploy list for that harness. What is not in the seed dir is not deployed there.
2. **Drift-check audits within one harness only** (injector compares seed vs deployed of the same harness) — per-vendor lists never cross-validate.
3. **No vendor is privileged**: forge/scout run anywhere the harness can run node scripts + cold-context subagents; the mechanism adapter is the only per-vendor surface.
4. Local decisions belong in this table (instance + date), never in the bundle logic.

## Contract v3.1 — provenance + cross-provider panel (2026-08-05, Operator-approved)

Towards full harness-agnosticism (Operator's direction: never marry a client — Codex, Claude Code, Antigravity, Kimi, opencode are all interchangeable execution backends). The protocol kernel (schemas/gate/rules) stays IDENTICAL; the mechanism layer grows a federation channel.

1. **`Provenance` def (common.defs.json, propagated to the 7 role-report schemas as local `$defs` — self-contained, same rule as Evidence)**: `{harness (enum: opencode|claude-code|codex|agy|local|antigravity|kimi|other), provider, model, version, timestamp}`. Optional in the role schemas (backward compatible — a role may emit it or not), **mandatory at ledger time**: the orchestrator STAMPS it at consolidation if missing. A report never lands in `usage_ledger.entries[]` without provenance. `gate-check.mjs` exposes the unique sources in `summary.provenance` (informational, never a gate check).
2. **Cross-provider panel (feature O2, panel-policy.md §Cross-provider lenses)**: a lens may declare `backend` (claude|agy|opencode|local + codex/antigravity/kimi via `other`) → launched via `job_manager_api.job_submit` (`agentic_job`, `async_mode` implicit — result to Minion Inbox) → poll `job_status` / `check_minion_inbox`. *(Histórico v3.1: usaba `run_agent_task(backend=..., async_mode:true)`; sustituido por el job-manager en v1.3.0.)* Contract identical (same schema, same validate-report.mjs, same aggregation). Mandatory fallback: failed remote → local re-run with the same prompt, never a silent panel reduction. Scale: max 1 remote lens at L2, 2 at L3; judge + orchestrator always local. Only adversarial lenses (refuters, optionally validator) go remote.
3. **Ledger v3.1**: `usage_ledger` keeps `{spent_tokens, capacity_est}` and gains `entries[]` — `{role, phase_id?, report, provenance, timestamp}`. The sentinel/budget logic is unchanged.
4. **Fixture evidence**: `implementor_badprov_invalid` covers the provenance-required rule (15 schema cases in the suite; 23 total).
5. **A2A deliberately NOT adopted (Operator stance)**: Google's A2A is on watch ("de reojo") — not convinced it becomes the de-facto standard; the local contract (schemas + ledger + report files) is already transport-independent and cheap to adapt. Revisit only if A2A shows durable traction.

## External survey — tikalk/adlc-team-skills (2026-08-05, Operator request)

ADLC (Agentic SDLC, Tikal) solves a DIFFERENT problem: team-rule knowledge (index + pull-on-demand) and spec-pipeline discipline (mission-brief). It has NO adversarial panel, NO evidence-mandatory schemas, NO deterministic gate, NO usage budget discipline — its close is "a human reviews the PR". Forge's core (verification that cannot lie) is not covered by it. Adopted from the survey (below); deliberately NOT adopted: "model picks the skill per step" (weakens determinism — this bundle's protocol is fixed, the model only executes).

### Adopted: context-stuffing rationale (a)

Progressive disclosure (SKILL.md + references loaded on demand) is now an explicit design principle with a citation: arXiv:2510.05381 — context stuffing degrades compliance by 13.9%–85% as prompt length grows. Do NOT inline the full reference suite into SKILL.md; load per step, keep the anchor lean.

### Adopted: self-test suite (b)

`tests/` — regression goldsets + `tests/run-tests.mjs` (self-locating runner). Every gate/schema change must update goldsets in the same commit. Mirrors ADLC's evals-as-code idea without importing their framework.

### Adopted: supply-chain rule (c)

ADLC suffered a supply-chain worm 2026-07-27 (stolen maintainer token; payload in `.claude/` + `.vscode/` of the repo, executing on open). RULE for this bundle: skill/seed scripts are NEVER auto-executed at install; the red-pill injector only COPIES files (subst placeholders in `.md` only). Cloned or seeded skill directories are treated as untrusted input until reviewed. `npx adlc-skills-cli`-style installers that run fetched code are rejected.
