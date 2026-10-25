---
name: context-distiller
version: 3.0.0
description: >-
  Session handoff (v3). Writes the workspace cold-start snapshot to
  .red-pill/memory/session_snapshot.md (never .agent/), indexes it in MEMORY.md,
  and records a read-mark in an append-only ledger so a new session knows whether
  this snapshot version was already consumed. Use on "guarda el contexto /
  snapshot / handoff / cierra sesión", when context gets heavy, or before
  switching model/session.
---

# Context Distiller — session handoff (v3)

> Purpose: **not lose state across restarts/compaction**. A technical handoff,
> not a diary. It is the durable companion of the kernel's per-turn capture, the
> session mirror (B-01) and the desk's OPEN LOOPS digest.

## When it activates

- Context is getting heavy (near compaction/limits).
- The operator says *"guarda el contexto"*, *"snapshot"*, *"handoff"*, *"cierra sesión"*.
- Before switching model/session, or before a long pause.

## Output — two files, one source of truth

1. **Snapshot** (overwritten): `<ws>/.red-pill/memory/session_snapshot.md`
2. **Read ledger** (append-only): `<ws>/.red-pill/memory/session_snapshot.reads.jsonl`

**Never** write to `.agent/` (host-owned, read-only) or to project source trees.
Index the snapshot in `MEMORY.md` (`- @session_snapshot.md — <frontier>`); do
**not** index the ledger — it is operational state, like `bank_health.json`.

## Snapshot format

Start with YAML frontmatter (see `FRONTMATTER_TEMPLATE.md`): `type`, `status`,
`created`, `updated`, `author`, `project`; optional `id`, `related`, `tags`,
`superseded_by`. Then, tight and technical:

1. **Frontera actual** — the exact task in progress and the **next sub-step**.
2. **Decisiones y bloqueos** — open decisions (link their `decisions:` ledger),
   blockers, and what unblocks them.
3. **Estado en vuelo** — branch + worktree path + last commit, and jobs/DAGs
   launched (id + state).
4. **Decisiones técnicas** — table `Priority | Decision | Rationale | State`
   (only durable, non-obvious changes).
5. **Alias** (optional) — only if a term would be ambiguous to a cold reader.

**One snapshot per workspace.** No per-session snapshots, no accumulation.

## Read protocol (cold start / new session)

Before loading the body, ask the ledger. The helper hashes the snapshot and
tails the JSONL; it does **not** read the body:

```bash
python3 <skill_dir>/snapshot_read.py check \
  --originator "<provider>:<session_id>" [--continuity-id "<cid>"]
```

- `MISSING` → no snapshot; continue.
- `READ` → read the snapshot body.
- `SKIP_CANDIDATE` → this same originator already read **this exact version**
  (`snapshot_sha`). Skip only if the snapshot is still in your hot context (same
  session, no compaction). If in doubt, or after compaction/model switch,
  **read anyway**: the mark is advisory, never authoritative.

Then record the decision (append-only, atomic):

```bash
python3 <skill_dir>/snapshot_read.py mark \
  --originator "<provider>:<session_id>" [--continuity-id "<cid>"] \
  --action read   # or skipped
```

`snapshot_sha` pins the version: any edit to the snapshot invalidates previous
reads, so a regenerated snapshot is always re-read. Missing or unreadable ledger
→ fail open (read).

**Why a sidecar and not a mark inside the snapshot:** at the end it forces a
full read before you learn it was already consumed; at the top it forces a full
rewrite on every read and only tracks the last reader. The JSONL is cheap to
check (tail), append-only, and per-reader.

## Write protocol (regenerate)

1. Overwrite `session_snapshot.md` atomically (tmp + rename, or
   `write_workspace_memory`), with a fresh `updated`.
2. Mark it `superseded_by` if it replaces a named doc.
3. **Keep the ledger**: never delete or rewrite it.
4. Re-index in `MEMORY.md`.
5. Tell the operator how to resume (*"lee
   `.red-pill/memory/session_snapshot.md` y continúa"*), and update the desk item
   status so `STATE.md`/OPEN LOOPS reflect reality.

## Rules

- **Technical only, and honest.** No filler, no invented facts. If something is
  unknown, say so.
- **Point, don't copy.** Link to the artifact (RFC, shard, commit, note) instead
  of duplicating it; the snapshot is an index of state, not a copy of the world.
- **No identity handling here.** Never sanitize, hide, or rewrite the
  agent/operator identity; identity is config of the instance. No "silence
  protocol".
- **No secrets.** IDs only: `continuity_id`, `originator`, `session_id`, `job_id`;
  never tokens, credentials or payloads.
- **Regenerate, don't accumulate.** The history lives in the kernel (mirror,
  Memento, Qdrant), not in the snapshot.

## Legacy

An old snapshot in `.agent/rules/` belongs to the host workspace: **do not edit,
move or delete it**. Treat it as non-authoritative and point the operator there.
A snapshot without a ledger entry is simply unread.

## Interplay

- Kernel **OPEN LOOPS** digest counts pending decisions/blockers — the snapshot
  is the detail behind those counts.
- Desk **`STATE.md`** (`planner/tools/state.py`) is the desk's cold entry point.
- Per-turn capture and the session mirror already hold the raw history; the
  snapshot only answers *where am I / what's next / what's blocked*.
