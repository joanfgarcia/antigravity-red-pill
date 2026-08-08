# ALTERNATIVE Adapter — red-pill Job Manager (cola central + drivers)

> **Status:** the **job-manager path** for **headless / autonomous / sovereign / heterogeneous** scenarios (no interactive IDE, different model per role, missions in background, or Bünker traceability). The canonical runtime of Forge is opencode (`opencode.md`); for normal interactive orchestration use that one. **Since v1.3.0 the federation channel (contract v3.1) runs through the Centralized Job Manager** (`red-pill job` / `job_manager_api` MCP) — `run_agent_task` remains as the raw single-shot substrate for synchronous one-offs.

## What it is

Everything that launches a headless agent from the Forge skill goes through the **Centralized Job Manager**: a single persistent queue (`bunker_queue.db`), a runner shot-and-forget (timer `redpill-queue`, 1 min), and **resumable drivers by checkpoint**. Instead of `run_agent_task` inline, the skill **encolues** roles as jobs and polls them. Benefits: persistence across restarts, checkpoint/resume, priority arbitration, GPU deferral, Minion Inbox reporting, and **`mission_id` isolation between concurrent forges** (two missions never step on each other).

Two drivers matter for Forge:

| Driver | Source | What it runs |
|--------|--------|--------------|
| Agentic | `agentic_job` | ONE prompt via a backend (opencode/claude/agy/local). **Sabor A**: one role per job. Recipe per role fixes backend/model/effort. |
| Dag | `dag_job` | A full mission as a RECURSIVE TREE of stages (minions + sub-stages, `parallel` intent). **Sabor B**: the whole mission in background, with **transferable control**. Since RFC_JOB_DAG v0.7 `forge_job` is the LEGACY name — new missions declare `dag_job` manifests (§4.1: atomic `minion`/compound `sub_etapas`). |

### MCP entry: `job_manager_api`

The skill talks to the job manager through MCP (no shell dependency):

| Action | Purpose |
|--------|---------|
| `job_submit` | Enqueue a job (`agentic_job` or `forge_job`). Validates the payload at submit. |
| `job_list` | List active jobs; filter by `mission_id` (isolation between forges). |
| `job_status` | Full row: checkpoint, progress, attempts, error_log. |
| `job_pause` / `job_resume` | Pause at a step boundary / resume from the checkpoint. |
| `job_kill` | Hard interruption (PAUSED* or discard). |
| `job_checkpoint` | **Handoff**: write a new checkpoint on a PAUSED/PENDING job from outside. |
| `job_transfer` | **Take control**: pause + return the checkpoint in one call. |

### Recipes per role (`configs/jobs/forge-*.yaml` in the kernel repo)

One recipe per role — the role's execution profile as an ATOMIC dag_job stage, versioned:

`forge-triage`, `forge-implementor`, `forge-validator`, `forge-smoke-tester`, `forge-devils-advocate`, `forge-judge`, `forge-doc-anchor`, `forge-qa`, `forge-scout`.

Each is a `dag_job` recipe whose `manifest.stages[0]` defines the role's profile:
`type: agent`, `minion: agent`, `backend`, `model`, `effort`. The `prompt` is
**dynamic** (per task) — the skill injects it into the stage when composing the
mission manifest. The recipe is the profile, not the content.

## Sabor A — Main loop in command (default): one role per job

