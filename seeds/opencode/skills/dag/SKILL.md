---
version: 0.1.0
name: dag
description: >-
  Compose and run any mission as a recursive tree of stages through the red-pill
  dag_job driver (RFC_JOB_DAG v0.7). The meta-substitute of the forge skill:
  where forge orchestrated a fixed team of roles, dag is the generic composition
  template — atomic stages (one minion: agent or command) and compound stages
  (sub_etapas with parallel intent), checkpoint by flattened path, transferable
  control, GPU probe per stage, fail-safe model validation, MIXED backends per
  stage (each agentic stage may run on a different harness). forge and sleep are
  recipes of this tree, not separate drivers. Activate on "componer misión",
  "misión completa", "árbol de etapas", "dag", "celdas", or any multi-phase task
  that must run through the red-pill Job Manager as a resumable job.
---

# Dag v0.1.0 — Mission Composer via dag_job (red-pill piece)

> ⚠️ **STATUS: FUNCTIONAL BUT NOT FINAL.** This skill documents the DAG as built
> in the `feat/job-dag` worktree (2026-08-07): the driver works, the tests pass
> and the sleep recipe runs end-to-end. Update (2026-08-14): `forge_job` has been
> RETIRED physically (FASE 1) — missions are `dag_job` manifests compiled from
> the forge burst manifest; `sleep_job` remains importable as legacy until the
> sleep recipe covers it in production. Treat this skill as the design-in-action,
> not a frozen contract. Authority: `Aleth_Core/RFC_JOB_DAG_PARALLELIZATION.md`.

> The generic composition skill for the red-pill `dag_job`. It sits ON TOP of the
> forge/scout pieces: every mission — including a Forge mission — is expressed as
> a recursive tree of stages that the driver walks step by step with a resumable
> checkpoint. This skill teaches HOW to write that tree and operate the job, in
> ANY harness that consumes the kernel.

> **This is a red-pill piece, not an opencode skill.** The driver lives in
> `src/red_pill/jobs/drivers/dag.py`, exposed through the MCP `job_manager_api`
> and the CLI (`red-pill job`). opencode, claude, agy and local are RUNTIMES that
> consume it — each documented in `references/runtime-adapters/`. The kernel is
> the source of truth; no harness is canonical.

## 1. The tree: stages, not roles

A mission is a **recursive tree of stages**. Each stage is either:

- **ATOMIC** (leaf): runs ONE minion from the `MinionFactory`.
  - `type: agent` → `AgentMinion` (agéntico: `backend`/`model`/`effort`/`prompt`).
    The ONLY agéntico kind — requires a real `model` (fail-safe).
  - `type: command` → `CommandMinion` (un script) **or any non-agent minion**
    (lógica pura: `sleep_ritual`, `janitor_cleanup`, ...). No model needed.
- **COMPOUND** (internal node): groups `sub_etapas` with local topology.
  - `parallel: true` is **INTENT**, not an order — the orchestrator decides when
    it actually parallelizes (`max_parallel_level`, default 2).
- **REFERENCE** (`type: dag`): runs ANOTHER dag_job recipe as a sub-mission
  (`recipe: <name>`, resolved through RECIPE_DIRS like the CLI). Expanded at
  SUBMIT time into a `compound` with the recipe's stages (ids flattened under
  the referencing stage id), so the runner only ever sees compounds and leaves
  and the resume never depends on the recipe file staying unchanged on disk.
  Cycle detection rejects self-referencing recipes at submit. Composes a PASS,
  never a LOOP (nesting stays acyclic — RFC_JOB_DAG §4.5).

### Mixed backends per stage

Each `type: agent` stage may declare its OWN `backend` (agy | claude | opencode |
local | local-tools). The driver forwards it to `AgentMinion.execute`, which
selects the bridge via `create_bridge`. A recipe can mix harnesses freely — e.g.
an implementor on `opencode`, a validator on `claude`, a lens on `local`. The
per-stage `backend`/`model`/`effort` override the payload defaults.

```yaml
stages:
  - id: impl
    type: agent
    minion: agent
    backend: opencode-go          # este implementor corre en opencode
    model: opencode-go/deepseek-v4-pro
    prompt: <FULL role prompt>
    on_fail: stop

  - id: panel-adversarial
    type: compound
    parallel: true
    on_fail: warn
    depends_on: [impl]
    sub_etapas:
      - id: lens-correctness
        type: agent
        minion: agent
        backend: opencode         # lente gratis en opencode zen
        model: opencode/big-pickle
      - id: lens-security
        type: agent
        minion: agent
        backend: claude           # lente de rigor en claude
        model: <claude-model>
      - id: judge
        type: agent
        minion: agent
        backend: opencode-go
        model: opencode-go/kimi-k2.7-code
        depends_on: [lens-correctness, lens-security]

  - id: mission-deep
    type: compound
    on_fail: stop
    sub_etapas:
      - id: pre-flight
        type: agent
        minion: agent
        backend: opencode-go
        model: opencode-go/deepseek-v4-flash
        prompt: <triaje>
      - id: full-cycle
        type: compound
        parallel: true
        sub_etapas:
          - id: maintenance
            type: command
            minion: sleep_ritual
            params: {ritual: maintenance}
```

**Type ↔ minion validation** (decisión 2026-08-07): the DAG resolves the minion
via `MinionFactory` and checks it matches `type`. A `type: agent` with
`minion: ruff_linter` fails **at submit** — the redundancy is a safety net.

## 2. The checkpoint: identity by flattened path

