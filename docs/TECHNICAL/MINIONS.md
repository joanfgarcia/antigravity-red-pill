# Minions — capabilities, usage & limitations

Red Pill can delegate work to **minions**. This document is written for two readers:

- a **human** deciding how to structure delegated work, and
- an **orchestrating agent** (e.g. Aleth) that spawns minions via the
  `swarm_orchestrator_api` MCP tool and must know *what each kind can and cannot do*
  before assigning a task.

> **TL;DR for the orchestrator:** match the task to the weakest minion that can do
> it. One-shot text → `local`. Complex tool-using work you can supervise → external
> agent (`claude`/`agy`/`opencode`/`pi`). Sovereign in-house tool loop → `run_local_minion`
> (not yet MCP-exposed; see §5). Never assign a multi-turn, many-tool, long-context
> task to the local 8B model.

---

## 1. The taxonomy

| Kind | What it is | Agent loop | Tooling | Turns | Inference |
|------|-----------|-----------|---------|-------|-----------|
| **Simple** (`CommandMinion`) | Runs a shell command/script, captures output | No | n/a | 1 (exec) | none (no LLM) |
| **Local, one-shot** (`backend="local"`) | Single local-LLM call, returns text | No | No | 1 | local (Granite via SIP) |
| **Local, tool-using** (`run_local_minion`) | Bounded in-memory tool loop on the local model | Yes (≤8) | MCP + bash | few | local (Granite via SIP) |
| **External agentic** (`backend="claude"|"agy"|"opencode"|"pi"`) | Full agent delegated to a vendor CLI | Yes (vendor) | MCP + bash + files | many | external (cloud/hosted) |
| **Logic** (`sleep_ritual`, `sleep_phase`, `sleep_finalize`, `dossier_gate`, `echo`, `janitor_cleanup`…) | Pure in-process kernel logic — no shell, no LLM | No | n/a | 1 (call) | none (no LLM) |

On top of all of these sits the **orchestrator** (you), which picks the kind, writes
the role prompt, and collects results. Logic minions are normally not spawned by
hand: they run as `type: command` stages of a **dag_job recipe** (e.g. the sleep
cycle `configs/jobs/sleep.yaml`, or the ideation-loop gate re-enqueued via
`dossier_gate.enqueue_pass`) — the recipe declares them, the Job Manager runs them
with checkpoint/on_fail/pause semantics (RFC_JOB_DAG).

---

## 2. How to invoke (agent-facing)

All MCP calls go through the `swarm_orchestrator_api` tool.

### External agentic minion — `run_agent_task`
```jsonc
// action: "run_agent_task"
{
  "prompt": "In workspace X, find and fix the failing test in module Y. Report the diff.",
  "backend": "claude",        // "claude" | "agy" | "opencode" | "pi" | "local" (omit → IDE_BACKEND)
  "model": "sonnet",          // backend-specific (opus/sonnet/haiku/claude-opus-4-8; opencode/pi: provider/model)
  "effort": "medium",         // low|medium|high|xhigh|max (claude; others may ignore)
  "workspace": "/path/to/project",  // omit → red-pill's own dir
  "timeout": 600,             // seconds (default 600)
  "async_mode": true          // true (default) → Minion Inbox; false → wait + inline
}
```
- **Async (default):** the call returns immediately; poll results with
  `check_minion_inbox`. Use for anything non-trivial (the loop can run minutes).
- **Sync (`async_mode:false`):** blocks and returns inline — **only for short tasks**,
  the MCP call is held open the whole time.

### Local one-shot minion
Same `run_agent_task` with `backend:"local"`. No tools, no loop — a single
generation. Good for: summaries, classification, extraction, rewriting, a quick
judgment. `model`/`effort` are largely ignored (the local daemon serves one model).

### Local tool-using minion
Same `run_agent_task` with `backend:"local-tools"` — the local model runs a bounded
in-process tool loop (MCP + bash) and returns the final answer:
```jsonc
{ "prompt": "How many entries in /path/to/dir? Use run_bash, then answer with the number.",
  "backend": "local-tools", "workspace": "/path/to/dir", "async_mode": false }
// → response: "51"
```
It is also callable directly as a Python entry point (same loop):
```python
from red_pill.swarm.agents.local_minion import run_local_minion
result = await run_local_minion("…", cwd="/path/to/dir")
# → {"ok": True, "answer": "51", "steps": 1, "used_tools": True, "tool_calls": 1, "messages": [...]}
```
`tool_calls` counts every executed call; `used_tools` is True only if at least one
returned a non-`ERROR` result — the `local-tools` bridge flags an answer without one
as *ungrounded* (`error` set), so an invented or failing tool never passes as verified.

