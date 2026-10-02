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

## 4. Plans & RFCs — Desk-First (Critical)
- **Plans and design live in the desk, not the project repo**: `${AGENT_CORE_DIR}/planner/`
  (a *phase* is a *folder*: `ideas/` → `research/` → `design/` → `pending/` → `in_progress/`;
  `design/` is where the **RFCs** live, grouped by family).
- When the operator asks about a **plan / design / RFC**, look in the planner **FIRST** —
  before searching the workspace. A new RFC is born **and stays** in
  `${AGENT_CORE_DIR}/planner/design/<family>/` (frontmatter YAML; see `FRONTMATTER_TEMPLATE.md`).
- **Separation**: the desk references the project; the project **NEVER references the desk**
  (no `${AGENT_CORE_DIR}/...` paths, no desk RFCs inside the repo). When a design is
  implemented, its essence lives in the project's own docs (`DECISION_LOG` `AD-NNN`, repo docs).
- The repo may carry a **legacy** spec series (`docs/.../RFC_0NN`); it is **not** the plan/RFC
  home. Lifecycle: `draft → ratified → implemented → closed → archived`
  (if your desk carries `planner/design/governance/RFC_FLUJO_RFCS.md`, it details it).

</constraint>

