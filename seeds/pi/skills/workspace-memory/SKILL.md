---
name: workspace-memory
description: Controls the local workspace-level memory filing cabinet, ensuring persistent technical context. In Pi the bank is plain markdown under <ws>/.red-pill/memory/ read/written with the native read/write tools.
---

# Red Pill: Workspace Memory Skill (Pi)

This Skill defines your inherent capability to manage and utilize the workspace-local memory filing cabinet, preserving technical context across compactions or new sessions.

## 🧠 1. Cognitive Guidelines (When to Use)
- **Awakening/Context Hydration**: Upon cold start or context compaction, look up your Current Working Directory (CWD) to determine the active workspace. Read `<ws>/.red-pill/memory/MEMORY.md` with the `read` tool to recover project-specific status, architectural decisions, and tasks.
- **Decision Recording**: When you make a key technical decision (e.g. choosing a pattern, configuring a model, solving a bug), ensure it is memorized in Qdrant (`work_memories` collection) — tool `bunker_save` or `${RED_PILL_CMD} add work "..."` — so it will automatically be projected into the workspace bank.
- **Trainee Handoff**: If you are working on a multi-phase task or fanning out subagents, write status updates to memory files under `<root>/.red-pill/memory/` so subsequent agents can read them.

## 💧 1b. Session-Start Hydration (MANDATORY when CWD is a registered workspace)

The bank is useless if nobody reads it. At session start (and after compaction),
if your CWD falls inside a registered workspace (`~/.config/red-pill/workspaces.yaml`):
1. `read` the index `<ws>/.red-pill/memory/MEMORY.md` (`@fichero.md` refs, canonical
   convention — decisión operador 2026-09-03).
2. `read` `<ws>/.red-pill/memory/bank_health.json` — if `thresholds_tripped` is
   non-empty, surface it: the bank needs attention (oversized file, broken refs)
   and semantic compaction is operator on-demand.
3. Anti-bloat: index + health ONLY. Read a bank file in full only when the task
   at hand requires it — never preemptively.
Skip silently (no calls) when CWD is outside every registered workspace.

## 📥 1c. Deposit + Index (write path — keeps `orphans` at zero)

When you produce a durable artifact inside a workspace (plan, review, audit,
decision log, remediation report): deposit it under `<ws>/.red-pill/memory/`
and index it in `MEMORY.md` with the canonical `@refs` convention (decisión
operador 2026-09-03) — one line, e.g. `- @REVIEW_2026-09-03_x.md — qué decide`.
Ephemeral notes, drafts and task scratch stay OUT of the bank. If you touch the
index, keep every entry as `@fichero.md`: markdown links are diagnosed as
`non_canonical_refs` by `scripts/bank_janitor.py` and never count as index.

## 🚨 1d. Pain Loop (`memory_bank_bloat_<ws>` — report, never auto-compact)

`scripts/bank_janitor.py` emits a `memory_bank_bloat_<ws>` pain signal to the
córtex when thresholds trip. When you see one active: read that workspace's
`bank_health.json`, report a one-line summary (biggest file, orphans, broken
refs) and offer the operator on-demand semantic compaction. NEVER auto-compact
(decisión operador 2026-09-03).

## 🛠️ 2. Interface (Pi — native file ops, NO MCP)

Pi has no MCP: the bank is plain markdown, so you operate on it directly.
- **List memory files**: `bash: ls <ws>/.red-pill/memory/`
- **Read a memory file**: `read <ws>/.red-pill/memory/<file>`
- **Write/Overwrite**: `write <ws>/.red-pill/memory/<file>` (tmp + rename for atomicity if you touch the index)
- **Enable/disable a workspace**: `${RED_PILL_CMD} memory enable|disable <ws_name_or_path> [--path <custom_path>]`

## 🛡️ 3. Safety & Isolation Rules
- **No `.agent/` Intrusion**: NEVER modify, write, or delete files inside the workspace's `.agent/` folder. That folder belongs to the host workspace and is read-only.
- **Confinement**: All workspace-specific memory metadata and templates must reside strictly under `<ws_root>/.red-pill/` (specifically `<ws_root>/.red-pill/memory/`).
- **Atomic Operations**: When compacting or optimizing memory, write to `.tmp` files first, then use atomic replaces to prevent context deletion on failures.

## 🚀 4. CLI Administration
- **Enable Memory**: `${RED_PILL_CMD} memory enable <ws_name_or_path> [--path <custom_path>]`
- **Disable Memory**: `${RED_PILL_CMD} memory disable <ws_name_or_path>`
- **Sync Memories**: `${RED_PILL_CMD} memory sync` (projects Qdrant engrams to `<ws>-decisions.md` immediately)
- **Consolidate (Compaction)**: `${RED_PILL_CMD} memory optimize` (compacts engrams via LLM immediately)
