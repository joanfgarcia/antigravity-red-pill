# Antigravity IDE Plugin — Architecture & Design Decisions

> **Plugin**: `red_pill.plugins.antigravity_ide`  
> **Last updated**: 2026-05-26  
> **Authors**: Joan + Aleth (Opus 4.6 + Gemini Flash 3.5 via Telegram)

## 1. Purpose

This plugin is the **communication bridge** between the Red-Pill ecosystem and the Antigravity IDE. It enables:

1. **Prompt execution** — processing Telegram/Neon-Link messages by invoking the IDE's AI agent
2. **Conversation extraction** — pulling conversation histories for the Chronicle archival pipeline
3. **Autonomous AWAKENINGs** — background system maintenance tasks

## 2. Why Two Backends?

### The Ghost Cascade Problem (v1 — gRPC)

The original implementation (`ide_client.py`) used **gRPC-Web** to communicate with the IDE's LanguageServer. This worked for conversation extraction but had critical limitations for prompt execution:

| Problem | Impact |
|---------|--------|
| **Ghost cascades** | Each injected message created a visible tab in the IDE, polluting the workspace |
| **Approval gates** | `run_command` and MCP tools got stuck in `PENDING` status, waiting for manual approval that never came |
| **Async polling** | Response had to be polled via `check_for_replies()`, adding ~60s+ latency |
| **Context pollution** | The IDE operator saw phantom conversations from Telegram appearing in their session |

### The AgyBridge Solution (v2)

Google released the `agy` CLI (`antigravity-history`) which allows **headless, non-interactive** prompt execution. The key flag is `--dangerously-skip-permissions`, which auto-approves all tool calls (including `run_command` and MCP tools).

**Result**: Telegram messages are now processed in **14-21 seconds** with full tool access, no ghost cascades, and no approval gates.

### Architectural Decision: Coexistence

> **Decision**: Both backends coexist. They serve different purposes.

- `AgyBridge` → **Execution** (Telegram, AWAKENINGs, Neon-Link commands)
- `GrpcBridge` → **Extraction** (Chronicle pipeline, `archive_memories`)

The `GrpcBridge` is **NOT deprecated**. It remains the only way to call `GetAllCascadeTrajectories` and `GetCascadeTrajectorySteps` for the Chronicle ingestion pipeline.

## 3. Module Map

```
antigravity_ide/
├── __init__.py              # Public API exports
├── bridge.py                # IDEBridge ABC + dataclasses (BackendType, BridgeCapabilities, ConversationResult)
├── agy_bridge.py            # AgyBridge: execution via agy CLI
├── grpc_bridge.py           # GrpcBridge: extraction via gRPC-Web + legacy execution
├── factory.py               # create_bridge() / create_extraction_bridge() / preflight_check()
├── ide_client.py            # Low-level gRPC-Web client (AntigravityIDEClient)
├── worker.py                # IDEWorker: inbox → bridge → outbox orchestration
└── telegram_extractor.py    # TelegramResponseExtractor (gRPC response fallback)
```

## 4. AgyBridge — Multi-Turn Design

### The Accumulated Stdout Problem

`agy --conversation <uuid> -p "prompt"` **accumulates all previous responses** in stdout:

```
Turn 1: agy -p "say ALFA"         → stdout: "ALFA"
Turn 2: agy --conversation <uuid> → stdout: "ALFA\nBETA"  (not just "BETA")
Turn 3: agy --conversation <uuid> → stdout: "ALFA\nBETA\nGAMMA"
```

This was verified empirically on 2026-05-24. Without handling, each Telegram response would contain ALL previous responses concatenated.

### Solution: Dir-Diff UUID Capture + Prefix-Stripping

#### First message (new conversation):

```
1. Generate eid = uuid4()[:12]          ← ephemeral ID for safety
2. Snapshot brain_dir = ls(~/.gemini/antigravity-cli/brain/)
3. Execute: agy -p "prompt <!-- eid:abc123 -->" --dangerously-skip-permissions
4. Dir-diff: new_uuid = ls(brain_dir) - snapshot
5. If ambiguous (>1 new dir): verify eid in transcript.jsonl
6. Store in telegram_sessions: (user_id, uuid, accumulated_len=len(stdout))
7. Return full stdout as response
```

