# Adapter Template — how to add a backend consumer

> The dag skill is ONE skill for the red-pill piece. A new backend is a NEW
> ADAPTER, not a new skill: copy this file, fill in the harness-specific notes,
> and keep the kernel mechanism (MCP `job_manager_api` / CLI) as the contract.

## Why adapters, not per-backend skills

The tree, the manifest, the checkpoint and the transferable control are kernel
facts — identical for every harness. Only HOW the orchestrator talks to the
kernel, and any harness quirks, differ. Duplicating the whole skill per backend
would rot immediately. The SKILL.md stays the single source of truth; each
adapter adds the 10% that is harness-specific.

## How the kernel reaches each backend

`AgentMinion.execute` selects the bridge via `create_bridge(backend)`:

| `backend` | Bridge | Requires |
|-----------|--------|----------|
| `agy` | `AgyBridge` | `agy` CLI (Antigravity IDE) |
| `claude` | `ClaudeBridge` | `claude` CLI |
| `opencode` | `OpenCodeBridge` | `opencode` CLI |
| `local` | `LocalBridge` | local SLM via SIP provider (one-shot, no tools) |
| `local-tools` | `LocalToolBridge` | local model + bounded in-process tool loop |
| `opencode-go` | (subscription) | opencode subscription models (suffix `-go`) |

A mixed recipe puts the `backend` ON THE STAGE:

```yaml
- id: impl
  type: agent
  minion: agent
  backend: claude                # este etapa corre en claude
  model: <claude-model>
  prompt: <FULL role prompt>
- id: verify
  type: agent
  minion: agent
  backend: opencode
  model: opencode/big-pickle     # y esta en opencode zen
  prompt: <verify>
```

The payload-level `backend` is only the DEFAULT for stages without their own.

## Steps to add backend X

1. **Copy this file** → `runtime-adapters/x.md`.
2. **Fill the header block**: harness name, CLI/binary, how to reach the kernel
   (MCP server config, or `red-pill job` CLI).
3. **Compose**: how the X-orchestrator writes a manifest (the tree shape is in
   `../manifest.md` — do NOT repeat it, link it).
4. **Submit**: the exact call X uses to enqueue a `dag_job` (MCP tool, or CLI).
5. **Operate**: any X-specific notes on pause/resume/kill/transfer (the action
   table in the SKILL.md §4 is generic — reference it, add only deltas).
6. **Harness quirks**: cold-context packing, subprocess/thread semantics, model
   naming for THIS backend, known limitations.
7. **Register** the adapter in the SKILL.md §8 table.

## Template

```markdown
# Adapter — <BACKEND> (a consumer)

> <BACKEND> is ONE consumer of the red-pill dag_job piece. The piece itself is
> red-pill (`runtime-adapters/red-pill.md`); the tree contract is `../manifest.md`.

## Reach the kernel
<!-- how THIS harness talks to job_manager_api (MCP server config, URL) or the
     `red-pill job` CLI. -->

## Compose the tree
<!-- link ../manifest.md; note only what is different here (e.g. model naming,
     how prompts carry the report instruction). -->

## Submit a dag_job
<!-- the exact call/envelope for THIS harness. -->

## Operate
<!-- deltas only: reference SKILL.md §4 table, add harness-specific notes. -->

## Harness quirks
<!-- cold-context packing, tool/subprocess semantics, model names, limitations. -->
```
