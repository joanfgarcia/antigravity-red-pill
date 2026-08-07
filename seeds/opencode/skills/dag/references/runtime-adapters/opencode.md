# Adapter — opencode (a consumer)

> opencode is ONE consumer of the red-pill dag_job piece. The orchestrator
> (main loop) composes a mission tree, submits it via MCP `job_manager_api`, and
> operates it with transferable control. The piece itself is red-pill
> (`runtime-adapters/red-pill.md`). None of the harnesses is canonical; each
> backend documents its own conventions.
>
> ⚠️ **Functional but not final**: the driver and this adapter match the
> `feat/job-dag` worktree (2026-08-07), not yet merged to `main`.

## Compose the tree

Every stage is atomic (`type: agent` with `minion: agent` + `model` + `prompt`,
or `type: command` with a non-agent minion) or compound (`sub_etapas` + optional
`parallel: true`). See the SKILL.md §1 for the shape; models per role from
`Aleth_Core/NOTE_MODEL_POLICY_ROLES.md`.

## Submit via MCP

```
job_manager_api.job_submit {
  source: "dag_job",
  payload: {
    mission_id: "<mission>",
    manifest: { workdir: "<abs-workspace>", stages: [ ...arbol... ] },
    max_parallel_level: 2, max_concurrency: 4,
    backend: "opencode", model: "opencode-go/deepseek-v4-pro", effort: "high", timeout: 900
  },
  mission_id: "<mission>"   # isolation between concurrent missions
}
```

- Submit FAILS at validation time if any agent stage lacks a real model or the
  type↔minion pair mismatches. Fix the manifest, do not force the job.
- The mission is enqueued; the runner picks it up on the next timer tick
  (`systemctl --user start redpill-queue.service` for immediate unattended start).

## Operate

| Action | Use |
|--------|-----|
| `job_status <id>` | Checkpoint, progress (leaves done / total), attempts. |
| `job_pause <id>` | Cooperative — the in-flight stage completes, then pauses at the boundary. |
| `job_resume <id>` | Continue EXACTLY from the tree checkpoint. |
| `job_kill <id> [--discard]` | Hard interruption (PAUSED* or discard). |
| `job_transfer <id>` | Take control: pause + return checkpoint (`completed_stage_ids`). |
| `job_checkpoint <id> {completed_stage_ids: [...]}` | Handoff: write an advanced tree from outside. |

## Transferable control (the tree is the currency)

1. `job_transfer <id>` → the main loop gets the checkpoint.
2. Execute N stages inline — SAME report structure (`.cell/reports/<path>.json`),
   SAME schemas, SAME gates as the driver would.
3. `job_checkpoint <id> { completed_stage_ids: [...] }` → write the advanced tree.
4. `job_resume <id>` → release control: the driver continues from the advanced tree.

A handoff is atomic: there is no "half state" — both modes share the checkpoint.

## Parallel panel pattern (L2/L3 missions)

An adversarial panel becomes a compound stage:

```yaml
- id: panel-adversarial
  type: compound
  parallel: true
  on_fail: warn
  sub_etapas:
    - id: lens-correctness
      type: agent
      minion: agent
      model: opencode/big-pickle          # free lens, experimental
    - id: lens-security
      type: agent
      minion: agent
      model: opencode-go/mimo-v2.5-pro
    - id: judge
      type: agent
      minion: agent
      model: opencode-go/kimi-k2.7-code
      depends_on: [lens-correctness, lens-security]
```

`parallel: true` is intent — the DAG executes the sub-stages in threads within ONE
step when the level is within `max_parallel_level`; otherwise sequentially.

## Rules for the orchestrator

- Cold context inherits nothing: pack ALL context into each agent stage's prompt,
  plus the instruction to emit the schema-conforming JSON to `.cell/reports/<path>.json`.
- `on_fail: warn` = continue-on-error (mark FAILED, no breaker burn); `stop` = real
  failure. Choose per node; the report shows unclaimed what was not executed.
- Never claim PASS for a stage the gate did not open.
