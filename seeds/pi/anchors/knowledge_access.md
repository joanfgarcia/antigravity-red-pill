<constraint critical="true" level="2" name="knowledge_access">

## 1. Knowledge Access — Four Spaces
Do NOT mix them: *Identity/history* → **Bünker** (Qdrant RAG; collections `work`, `social`, `directive`, `story`, `interaction`) | *Transversal notes* → **Agent_Core** (`${AGENT_CORE_DIR}`) | *Task artifacts* → **workspace-memory** (`<ws>/.red-pill/memory/`, indexed in `MEMORY.md` with canonical `@refs`) | *Code structure* → skill **graphify**, loaded before grep/cat.

## 2. Bünker-First Cognitive Rule (Critical)
Lacking context (session start, post-compaction, history/milestones)? Search the Bünker FIRST with `bunker_search` BEFORE any local file search. Do not scan directories for what you can recall.

## 3. Tool Specs
- Bünker: `bunker_search` (read) / `bunker_save` (write); edit/erode/delete via `${RED_PILL_CMD} search|add|edit|erode` (skill `memory-manager`).
- workspace-memory: pi `read`/`write` on the markdown files (skill `workspace-memory`).
- graphify: `query_graph` / `get_neighbors` / `shortest_path`.

## 4. Plans & RFCs — Desk-First (Critical)
- Plans and RFCs live in the desk planner, never in the project repo: `${AGENT_CORE_DIR}/planner/` (phase = folder: `ideas/` → `research/` → `design/` → `pending/` → `in_progress/`). Asked about a plan/design/RFC → list and read it there FIRST (pi `bash`/`read`). A new RFC is born and stays in `${AGENT_CORE_DIR}/planner/design/<family>/` (frontmatter: `FRONTMATTER_TEMPLATE.md`), written with pi `write`.
- The project NEVER references the desk (no desk paths or RFCs in the repo); once implemented, its essence lives in the project's docs (`DECISION_LOG` `AD-NNN`). A legacy `docs/.../RFC_0NN` series is not the plan home. Lifecycle: `draft → ratified → implemented → closed → archived` (if your desk carries `planner/design/governance/RFC_FLUJO_RFCS.md`, it details it).

</constraint>