The Orchestrator stays the main loop (it decides escalation/panel/judge) and each headless role runs as a **single-stage dag_job** (the role's recipe) enqueued and polled:

```
1. Pack ALL role context into the prompt (cold context inherits nothing) +
   the instruction to emit JSON conforming to the schema (references/schemas/)
   into .cell/reports/<role>-<phase>.json.
2. job_manager_api.job_submit { source: dag_job,
     payload: { mission_id,
       manifest: { workdir: <workspace>, stages: [
         { id: <role>, type: "agent", minion: "agent",
           backend: <role-backend>, model: <role-model>, effort: <role-effort>,
           prompt: <FULL> } ] } },
     mission_id: <mission> }
3. Poll job_status (or wait for the Minion Inbox report) until COMPLETED.
4. Consolidate the report into .cell/state.json; run validate-report.mjs /
   gate-check.mjs / render-artifacts.mjs — the gates are identical.
5. Provenance (v3.1): if the report lacks provenance, STAMP it (backend + model
   requested) at consolidation and record it in the ledger.
```

Parallel panel (L2/L3): compose the panel as a COMPOUND stage with `parallel:
true` (see Sabor B / `configs/jobs/forge-panel.yaml`) — the DAG parallelizes the
lenses inside one step; do NOT fall back to N serialized `agentic_job`s.

## Sabor B — Full mission in background with TRANSFERABLE CONTROL

`dag_job` runs the entire mission manifest as a resumable job (RFC_JOB_DAG v0.7). The checkpoint in the DB is the shared currency between the driver and the main loop. Each step of the plan becomes an ATOMIC stage (`type: agent`, `minion: agent`, `model` per role policy, `prompt`), and the adversarial panel becomes a COMPOUND stage with `parallel: true`:

```
payload = {
  mission_id, manifest: { workdir, stages: [
    { id: "impl", type: "agent", minion: "agent", model: "<per-role>", prompt: "<FULL>", on_fail: "stop" },
    { id: "panel", type: "compound", parallel: true, depends_on: ["impl"], on_fail: "warn",
      sub_etapas: [
        { id: "lens-correctness", type: "agent", minion: "agent", model: "opencode/big-pickle", prompt: "..." },
        { id: "judge", type: "agent", minion: "agent", model: "opencode-go/kimi-k2.7-code", prompt: "...",
          depends_on: ["lens-correctness"] } ] } ] },
  max_parallel_level, max_concurrency, timeout
}
checkpoint = { completed_stage_ids: [...], results: {...}, stage_flags: {...} }
```

Legacy `forge_job` (phases→steps) still runs for existing jobs; new missions use `dag_job`. The full manifest RFC: `Aleth_Core/RFC_JOB_DAG_PARALLELIZATION.md` §4.1.

- **Driver in control (background)**: the runner walks the tree alone; each atomic stage executes one minion and the DAG serializes its report to `.cell/reports/<stage-path>.json`; telemetry mirrors to `.cell/dag_status.json` (never the resume source — the DB checkpoint is authoritative, RFC SleepJobDriver A2).
- **`on_fail` per stage** (and per sub-stage): `warn` (default) = mark FAILED and continue WITHOUT burning the circuit breaker (continue-on-error); `stop` = real job failure (attempts++, circuit breaker if it insists).
- **Main loop takes control (on demand)**:
  1. `job_transfer <id>` → pause + return the checkpoint (`completed_stage_ids`).
  2. Execute N stages inline (same report structure, same schemas).
  3. `job_checkpoint <id> { completed_stage_ids: [...] }` → write the advanced checkpoint.
  4. `job_resume <id>` → **release control**: the driver continues from the advanced tree exactly.
- **Pause/kill are cooperative per step** (like SleepJobDriver): the in-flight unit completes, then the runner reads state at the boundary (R3) and pauses.

### Aislamiento entre forges

Every job carries `mission_id`. `job_list --mission <id>` lists only that mission; the job-monitor and polling never mix missions. The `cwd` per workspace already separates `.cell/` on disk. A `dag_job` (and legacy `forge_job`) is REQUIRED to declare `mission_id` (validation at submit).

## Handoff between agents via `workspace-memory` (artifact = result + signal)

When a task is phased across agents that do NOT share context (parallel windows / cold context), **coordination is local and goes through the `workspace-memory` bank** (`<workspace>/.red-pill/memory/`), not shared context. The artifact of a phase is **both result and signal**:

1. The orchestrator agrees, per phase with dependents, **which artifact** is written and **where** (stable path+name under `.red-pill/memory/`, e.g. `handoff/<task>/phase-<N>.md`).
2. On **finishing** phase N, the agent **writes the artifact** (result + a "ready" marker).
3. The dependent-phase agent **polls that path**: starts immediately if it already exists, or waits until it appears.

It is **local** (filesystem) coordination, NOT neon-link. Do NOT use the Bünker (engrams/identity) or Agent_Core (transversal agent notes) for this — task artifacts go to the workspace-memory of the workspace (knowledge_access anchor, the 4 boundaries).

## Known limitations

- The schema is not validated at launch (the cold process could deviate) → the final gate remains the safety net.
- Resumption goes through the DB checkpoint (`step_index`), not a shared `resumeFromRunId`.
- The queue runner is sequential across JOBS (one pop at a time), but a `dag_job`
  parallelizes INSIDE its step (threads): an L3 panel of 5 lenses runs in ONE step.
  In sabor A (one `agentic_job` per lens) the queue still serializes them.