---

## 3. Capabilities & limitations, per kind

### Simple (`CommandMinion`)
- **Can:** run any command/script (exec via `shlex` — **no shell**, so no pipes/redirection),
  with `cwd`/`env`, and return stdout/stderr/returncode.
- **Cannot:** reason, retry, or chain. It is a subprocess, not an agent.
- **Limits:** ⚠️ **no built-in timeout** — a hung command hangs the caller. Not
  directly invokable via an MCP action today (internal orchestration primitive).

### Local, one-shot (`backend:"local"`)
- **Can:** produce a text answer from a single prompt, fast and free (local Granite).
- **Cannot:** use tools, read files, run commands, or take a second turn
  (`mcp_tools=False`, `conversation_resume=False` by design).
- **Best for:** single-turn transforms where the answer is fully determined by the
  prompt. **Do not** ask it to "look something up" or "check X" — it has no way to.

### Local, tool-using (`run_local_minion`)
- **Can:** run a **bounded** tool loop — call `run_bash` (real `/bin/sh`: pipes,
  redirection, globs) and the RedPill-Kernel MCP tools (`bunker_memory_api`,
  `swarm_orchestrator_api`) **in-process**, feeding results back until it answers.
- **Limits (the model and the machine set these):**
  - **≤ 8 tool calls** per run — a budget enforced across turns, also when the model
    emits several calls in one turn (returns "mala tarde" if exceeded). Every call of
    a turn runs, in order.
  - **8B @ Q4 reasoning:** reliable for **short, concrete, mechanical** chains
    (2–4 steps). Degrades on ambiguous, long, or multi-objective tasks — it may pick
    the wrong tool, malform args, or fail to stop. Keep tasks **narrow and explicit**
    (name the tool/command when you can).
  - **Context:** Granite is a hybrid SSM, so long transcripts are cheap (KV ≈
    0.15 MB/token, trained at 131k); **no compaction in v1**, so keep tool outputs
    concise. The loop cap keeps context bounded in practice.
  - **Tools are curated & small** (bash + 2 MCP parents). It is not a general agent.
  - **Bash sandbox = cwd + 60 s timeout only** — a real shell driven by an 8B. Assign
    read-only/inspection tasks by default; only allow mutations deliberately.
  - Gives up after **3 consecutive tool errors**. A malformed or truncated tool call
    (e.g. cut by `max_tokens`) is fed back as an error ("re-emit it complete") and
    counts toward that cap — tool-call markup is never returned as the answer.
  - **Reasoning is not executed:** tool calls are parsed only from the *answer*; a
    `<tool_call>` the model writes while musing inside `<think>…</think>` (or in an
    unclosed `<think>`) is ignored.
  - **Tool output is data, not instructions:** with a native template that has a
    `tool` role (Granite 4.2 → `<tool_response>`) results go back as `role="tool"`;
    with `chatml-function-calling` (no `tool` branch — it drops such messages) they go
    in a user turn fenced as `<tool_output id=nonce>…` and labelled untrusted. This
    blunts, but does not remove, prompt injection from files/Bünker content — keep
    tasks read-only.
  - **Conduct comes from the profiles:** `temperature`, `max_tokens` and `tool_format`
    are resolved in-process for the task `minion_tool` (candidate > task > model
    profile, fallback 0.3 / 1024 / `auto`); the daemon does not apply them itself. A
    daemon rejection (e.g. a `model` that is not a `minion_tool` candidate → K1, 400)
    surfaces as a readable `SipInferenceError`.
  - **Tool-calling routing (HARNESS-003/004, 2026-09-30):** the daemon MUST pick a
    tool-capable `chat_format` (`minion_chat_format`, e.g. `chatml-function-calling`)
    when the request carries tools — the distiller `chat_format` silently drops them
    (the model then answers in prose, or invents a tool and fabricates its output).
    Granite **4.2** uses its **native** template and emits the tool-call as *text*
    (`<tool_call><function=NAME><parameter=k>v</parameter></function></tool_call>`);
    the loop parses it (`model_runtime.extract_toolcalls`) and keeps `arguments` as a
    mapping. 4.2-**3B** works but needs ~1200 tokens of budget for its `think` — the
    `minion_tool` task/candidate `max_tokens` must cover it (seed: 2048).
  - **Autonomy (measured by `scripts/autonomy_ladder.py`):** Granite 4.1 and 4.2 both
    **mutate the filesystem without asking** under ambiguous / "clean up" prompts →
    grant **read-only inspection** autonomy only; keep mutations human-gated. 4.2
    chains better than 4.1 (multi-step) but is heavier.
