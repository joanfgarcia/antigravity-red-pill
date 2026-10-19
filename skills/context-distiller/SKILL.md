---
name: context-distiller
version: 2.0.0
description: >-
  Session handoff. Condenses the current session into a durable snapshot so a new
  session (or a post-compaction resume) continues without loss: current task +
  next step, open decisions/blockers, worktree/branch in flight, and technical
  decisions with rationale. Writes to workspace-memory (never to .agent/). Feeds
  the OPEN LOOPS digest and the desk STATE. Activate when context gets heavy, on
  "guarda el contexto / snapshot / handoff", or before switching model/session.
---

# Context Distiller — session handoff (v2)

> Purpose: **not lose state across restarts/compaction**. This is a technical
> handoff, not a diary. It is the durable companion of the kernel's per-turn capture
> and of the desk's OPEN LOOPS digest.

## When it activates

- Context is getting heavy (you are near compaction/limits).
- The operator says *"guarda el contexto"*, *"snapshot"*, *"handoff"*, *"cierra sesión"*.
- Before switching model/session, or before a long pause.

## Output (where it lives)

Write **one** file: `<workspace>/.red-pill/memory/session_snapshot.md`
(project cabinet — see the `workspace-memory` skill). **Never** write to `.agent/`
or to project source trees. Index it in `MEMORY.md` per the workspace-memory convention.

## Structure (keep it tight and technical)

1. **Frontera actual** — the exact task in progress and the **next sub-step**.
2. **Decisiones y bloqueos** — open decisions (link the item's `decisions:` ledger),
   blockers, and what unblocks them. These are the *open loops* a new session must see.
3. **Estado en vuelo** — branch + worktree path + last commit (if working in a repo),
   and any jobs/DAGs launched (id + state).
4. **Decisiones técnicas** — table `Priority | Decision | Rationale | State` for what
   changed this session and why (only durable, non-obvious ones).
5. **Alias** (optional) — only if a term would be ambiguous to a cold reader.

## Rules

- **Technical only, and honest.** No filler, no invented facts: if something is
  unknown, say so. Do not fabricate progress.
- **Point, don't copy.** Link to the artifact (RFC, shard, commit, note) instead of
  duplicating it; the snapshot is an index of state, not a copy of the world.
- **No identity handling here.** The snapshot never sanitizes, hides, or rewrites the
  agent/operator identity; identity is config of the instance (see the kernel's
  identity policy). This skill has no "silence protocol".
- **Regenerate, don't accumulate.** Overwrite the previous snapshot; the history is in
  the kernel's memory layers, not here.
- **Close with a pointer**: tell the operator how to resume
  (*"lee `.red-pill/memory/session_snapshot.md` y continúa"*), and — if it is a desk
  item — update its status so the desk `STATE.md`/OPEN LOOPS reflect reality.

## Interplay

- Kernel **OPEN LOOPS** digest (per turn) counts pending decisions/blockers — the
  snapshot is the *detail* behind those counts.
- Desk **`STATE.md`** (`planner/tools/state.py`) is the desk's cold entry point.