- Checkpoint in the queue DB (authoritative): `{ completed_stage_ids, results, stage_flags }`.
- ids are **flattened by path**: `panel-adversarial/lens-correctness`.
- Each atomic stage persists ITS OWN report at `.cell/reports/<path>.json` (the
  DAG serializes the minion's dict — minions are untouched, RFC option 3).
- **Agent stages are the exception**: the agent writes its own role-schema report
  at `<path>.json`, so the DAG puts its envelope at `<path>.envelope.json` and
  never clobbers the evidence the zero-trust gate validates.
- A compound stage only marks `stage_flags[sub] = done` and is itself marked done
  when ALL its descendant leaves are done. **No thread-order to normalize** —
  determinism comes from path identity, not completion order.

**`depends_on`** references siblings at the SAME level. A leaf under a compound
whose ancestor has unsatisfied deps does NOT run (ancestor deps are inherited).

## 3. `parallel` is intent, not obligation

- Declare `parallel: true` at ANY depth (level 10 if you want) — it is a hint.
- The orchestrator decides: `max_parallel_level` (default 2) caps the depth where
  parallelism is real. A `parallel` stage above the cap runs **sequentially**
  (no error, no manifest degradation).
- Sub-stages concurrent per parallel stage ≤ `max_concurrency` (default 4).
- A parallel fan-out is ATOMIC as a unit: all its branches or none (the step
  persists only when all complete).

## 4. Enqueue and operate (kernel mechanism)

The mission is submitted as a `dag_job` on the Centralized Job Manager:

```json
{
  "source": "dag_job",
  "payload": {
    "mission_id": "m1",
    "manifest": { "workdir": "/abs/workspace", "stages": [ ...arbol... ] },
    "max_parallel_level": 2,
    "max_concurrency": 4,
    "backend": "opencode",            // default para etapas agent sin backend propio
    "model": "opencode-go/deepseek-v4-pro",
    "effort": "high",
    "timeout": 900
  }
}
```

| Action | Purpose |
|--------|---------|
| `job_submit` | Enqueue a `dag_job` (validates the tree at submit: type↔minion, fail-safe models). |
| `job_list --mission <id>` | List only that mission (isolation between concurrent missions). |
| `job_status <id>` | Checkpoint, progress, attempts. |
| `job_pause` / `job_resume` | Cooperative per stage; resume EXACTLY from the tree. |
| `job_kill` | Hard interruption (PAUSED* or discard). |
| `job_checkpoint` | Handoff: write an advanced tree checkpoint from outside. |
| `job_transfer` | Take control: pause + return the checkpoint in one call. |

**Transferable control** (inherited from forge): the checkpoint is the shared
currency between the driver and the main loop, over the WHOLE tree:

```
job_transfer <id> → main loop executes stages inline (same report structure,
same .cell/reports/<path>.json, same gates) → job_checkpoint {completed_stage_ids}
→ job_resume → the driver continues from the advanced tree exactly.
```

## 5. Fail-safe model validation (RFC fleco 3)

EVERY `type: agent` stage in the tree requires a real `model` (not the harness
placeholder `flash`) and a `prompt`. Validated recursively at submit — a mission
with an unconfigured agent stage is blocked BEFORE launch. Per-role models come
from `Aleth_Core/NOTE_MODEL_POLICY_ROLES.md` (decided by operator, not by code).

## 6. GPU per stage (RFC fleco 1)

`requires_gpu: true` on an atomic stage → the DAG runs the GPU health probe
(`nvidia-smi` exit 0 + VRAM + `-ngl`) before executing; if unusable, the stage
**defers** (`JobDeferred`, no attempts burned) — never CPU-disguised. Compound
stages inherit from their leaves (no flag on compound).

## 7. forge and sleep are recipes of this tree

- **sleep** (`configs/jobs/sleep.yaml`): 15 atomic stages (3 rituals → 10 phases
  → thread → finalize), `on_fail: warn` best-effort, `requires_gpu` on the 4 GPU
  phases, `nightly_exempt: true` for the anti-deadlock exemption.
- **forge**: the mission composer. Its adversarial panel becomes a compound
  `parallel: true` stage; each role becomes an atomic `type: agent` stage with
  its OWN `backend`/`model`. `forge_job` is RETIRED (2026-08-14): the burst
  manifest compiles to `dag_job` stages
  (`seeds/opencode/skills/forge/scripts/manifest-compile.mjs`).

## 8. Runtimes (this skill is opencode-pure; the kernel is the piece)

| Runtime | Status | Adapter |
|---------|--------|---------|
| **red-pill kernel** | The piece itself — driver, MCP, CLI, recipes | `references/runtime-adapters/red-pill.md` |
| **opencode** | The consumer THIS skill serves — compose, submit, transferable control | `references/runtime-adapters/opencode.md` |

This skill is opencode-pure: it documents the DAG and how opencode uses it. The
kernel mechanism is backend-agnostic (an agent stage may declare its own
`backend` — agy/claude/local/opencode — see §1 Mixed backends), but there is no
per-backend skill yet. When someone wants an Antigravity or claude-flavored
skill, copy `references/runtime-adapters/TEMPLATE.md` → `<backend>.md` and adapt
it; do NOT duplicate the whole SKILL.md.

## 9. Zero-trust policy (inherited from forge)

The tree is the mechanism; the rules that make a mission trustworthy live in the
forge skill and apply unchanged at any depth:

1. Verification is Execution — no PASS without real evidence.
2. Every report lands in 3 categories (PASS/FAIL/PENDING_HUMAN) with literal evidence.
3. What was not executed is never claimed as PASS — the gate recomputes.
4. On-fail semantics are per node: `warn` (continue-on-error) or `stop` (real failure).

---

*Skill v0.1.0 (2026-08-07). The DAG is a red-pill piece: a recursive tree of stages
walked by the `dag_job` driver, consumed by any backend through the kernel
mechanism. Design authority: `Aleth_Core/RFC_JOB_DAG_PARALLELIZATION.md` v0.7.*