#### Subsequent messages (multi-turn):

```
1. Load from telegram_sessions: (uuid, previous_accumulated_len)
2. Execute: agy --conversation <uuid> -p "new prompt"
3. Prefix-strip: delta = stdout[previous_accumulated_len:]
4. Update accumulated_len in telegram_sessions
5. Return delta as response
```

### Why Not Use a Lock?

> **Decision**: No file lock (`flock`). The eid-based verification is sufficient.

Each invocation generates a **UUID4-based eid** embedded as an HTML comment in the prompt. This is:
- Invisible to the model (HTML comment)
- Persisted in `transcript.jsonl` for verification
- Collision-proof (UUID4 = 122 bits of entropy)

Even if two `agy` processes run concurrently (rare but possible with systemd timer overlap), each creates its own conversation directory and each has its own eid. The dir-diff gives us the UUID in 99% of cases; the eid scan handles the edge case.

### Why Not Parse `transcript.jsonl` Instead?

An earlier approach (by Gemini Flash 3.5, operating via Telegram) added `_find_active_log_path()` and `_get_planner_steps()` to parse the raw conversation log. This was **removed** because:

1. **Fragile**: relied on scanning ALL brain dirs for the most recently modified file
2. **Redundant**: prefix-stripping achieves the same result with zero I/O
3. **Race-prone**: the "most recently modified" heuristic could match wrong conversations

Prefix-stripping is deterministic, O(1), and requires no filesystem scanning.

## 5. Worker Architecture (IDEWorker)

### Dual-Path Routing

```
process_inbox()
    │
    ├── command == LIST_CASCADES  → gRPC (list IDE conversations)
    ├── command == SWITCH_CASCADE → gRPC (bind session to IDE tab)
    ├── command == NEW_CASCADE   → gRPC (create new IDE tab)
    │
    └── conversational message
         │
         ├── AgyBridge available (auto_approve=True)?
         │     └── _process_via_bridge()  ← v2 path (synchronous)
         │
         └── GrpcBridge fallback
               └── send_user_message() + check_for_replies()  ← v1 path (async poll)
```

### External Scribe Pattern

In the v1 flow, the agent saved interactions by calling `interceptor_rp` (the MCP tool). In the v2 flow, the worker itself acts as the "scribe":

```python
# Worker saves directly to bunker.db, decoupled from agent state
_scribe_relay(user_prompt, agent_response)
```

This is necessary because:
1. The `agy -p` agent runs in an ephemeral conversation — it has no persistent state
2. We can't rely on the agent calling `interceptor_rp` in a headless session
3. The worker already has the prompt and response — it can save them directly

### Session Tracking (telegram_sessions)

| cascade_type | Backend | Purpose |
|---|---|---|
| `interactive` | gRPC (v1) | Bind Telegram user to an IDE tab for message injection |
| `agy_session` | agy (v2) | Track conversation UUID + accumulated_len for multi-turn |
| `ghost` | gRPC (v1) | Auto-injected background minion reports |

## 6. Configuration

```env
# .env — ~/.config/red-pill/.env
IDE_BACKEND=auto    # auto | agy | grpc
```

| Value | Behavior |
|-------|----------|
| `auto` | Use `AgyBridge` if `agy` CLI is found in PATH, else `GrpcBridge` |
| `agy` | Force `AgyBridge` (fails if `agy` not installed) |
| `grpc` | Force `GrpcBridge` (legacy behavior) |

### CLI Management

```bash
red-pill ide backend         # Show current backend
red-pill ide backend agy     # Set backend
red-pill ide status          # Show capabilities and preflight
red-pill ide test            # Health check
```

## 7. Prerequisites

| Requirement | For |
|---|---|
| Antigravity IDE running | Both backends (LanguageServer process) |
| `agy` CLI >= 1.0 | AgyBridge execution |
| `agy` CLI >= 2.0 | Autonomous AWAKENINGs |
| `neon-link` >= 0.4.0 | Telegram message routing |

## 8. Known Limitations

1. **`agy --conversation` accumulates stdout** — handled by prefix-stripping, but if the model reformats a previous response slightly, the prefix won't match exactly. Fallback: return full accumulated response.

2. **No cross-session persistence** — `agy` conversations don't survive IDE restarts. After a restart, the next Telegram message creates a fresh conversation.

