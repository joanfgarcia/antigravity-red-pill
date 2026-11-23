<constraint critical="true" level="2" name="knowledge_access">

## 1. Knowledge Access — Four Spaces
Do NOT mix them: *Identity/history* → **Bünker** (Qdrant RAG; recalled, not filed) | *Transversal notes* → **Agent_Core** (`${AGENT_CORE_DIR}`) | *Task artifacts* → **workspace-memory** (`<ws>/.red-pill/memory/`, never `.agent/`) | *Code structure* → **graphify** when the harness exposes it and the graph is fresh; otherwise `grep`/read, cheaper and exact.

## 2. Bünker-First Cognitive Rule (Critical)
Lacking context (session start, post-compaction, history/milestones)? Search the Bünker FIRST — `search_memory_research` under `bunker_memory_api` — BEFORE any local file search. Do not scan directories for what you can recall.

## 3. Tool Specs
workspace-memory goes through `bunker_memory_api`: `list_workspace_memory` / `read_workspace_memory` / `write_workspace_memory`.

## 4. Plans & RFCs — Desk-First (Critical)
- Plans and RFCs live in the desk planner, never in the project repo: `${AGENT_CORE_DIR}/planner/` (phase = folder: `ideas/` → `research/` → `design/` → `pending/` → `in_progress/`). Asked about a plan/design/RFC → look there FIRST. A new RFC is born and stays in `${AGENT_CORE_DIR}/planner/design/<family>/` (frontmatter: `FRONTMATTER_TEMPLATE.md`).
- The project NEVER references the desk (no desk paths or RFCs in the repo); once implemented, its essence lives in the project's docs (`DECISION_LOG` `AD-NNN`). A legacy `docs/.../RFC_0NN` series is not the plan home. Lifecycle: `draft → ratified → implemented → closed → archived` (if your desk carries `planner/design/governance/RFC_FLUJO_RFCS.md`, it details it).

</constraint>
