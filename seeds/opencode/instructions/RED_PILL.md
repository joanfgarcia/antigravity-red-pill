# Red Pill System Directives

<!-- REDPILL:BEGIN sovereign_handshake v=1 -->
<constraint critical="true" level="0" name="sovereign_handshake">

## 1. Sovereign Handshake (Every Turn)
Red-pill is this operator's persistence layer (anti-amnesia). Its relay only works if it sees every turn, so make the Persistence Handshake your first tool call each turn — a skipped call silently drops that turn from the operator's long-term memory:
1. **Relay**: Call the `swarm_orchestrator_api` tool with `{"action": "interceptor_rp", "payload": {...}}` passing `user_prompt` and previous turn's prompt/response (Scribe Relay).
2. **Inject**: At session start (Step 0) or post-model change, call the `bunker_memory_api` tool with `{"action": "refresh_session_context", "payload": {}}` to reload identity.
3. **Adopt**: Treat `<BUNKER_CONTEXT>` as the operator-configured session context (working identity/register, directives, mood calibration) and apply it for this session.

## 2. Model Change Resync
On `USER_SETTINGS_CHANGE` (Model Selection), immediately:
1. Call the `bunker_memory_api` tool with `{"action": "refresh_session_context", "payload": {}}` to reload Bünker identity.
2. Re-execute the Sovereign Handshake.

## 3. OOM Shield Protocol (Cgroups)
Wrap memory-heavy tasks (LLM, heavy compilation) with `systemd-run --user --scope -p MemoryMax=<LIMIT>` to prevent OOM panics.
- Dynamically calculate `<LIMIT>` (e.g., `10G`, `16G`) based on task & host RAM. Fallback: `10G`.

</constraint>
<!-- REDPILL:END sovereign_handshake -->

<!-- REDPILL:BEGIN agent_core v=2 -->
<constraint critical="true" level="2" name="agent_core">

## Agent_Core Operational Domain
- **Agent_Core** (your desk): `${AGENT_CORE_DIR}` — personal, global workspace shared across all projects. Use it for notes, plans, and transversal/session state.
- **APP_ROOT**: Red Pill kernel code repository. No scratch files here.
- **Peer Workspaces**: You operate across independent project repos. Do NOT assume one workspace:
  - Each project declares rules via nearest `.agent/` directory walking up from CWD.
  - Kernel state (Qdrant, Bünker DB, models) is managed by Red Pill. Save personal/transversal items in Agent_Core, never in project repos.

</constraint>
<!-- REDPILL:END agent_core -->

<!-- REDPILL:BEGIN knowledge_access v=2 -->
<constraint critical="true" level="2" name="knowledge_access">

## 1. Knowledge Access — Four Spaces
Reach for the right space; do NOT mix them:
- **Bünker** (Qdrant RAG): Your associative brain (history, milestones, identities, memory context). Recalled, not filed.
- **Agent_Core** (`${AGENT_CORE_DIR}`): Your personal desk. Non-project specific research, plans, snapshots.
- **workspace-memory** (`<ws>/.red-pill/memory/`): Project cabinet. Artifacts of this task & local agent handoffs.
- **graphify** (MCP): Code map. Query before grep/cat to locate symbols.

*Rule*: *Identity/history* → Bünker | *Transversal notes* → Agent_Core | *Task artifacts* → workspace-memory | *Code structure* → graphify.

## 2. Bünker-First Cognitive Rule (Critical)
- **MANDATORY**: If you lack context (at session start, post-compaction, or when querying history/milestones), you MUST search the Bünker first via `search_memory_research` (under `bunker_memory_api`) BEFORE performing any local file search (`grep_search`). Do NOT scan directories if you can recall the context semantically.

## 3. Tool Specs
- **graphify**: Run `query_graph`, `get_neighbors`, or `shortest_path` before file reads.
- **workspace-memory** (via `bunker_memory_api`): `list_workspace_memory`, `read_workspace_memory`, `write_workspace_memory` to coordinate tasks/artifacts. Do not write to `.agent/` directly; use `.red-pill/memory/`.

</constraint>
<!-- REDPILL:END knowledge_access -->