3. **Decoupled Telegram Commands**: Commands `/list`, `/new`, `/switch`, and `/delete` are fully supported under `AgyBridge` using local JSON session files (under `$XDG_DATA_HOME/red-pill/telegram_conversations/`) and SQLite mapping tracking. They no longer require active gRPC IDE tabs.

4. **Concurrent execution** — The systemd timer fires every ~60s. If a heavy `agy -p` execution takes >60s, the next timer fires while it's still running. The dir-diff + eid handles this correctly, but the timer should ideally be debounced.

## 9. Antigravity Python SDK Connection Audit & Viability Assessment

During the development of the v7.1.0 lifecycle hardening, we conducted a comprehensive structural audit of the `google.antigravity` Python SDK (`google-antigravity` package) to determine if it could replace the CLI-based `AgyBridge` or directly connect to a running IDE Language Server.

### Analysis & Structural Findings

1. **Tight Coupling to Subprocess Execution**:
   - `LocalConnectionStrategy` inside the SDK is hardcoded to spawn the `localharness` binary as a subprocess via `subprocess.Popen([self._binary_path])`.
   - The strategy is strictly configured to communicate with this subprocess via WebSocket on an ephemeral port (reading the port and generated API key from stdout).
   
2. **Absence of gRPC-Web Client Capabilities**:
   - The Python SDK contains **zero gRPC client code** or capabilities to query active IDE cascades. 
   - It cannot communicate with the gRPC-Web endpoints exposed by the IDE Language Server (`ANTIGRAVITY_LS_ADDRESS`).
   - Consequently, the SDK cannot replace `GrpcBridge` for the Chronicle ingestion pipeline.

3. **Auto-Approval / Permission Gates Overhead**:
   - Spawning the binary via `LocalConnectionStrategy` does not allow passing custom command-line flags (such as `--dangerously-skip-permissions`).
   - All tool execution permissions (like `run_command` or `edit_file`) are routed back to the Python SDK over the WebSocket as `tool_confirmation_request` packets.
   - While auto-approval can be achieved in Python by implementing a global `HookRunner` that returns `allow=True` for all tool calls, this introduces unnecessary roundtrip latency and Python execution overhead.

### Design Trade-Off Decision

Based on the architectural findings, the **CLI-based `AgyBridge` is finalized as the official execution backend** for the Bünker headless prompt runner:

| Metric | CLI-based `AgyBridge` (v2) | SDK-based `LocalConnection` |
|---|---|---|
| **Spawns Subprocess** | Yes (`agy` CLI) | Yes (`localharness` via Python Popen) |
| **Protocol** | CLI Stdout / Ephemeral | WebSocket Client + Proto Handshake |
| **Permissions Bypass** | Native (`--dangerously-skip-permissions`) | Custom Python Hook (`HookRunner`) |
| **IDE gRPC-Web Support** | None (requires GrpcBridge) | None (requires GrpcBridge) |
| **Complexity & Overhead** | Low (Stateless CLI execution) | High (WebSocket loop + daemon threads) |
| **Stability** | High | Medium (vulnerable to WS/D-Bus connection drops) |

**Conclusion**: The `AgyBridge` CLI execution pattern is structurally superior for headless Telegram and Neon-Link execution, while `GrpcBridge` remains the canonical bridge for IDE-driven Chronicle telemetry.

## 10. Historical Timeline

| Date | Event |
|---|---|
| 2026-05-02 | gRPC injection working (ghost cascades, async polling) |
| 2026-05-08 | `/list`, `/switch`, `/new` commands added |
| 2026-05-22 | Ghost cascade problem identified as structural |
| 2026-05-23 | `IDEBridge` ABC designed, `AgyBridge` + `GrpcBridge` implemented |
| 2026-05-23 | E2E Telegram test: `run_command` + MCP working via agy (14-21s) |
| 2026-05-23 | `agy --conversation` stdout accumulation discovered (scenario B) |
| 2026-05-24 | Dir-diff UUID capture + prefix-stripping implemented |
| 2026-05-24 | Antigravity Python SDK Connection Audit & Viability Assessment concluded |
| 2026-05-26 | Decoupled Telegram commands (/list, /new, /switch, /delete) to local disk sessions, compaction & Qdrant-verified Janitor sweep |
