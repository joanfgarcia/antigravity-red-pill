# `swarm/bridges` — Agent-Backend Abstraction

Generic way to "run a prompt through an agent", independent of which backend
executes it. Extracted from `plugins/antigravity_ide` once it stopped being
Antigravity-specific (see DECISION_LOG **AD-016**).

## Interface
- **`AgentBridge`** (`base.py`, ex-`IDEBridge`) — ABC: `prompt()`, `continue_conversation()`,
  `health_check()`, `get_capabilities()`. Extraction methods default to `NotSupportedError`
  (only `GrpcBridge` overrides them, for the Chronicle pipeline).
- **`BackendType`** — `agy | grpc | claude | local`.
- **`ConversationResult`**, **`BridgeCapabilities`** — result + capability dataclasses.

## Backends
| Backend | Where | What | Capabilities |
|---------|-------|------|--------------|
| `AgyBridge` | `plugins/antigravity_ide/agy_bridge.py` | `agy` CLI (Antigravity) | auto-approve, resume, mcp_tools |
| `ClaudeBridge` | `bridges/claude.py` | `claude -p … --output-format json` | auto-approve, resume, model, mcp_tools |
| `LocalBridge` | `bridges/local.py` | local model via SIP provider | generation only (no mcp_tools/resume) |
| `GrpcBridge` | `plugins/antigravity_ide/grpc_bridge.py` | gRPC to LanguageServer | extraction (Chronicle) |

Antigravity-specific backends stay under `plugins/antigravity_ide` and import the
ABC from here. New backends are drop-in `AgentBridge` subclasses + a `BackendType` +
a route in `factory.create_bridge()`.

## Factory & selection
`create_bridge(backend=None)` — routes on the explicit `backend` arg or `config.IDE_BACKEND`
(`auto` → agy if present else grpc). `create_extraction_bridge()` → GrpcBridge.
`preflight_check()` → agy/IDE readiness.

## Consumers
`swarm/agents/agent.py:AgentMinion` (first-class minion, registered `"agent"` in
`MinionFactory`), `swarm/executor.py` (cognitive-queue executor), `plugins/antigravity_ide/worker.py`
(Telegram / AWAKENINGs), `cli.py` (`red-pill ide status|test`).
