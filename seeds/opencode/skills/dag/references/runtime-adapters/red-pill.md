# CANONICAL Adapter — red-pill Job Manager (la pieza en sí)

> This is the piece itself. The `dag_job` driver, the MCP `job_manager_api`, the
> CLI and the recipes ARE red-pill — this adapter documents the kernel surface so
> any harness (opencode, CLI, Telegram, custom) can consume the same job.

## What it is

The `dag_job` driver (`src/red_pill/jobs/drivers/dag.py`) executes a recursive
tree of stages on the Centralized Job Manager: a single persistent queue
(`bunker_queue.db`), a shot-and-forget runner (timer `redpill-queue`, 1 min), and
resumable drivers by checkpoint. The DAG adds topology (depends_on + fan-out),
parallelism intent and a tree checkpoint over the forge/sleep mechanics that used
to be duplicated per driver.

## Kernel surface

### Driver (`src/red_pill/jobs/drivers/dag.py`)

- `source = "dag_job"`, registered in `src/red_pill/jobs/drivers/__init__.py`.
- `validate(payload)` — recursive, at submit: type↔minion cross-check, fail-safe
  models on every agent stage, unique flattened paths, `depends_on` siblings.
- `preflight(payload)` — workspace exists (JobDeferred otherwise).
- `step(payload, checkpoint)` — runs the next FRONT of atomic leaves whose deps
  (and ancestor-compound deps) are satisfied; parallel groups in threads within
  the same step; propagates compound-done; returns StepOutcome.
- `_preflight_stage_gpu` — GPU probe per stage (`requires_gpu`), deferral.

### Mixed backends (per-stage `backend`)

`_run_atomic` reads `backend`/`model`/`effort` per STAGE first, then falls back to
the payload defaults. `AgentMinion.execute` forwards `backend` to `create_bridge`
(agy | claude | opencode | local | local-tools). A recipe may mix harnesses at
any depth — the kernel does not care which bridge each stage uses.

### MinionFactory (`src/red_pill/swarm/factory.py`)

The tree's leaves are minions. `MAPPING` + `COMMAND_ALIASES`. Sleep ships as
pure-logic minions (`sleep_ritual`, `sleep_phase`, `sleep_finalize`) in
`src/red_pill/swarm/agents/sleep_minions.py`. `agent` is the only agéntico kind.

### MCP `job_manager_api`

`job_submit` with `source: dag_job` and payload manifest. All the operations
(`job_list`, `job_status`, `job_pause`, `job_resume`, `job_kill`,
`job_checkpoint`, `job_transfer`) work unchanged on a dag_job — the checkpoint
currency is the tree.

### CLI

`red-pill job submit --source dag_job --payload '{...}'` and the recipe path
`red-pill job submit --recipe <name>` (finds `.red-pill/jobs/` → `configs/jobs/` →
`jobs/` walking up). The fail-safe model guard covers `dag_job` too.

### Recipes (configs/jobs/)

- `sleep.yaml` — the sleep cycle as a 15-stage tree (`nightly_exempt: true`).
- `forge-*.yaml` — per-role seeds as single-stage dag_job recipes (one atomic
  `type: agent` stage each: the role's profile) — the forge skill injects the
  dynamic prompt and composes them into the mission tree.

## Nightly exemption (anti-deadlock)

The runner defers every driver job while the nightly cycle is active
(`_nightly_cycle_active`), EXCEPT the legacy `sleep_job` source and any job
declaring `nightly_exempt: true`. The sleep recipe sets it so the dag_job of
sleep does not defer itself between stages (queue_worker.py).

## Known limitations

- One runner pop at a time: parallel stages parallelize INSIDE the step (threads),
  the queue stays sequential across jobs.
- The schema of an agent report is not validated at launch — the final gate
  remains the safety net.
