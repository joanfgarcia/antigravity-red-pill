---
name: knowledge_access
description: Use when the session mentions knowledge access, four spaces, bünker rag, qdrant, graphify, workspace memory, memory research, bunker-first, or semantic search. This skill defines the four knowledge spaces and mandates Bünker-first cognitive rule before local file search.
---

## Knowledge Access — Four Spaces
Reach for the right space; do NOT mix them:
- **Bünker** (Qdrant RAG): Your associative brain (history, milestones, identities, memory context). Recalled, not filed.
- **Agent_Core** (`${AGENT_CORE_DIR}`): Your personal desk. Non-project specific research, plans, snapshots.
- **workspace-memory** (`<ws>/.red-pill/memory/`): Project cabinet. Artifacts of this task & local agent handoffs.
- **graphify** (MCP): Code map. Query before grep/cat to locate symbols.

*Rule*: *Identity/history* → Bünker | *Transversal notes* → Agent_Core | *Task artifacts* → workspace-memory | *Code structure* → graphify.

## Bünker-First Cognitive Rule (Critical)
- **MANDATORY**: If you lack context (at session start, post-compaction, or when querying history/milestones), you MUST search the Bünker first via `search_memory_research` (under `bunker_memory_api`) BEFORE performing any local file search (`grep_search`). Do NOT scan directories if you can recall the context semantically.

## Tool Specs
- **graphify**: Run `query_graph`, `get_neighbors`, or `shortest_path` before file reads.
- **workspace-memory** (via `bunker_memory_api`): `list_workspace_memory`, `read_workspace_memory`, `write_workspace_memory` to coordinate tasks/artifacts. Do not write to `.agent/` directly; use `.red-pill/memory/`.