- **Best for:** headless, unattended, well-scoped tasks — "count/inspect X", "read
  file Y and extract Z", "search the Bünker for W and summarize". Bit/frankenswarm-style
  chores of a few turns.

### External agentic (`claude` / `agy` / `opencode` / `pi`)
- **Can:** full multi-turn agent work — many tools, files, long context, real
  reasoning. The vendor CLI owns the agent loop; red-pill runs it headless with
  auto-approved permissions.
- **Limits / caveats:**
  - **`agy` needs the Antigravity IDE open** (it uses the IDE language server); if the
    IDE is closed the task will not run.
  - **`opencode`** works via the bridge factory but is **not yet listed** in the
    `run_agent_task` backend enum (you can still pass it). Uses OpenCode Zen models
    (e.g. free `big-pickle`) or a local endpoint.
  - **`pi`** (pi-coding-agent) runs headless (`pi --mode json`) on a provider/model
    configured in `~/.pi/agent/settings.json`. Pi has **no MCP**: the red-pill
    harness extension (`~/.pi/agent/extensions/red-pill.ts`) injects Búnker
    identity/RAG and relays the completed turn. Needs `pi` on the service
    manager's PATH (or `PI_BIN`).
  - **`claude`** uses cloud inference (capable but has cost/latency).
  - High per-invocation overhead (CLI + MCP server boot). Prefer `async_mode:true`.
- **Best for:** genuinely complex, multi-file, multi-tool tasks where the local 8B
  would flounder.

---

## 4. Orchestrator decision guide

```
Is there an LLM decision to make?
├─ No  → Simple minion (a script). (Internal primitive today.)
└─ Yes → Does the task need tools (read files / run commands / query memory)?
         ├─ No  → local one-shot (backend:"local"). Cheap, single turn.
         └─ Yes → How hard is it?
                  ├─ Short, concrete, few steps, headless, tolerant of retries
                  │    → run_local_minion (sovereign, free, in-process).  [§5: not MCP yet]
                  └─ Complex, multi-file, long, needs strong reasoning
                       → external agentic (claude; or opencode/agy/pi). async_mode:true.
```

**Golden rules for the orchestrator:**
- Prefer the **weakest sufficient** minion (cost/latency/blast-radius).
- Give the local tool-using minion **narrow, explicit** tasks; name the command/tool.
- Default local-minion bash tasks to **read-only** unless mutation is the point.
- Use **`async_mode:true`** + `check_minion_inbox` for anything that isn't a quick call.
- If a task needs `agy`, first confirm the IDE is open, else pick another backend.

---

## 5. Current gaps (state as of 2026-07-22)

> **Resueltos (v7.22, AD-030):** el enrutado de modelo por request ya existe (selector `experimental>custom>model>task>config>env`; `MINION_DEFAULT_PROFILE`). Snapshot fechado abajo.

- **No context compaction** in the local tool loop (bounded by the 8-call cap instead).
- Local endpoint model selection is fixed at daemon boot (`MINION_PROFILE`); the
  request `model` field is ignored (no per-request model routing yet).
- **`opencode` against the local SIP endpoint** is not yet working (ai-sdk streaming
  mismatch); `opencode` today drives its own hosted/Zen models.
- The dual-bind daemon is generated from a setup-script heredoc (un-linted, un-tested);
  see the ROADMAP item to promote it to a versioned source file.

See also: `swarm/bridges/` (bridge implementations & the cascade), `swarm/agents/local_minion.py`
(the in-house loop), `core/providers.py::SipInferenceProvider` (local inference client),
and the CPU-fallback worker isolation rationale in `docs/TECHNICAL/DECISION_LOG.md`.
