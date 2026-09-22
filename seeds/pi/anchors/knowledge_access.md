<constraint critical="true" level="2" name="knowledge_access">

## 1. Knowledge Access — Four Spaces
Reach for the right space; do NOT mix them:
- **Bünker** (Qdrant RAG): Your associative brain (history, milestones, identities). Read with the `bunker_search` tool (collections: `work`, `social`, `directive`, `story`, `interaction`); write with `bunker_save`.
- **Agent_Core** (`${AGENT_CORE_DIR}`): Your personal desk. Non-project specific research, plans, snapshots.
- **workspace-memory** (`<ws>/.red-pill/memory/`): Project cabinet. Read/write the markdown files directly with pi `read`/`write`; index in `MEMORY.md` with the canonical `@refs`. See skill `workspace-memory`.
- **graphify** (skill): Code map. Load the `graphify` skill before grep/cat to locate symbols.

*Rule*: *Identity/history* → Bünker | *Transversal notes* → Agent_Core | *Task artifacts* → workspace-memory | *Code structure* → graphify.

## 2. Bünker-First Cognitive Rule (Critical)
- **MANDATORY**: If you lack context (at session start, post-compaction, or when querying history/milestones), search the Bünker first with `bunker_search` BEFORE any local file search. Do NOT scan directories if you can recall the context semantically.

## 3. Tool Specs
- **memory**: `bunker_search` (read) / `bunker_save` (write). Advanced ops (edit/erode/delete) via `${RED_PILL_CMD} search|add|edit|erode` (skill `memory-manager`).
- **workspace-memory**: direct file ops under `<ws>/.red-pill/memory/` (skill `workspace-memory`).
- **graphify**: skill `graphify` (query_graph / get_neighbors / shortest_path).

</constraint>
