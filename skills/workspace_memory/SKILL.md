---
name: workspace_memory
description: Controls the local workspace-level memory filing cabinet, ensuring persistent technical context.
---

# Red Pill: Workspace Memory Skill

This Skill defines your inherent capability to manage and utilize the workspace-local memory filing cabinet, preserving technical context across compactions or new sessions.

## 🧠 1. Cognitive Guidelines (When to Use)
- **Awakening/Context Hydration**: Upon cold start or context compaction, look up your Current Working Directory (CWD) to determine the active workspace. Call `list_workspace_memory` and read `MEMORY.md` to recover project-specific status, architectural decisions, and tasks.
- **Decision Recording**: When you make a key technical decision (e.g. choosing a pattern, configuring a model, solving a bug), ensure it is memorized in Qdrant (`work_memories` collection) so it will automatically be projected into the workspace bank.
- **Trainee Handoff**: If you are working on a multi-phase task or fanning out subagents, write status updates to memory files under `<root>/.red-pill/memory/` so subsequent agents can read them.

## 🛠️ 2. MCP Tool Interface (RedPill-Kernel)
You interact with the workspace filing cabinet using actions registered under the `RedPill-Kernel` MCP server (specifically under `bunker_memory_api` and `swarm_orchestrator_api` parents):

- **List memory files**:
  `list_workspace_memory(workspace="<workspace_name>")`
- **Read a memory file**:
  `read_workspace_memory(workspace="<workspace_name>", filename="<file>")`
  *Examples: `read_workspace_memory(workspace="azrael", filename="MEMORY.md")`*
- **Write/Overwrite a memory file**:
  `write_workspace_memory(workspace="<workspace_name>", filename="<file>", content="<content>")`
- **Enable workspace memory**:
  `workspace_memory_enable(workspace="<workspace_name>", path="<optional_custom_path>")`
- **Disable workspace memory**:
  `workspace_memory_disable(workspace="<workspace_name>")`

## 🛡️ 3. Safety & Isolation Rules
- **No `.agent/` Intrusion**: NEVER modify, write, or delete files inside the workspace's `.agent/` folder. That folder belongs to the host workspace and is read-only.
- **Confinement**: All workspace-specific memory metadata and templates must reside strictly under `<ws_root>/.red-pill/` (specifically `<ws_root>/.red-pill/memory/`).
- **Atomic Operations**: When compacting or optimizing memory, write to `.tmp` files first, then use atomic replaces to prevent context deletion on failures.

## 🚀 4. CLI Administration
You can also run administrative operations from the command line:
- **Enable Memory**: `red-pill memory enable <ws_name_or_path> [--path <custom_path>]`
- **Disable Memory**: `red-pill memory disable <ws_name_or_path>`
- **Sync Memories**: `red-pill memory sync` (projects Qdrant engrams to `<ws>-decisions.md` immediately)
- **Consolidate (Compaction)**: `red-pill memory optimize` (compacts engrams via LLM immediately)
