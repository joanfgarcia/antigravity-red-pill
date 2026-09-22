---
name: minion-delegation
description: Use when you are about to delegate/offload a single task to a minion — spawn a sub-agent, pick a backend (claude/agy/opencode/local/local-tools/pi), assign work to another model, or run a bounded local tool loop. Picks the right minion KIND for the task and shows how to invoke it in Pi (no MCP) via `red-pill job submit`. For composing multi-step minion FLOWS use swarm-flow-manager instead.
---

# Minion Delegation (Pi)

You (the orchestrator) can hand a task to a **minion**. Match the task to the
**weakest minion that can do it** — cost, latency and blast-radius all scale up
the list. Full capability matrix: `docs/TECHNICAL/MINIONS.md`.

## The kinds (weakest → strongest)

| Backend | What it is | Tools | Turns | Pick it for |
|---|---|---|---|---|
| `local` | one local-LLM call, returns text | no | 1 | summarize / classify / extract / rewrite — answer fully determined by the prompt |
| `local-tools` | bounded in-process loop on the local 8B (MCP + bash) | yes | few | short, concrete, headless chores you can express explicitly |
| `opencode` | external agent CLI (OpenCode Zen, e.g. free `big-pickle`, or local) | yes | many | tool work when you want a capable hosted/free model |
| `pi` | external agent CLI (pi-coding-agent, headless) | yes | many | tool work on a configured Pi provider/model (harness extension gives Búnker identity/RAG) |
| `claude` | external agent CLI (cloud) | yes | many | genuinely complex, multi-file, strong-reasoning tasks |
| `agy` | external agent CLI via Antigravity IDE | yes | many | same as claude, **only if the IDE is open** |

`CommandMinion` (run a script, no LLM) exists too but is an internal primitive,
not reachable through delegation.

## Decision guide

```
No LLM decision needed        → a script (internal), not this path.
LLM, no tools needed          → backend "local"          (cheap, single turn)
LLM + tools, task is short/concrete/headless/retry-tolerant
                              → backend "local-tools"     (sovereign, free, in-process)
LLM + tools, complex/long/multi-file/needs strong reasoning
                              → backend "claude"  (or "opencode"/"pi"; "agy" only if IDE open)
```

## How to invoke (Pi — no MCP)

Pi has no MCP and no `swarm_orchestrator_api`. Delegate by enqueuing an
`agentic_job` on the central queue — it survives restarts, is pausable/resumable,
and inherits the OOM shield and sleep-inhibit:

```bash
${RED_PILL_CMD} job submit --source agentic_job --payload '{
  "prompt": "In workspace X, do Y and report Z.",
  "backend": "local-tools",   // local | local-tools | claude | opencode | agy | pi
  "cwd": "/abs/path",         // where the minion operates (omit → red-pill dir)
  "timeout": 900
}' --title "descripción corta" --priority 5
```

- **Anything non-trivial → diferido**: tras el `submit`, el timer `redpill-queue`
  (1 min) lo recoge solo. Sigue el estado con `${RED_PILL_CMD} job list`,
  `job status <id>` y `job logs <id> --tail 50`; los reportes finales van a
  `MinionInbox` (`~/.local/share/red-pill/queue/minion_inbox.db`).
- **Si necesitas la respuesta YA** (chat corto): no delegues — hazlo in-process.
  No existe `run_agent_task` ni `async_mode` en Pi.

## Hard limits to respect (do not assign around them)

- **`local` / `local-tools` run an 8B @ Q4.** Reliable only for **short, concrete,
  mechanical** work. Do NOT give it ambiguous, multi-objective, or long chains.
  For `local-tools`: ≤ 8 tool calls, no context compaction, and its bash is a real
  shell — **default to read-only** tasks unless mutation is the explicit point.
- **`local` cannot use tools** — never ask it to "look up" or "check" anything; it
  has no way to. Use `local-tools` or an external backend for that.
- **`agy` needs the Antigravity IDE open** — confirm first, else pick another backend.
- Name the tool/command in the prompt when you can — small local models follow
  explicit instructions far better than open-ended ones.

When in doubt about capabilities or edge cases, read `docs/TECHNICAL/MINIONS.md`.
