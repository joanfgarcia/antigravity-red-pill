# The Manifest — recursive stage tree (contract)

> Full specification of the `dag_job` payload. Source of truth:
> `Aleth_Core/RFC_JOB_DAG_PARALLELIZATION.md` §4.1.
>
> ⚠️ **Functional but not final**: this contract matches the `feat/job-dag`
> worktree build (2026-08-07), not yet merged to `main`. The shape is stable and
> tested; the retirement of `forge_job`/`sleep_job` as drivers and the forge
> panel migration are deferred until the recipes are validated in production.

## Payload

```json
{
  "mission_id": "str (required — isolation between concurrent missions)",
  "manifest": {
    "workdir": "abs path to the workspace",
    "stages": [ "recursive array — see below" ]
  },
  "max_parallel_level": 2,     // default 2: depth where `parallel` is really parallel
  "max_concurrency": 4,        // default 4: concurrent sub-stages per parallel stage
  "backend": "opencode|claude|agy|local",
  "model": "per-role default for agent stages",
  "effort": "low|medium|high",
  "timeout": 900,              // seconds per atomic stage
  "nightly_exempt": true       // optional: exempt from the nightly anti-deadlock deferral
}
```

## Stage

A stage is **atomic** or **compound**. Both may carry:

| Field | Meaning |
|-------|---------|
| `id` | Unique GLOBALLY across the tree (paths are built from ids). |
| `depends_on` | Sibling ids at the SAME level that must be `done` first. |
| `on_fail` | `warn` (default: continue-on-error) or `stop` (real failure). |

### Atomic (`type: agent` | `type: command`)

```json
{ "id": "impl", "type": "agent", "minion": "agent",
  "backend": "opencode-go", "model": "opencode-go/deepseek-v4-pro",
  "prompt": "<FULL role prompt>", "on_fail": "stop" }
```

```json
{ "id": "lint", "type": "command", "minion": "ruff_linter" }
```

```json
{ "id": "maintenance", "type": "command", "minion": "sleep_ritual",
  "params": { "ritual": "maintenance" } }
```

- `type: agent` requires `minion: agent`, a real `model` (never `flash`) and `prompt`.
- `type: command` accepts ANY non-agent minion (`command_runner`, `ruff_linter`,
  `janitor_cleanup`, `sleep_*`, ...). `command` may come from the minion alias or
  a `params: {command: "..."}`.
- `requires_gpu: true` (atomic only) → GPU probe + deferral before running.
- `params` → arbitrary kwargs forwarded to `minion.execute(task, **params)`
  (e.g. `phase_index`, `ritual`, `mode`).

### Mixed backends (per-stage `backend`)

`backend`, `model` and `effort` are read PER STAGE first, then fall back to the
payload defaults. `AgentMinion.execute` forwards `backend` to `create_bridge`
(agy | claude | opencode | local | local-tools). A recipe may mix harnesses at
any depth — the kernel does not care which bridge each stage uses:

```yaml
stages:
  - id: triage
    type: agent
    minion: agent
    backend: local                  # barato, decisión binaria
    prompt: <clasifica y devuelve verdict>
  - id: impl
    type: agent
    minion: agent
    backend: opencode-go            # el código real en la suscripción
    model: opencode-go/deepseek-v4-pro
    prompt: <implementa>
    depends_on: [triage]
  - id: lens-security
    type: agent
    minion: agent
    backend: claude                 # lente de rigor en claude
    model: <claude-model>
    prompt: <audita>
    depends_on: [impl]
```

### Compound (`type: compound`)

```json
{ "id": "panel", "type": "compound", "parallel": true, "on_fail": "warn",
  "depends_on": ["impl"],
  "sub_etapas": [ "atomic or compound stages (recursive)" ] }
```

- NEVER carries a `minion`; REQUIRES non-empty `sub_etapas`.
- `parallel: true` is INTENT (see SKILL.md §3) — the orchestrator decides.
- Marked `done` when ALL descendant leaves are `done`.

## Validation (at submit — fails fast, not after 3 attempts)

1. `mission_id` present.
2. `manifest.workdir` present; `stages` non-empty.
3. Every id unique (flattened path). `depends_on` references exist (siblings).
4. `type` ∈ {agent, command, compound}.
5. Type ↔ minion cross-check via `MinionFactory`: `type: agent` must resolve to
   `AgentMinion`; `type: command` must NOT resolve to an agent minion.
6. Fail-safe models (recursive): every agent stage has a real `model` + `prompt`.
7. `on_fail` ∈ {warn, stop}.

## Checkpoint

```json
{
  "completed_stage_ids": [ "impl", "panel/lens-correctness", "panel/judge", "panel" ],
  "results": { "impl": "summary", "panel/lens-correctness": "summary" },
  "stage_flags": { "impl": "done", "panel/lens-correctness": "done" }
}
```

- ids flattened by path (`panel/judge`) — deterministic order = manifest DFS order.
- Each atomic stage serializes its minion dict to `.cell/reports/<path>.json`
  (the DAG does it — minions are untouched).
- Compound nodes appear in `completed_stage_ids` only when all their leaves are done.
- Resume/transfer operate on the WHOLE tree from this checkpoint.
