# RFC-002: Sovereign Vault Chronicle

| Field | Value |
|---|---|
| **RFC** | 002 |
| **Title** | Sovereign Vault Chronicle |
| **Codename** | Project Vault |
| **Status** | DRAFT |
| **Author** | Joan García (Operator) / Aleth (Agent) |
| **Created** | 2026-08-20 |
| **Triggered by** | Design review of the raw-capture architecture (scribe_relay + chronicle) |
| **Related** | [RFC-001](./RFC_001_FIRMWARE_PROTECTION.md), [DECISION_LOG](../DECISION_LOG.md), [ROADMAP](../ROADMAP.md), [CHRONICLE_INGESTION_GUIDE](../../GUIDES/CHRONICLE_INGESTION_GUIDE.md) |

---

## 1. Motivation

### 1.1 The Problem: two recorders, one tape

Today the Bünker records *everything* twice, and both times into Qdrant vectors:

**Pipeline A — Scribe relay (`interaction_memories`)**

- Capture surfaces: Claude Code Stop hook (`seeds/settings/hooks/redpill_scribe.py`),
  the opencode `redpill-scribe.js` plugin, `_scribe_relay()` of the bridges
  (`src/red_pill/swarm/bridges/opencode.py:130`, `src/red_pill/plugins/antigravity_ide/worker.py:890`)
  and the MCP `memorize_interaction` (`src/red_pill/mcp_server.py:253`).
- Everything lands in `memory_queue` (SQLite) → `drain_memory_queue`
  (`src/red_pill/core/queue_worker.py:345`) → `record_interaction_pair`
  (`src/red_pill/memory.py:487`) → collection `interaction_memories`.
- The 03:00 Sleep cycle later consolidates that buffer into `work_memories`.

**Pipeline B — Chronicle (`archive_memories`)**

- `scripts/chronicle_daily.py` (04:00 timer) discovers source plugins
  (`src/red_pill/chronicle_sources/`), reads the native session stores
  (opencode.db SQLite, Claude Code JSONL, Antigravity exports), normalizes them,
  and archives them atomized into `archive_memories`
  (chronicle_node / monolith_parent / idea_fragment with sequential axon threading).
- The codebase itself already acknowledges the redundancy:
  `src/red_pill/metabolism/maintenance.py:644` notes that the raw verbatim
  interaction is already archived in `archive_memories`.

**Consequences:**

1. **Double vectorization cost.** The same conversation is embedded at least twice:
   once raw in `interaction_memories`, once atomized in `archive_memories`.
2. **Signal dilution.** Every turn — including tooling noise, failed attempts,
   small talk — competes semantically with the genuinely valuable engrams.
   The vector store's recall degrades as raw noise scales.
3. **No true "exact recall".** Semantic search finds the *vague* and loses the
   *detail*. There is no human-readable, navigable, greppable record of what was
   actually said.
4. **Two sources of truth.** If `archive_memories` and `interaction_memories`
   disagree about a session, there is no canonical copy to consult.

### 1.2 The Original Vision

At project start, engrams were **curated**: only the pieces the agent judged
consequential were stored. The automatic "recorder" (scribe → Qdrant) was a
later convenience, not a principled choice. The raw layer is better served by
cheap, lossless, human-readable storage than by vectors.

> *"Ahora mismo tenemos dos procesos que vuelcan todas nuestras conversaciones
> dentro... Al inicio del proyecto guardabas los engramas que creías convenientes
> en vez de que fuera una 'grabadora'. Hoy me planteo volver a esos inicios y que
> el chronicle sea un archivo en disco a lo Obsidian Vault... Quizá no será una
> búsqueda semántica como hacemos directamente en Qdrant, pero sería algo más
> híbrido."*
> — Joan (Operator), 2026-08-20

### 1.3 The Proposal in One Paragraph

Introduce a **Sovereign Vault**: a disk-based, markdown tree of all
conversations/sessions (per provider), written by the chronicle pipeline —
the "grabadora" becomes cheap, exact, and human-readable. Qdrant stops being a
firehose and returns to being a **curated memory**: only what the consolidation
(distill/refine) judges to be engram ascends to vectors. The boundary between
"raw" and "curated" is drawn at **consolidation time**, never at capture time.

---

## 2. Goals / Non-Goals

### 2.1 Goals

- G1. Every captured conversation lives on disk as a canonical, readable markdown
  file, grouped and linkable (tree + graph).
- G2. Capture cost becomes near-zero (no embedding at write time).
- G3. Qdrant holds only synthesized/consolidated engrams → better signal-to-noise.
- G4. Exact recall: any session can be read verbatim by path or full-text.
- G5. A migration path that re-processes **all** existing chronicle history from
  every provider, standardizes it, and populates the vault.
- G6. Hybrid search: semantic (Qdrant) + full-text/path (vault) as first-class,
  coexisting modes.

### 2.2 Non-Goals

- NG1. Not replacing Qdrant as the associative memory; only relieving it of raw bulk.
- NG2. Not building a new UI; Obsidian (or any md reader) can be pointed at the vault.
- NG3. Not changing the capture *surfaces* (hooks/bridges) — only their sink.
- NG4. Not a semantic store on disk; the vault is text, not embeddings.

---

## 3. Functional Requirements

### 3.1 MUST

1. **Vault renderer**: the chronicle pipeline writes every normalized message to a
   markdown file per session in the vault, regardless of provider.
2. **Canonical format**: a single markdown schema (frontmatter + body) for all sources,
   with normalized timestamps and role markers.
3. **Idempotency**: re-running a session render is deterministic (overwrite, no dupes),
   keyed by `(session_id, sequence_index, role)`.
4. **Migration command**: a mechanism to force-reprocess the full chronicle history
   of all enabled sources into the vault (`--all` equivalent).
5. **Backfill fallback**: if a source store is unavailable, the migration can
   reconstruct sessions from `archive_memories`.
6. **Zero capture overhead**: no embedding is produced for raw vault content.
7. **Config switch**: `VAULT_ROOT` configurable (default under `get_data_dir()`),
   and per-source enable/disable.
8. **No breakage during rollout**: existing Qdrant behavior must not change until
   a phase explicitly deprecates it.

### 3.2 SHOULD

9. **Search mode**: a vault search action in the MCP (full-text via ripgrep,
   scoped by source/month, returns paths + snippets).
10. **Graph links**: frontmatter carries `prev_session`/`next_session` (thread
    continuity), so Obsidian renders a conversation graph.
11. **Per-source and per-month indexes** generated automatically.
12. **Registry**: `vault_registry.json` mirrors `chronicle_daily_registry.json`
    so reruns are cheap and audits possible.
13. **Noise normalization** shared with the ingester (reuse `_refine_content`-style
    cleaning, moved to a common module).

### 3.3 MAY

14. **Git history**: vault optionally git-initialized for immutable history.
15. **Dual-write window**: scribe keeps writing to `interaction_memories` during a
    transition, then stops (see §6).
16. **Automatic curation gate**: distill/refine may auto-promote vault fragments to
    Qdrant engrams (importance threshold or LLM judgment).
17. **Narrative rollups**: monthly summary files (`<AAAA-MM>/_rollup.md`) distilled
    by Samantha.

---

## 4. Design

### 4.1 Layered Architecture

```
CAPTURE  (hooks / bridges / MCP)          →   memory_queue  (SQLite)
                        │
                        ▼
   ┌────────────────────────────────────────────────────────────┐
   │  CHRONICLE (04:00)                                          │
   │  discover_source_plugins → load() → normalize               │
   │        │                                        │           │
   │        ▼                                        ▼           │
   │   SOVEREIGN VAULT (disk)                   Qdrant raw sink │
   │   markdown tree + indexes               (deprecated later)  │
   └───────────────┬────────────────────────────────────────────┘
                   │  (only curated content)
                   ▼
   CONSOLIDATION (distill / refine / sleep)   →   work_memories / social_memories
                   │
                   ▼
   SEARCH   semantic (Qdrant)   +   exact/fulltext (vault)
```

- **Raw layer = vault (disk).** Cheap, lossless, greppable, human-readable.
- **Synthesis layer = Qdrant.** Only engrams that passed consolidation.
- **Decision point = consolidation.** The chronicle decides *what ascends*; the
  capture surfaces never decide (they are deliberately dumb).

### 4.2 Vault File Format

Session file: `<vault>/<layout>/<session>.md`

```markdown
---
session_id: opencode:abc-123
source: opencode
originator: opencode
created_at: 2026-08-20T04:00:00Z
updated_at: 2026-08-21T04:00:00Z
step_count: 47
message_count: 32
workspace: /home/joan/Documents/IA/sharing
prev_session: opencode:abc-122
next_session: opencode:abc-124
---

# opencode:abc-123

## 2026-08-20 14:03:12 — Usuario
<content>

## 2026-08-20 14:03:41 — Asistente
<content>
```

- Frontmatter keys follow a fixed schema so they can be indexed.
- Roles rendered as `Usuario` / `Asistente` (unified across providers).
- Timestamps normalized to ISO 8601.
- Body = the already-normalized messages from `ChronicleSourcePlugin.load()`
  (`[{role, content, timestamp}]`, e.g. `src/red_pill/chronicle_sources/opencode.py:61`).
- `prev/next_session` preserve the Ariadne thread that `archive_memories` already
  forges via `associations`.

### 4.3 Structural Decision: source-first vs month-first

Proposal under review:

- **A (operator's first instinct):** `<vault>/<source>/<AAAA-MM>/<session>.md`
- **B (timeline-first):** `<vault>/<AAAA-MM>/<source>/<session>.md`

| Criterion | A — source-first | B — month-first |
|---|---|---|
| "What did we do in May?" | glob across sources | one folder |
| "All opencode sessions" | one folder | glob across months |
| Obsidian daily-note metaphor | weak | natural |
| Month rollups / narrative | need cross-source aggregation | trivial per folder |
| Graph/thread continuity | same | same (via frontmatter) |
| Stable path per source when months grow | stable | renames every month |

**Recommendation: B (month-first), with generated indexes as mitigation.**

Rationale: the vault is a *chronicle* — its primary value is narrative/temporal.
A session is an event in time; the month is the natural container. The "all
sessions of a source" browsing is recovered with an auto-generated per-source
index (`<vault>/index/<source>.md`) that lists sessions chronologically, and the
frontmatter links keep the graph alive regardless of folder layout.

> This is an explicit decision point for the operator. If A is chosen, the only
> schema change is the path template; nothing else in this RFC depends on it.

### 4.4 Scribe Relay Evolution

- Phase 1: scribe continues exactly as today; the vault is purely additive.
- Phase 2 (optional): scribe writes the turn to the vault (append) *in addition*
  to the queue, so the vault is real-time, not only 04:00.
- Phase 3: `interaction_memories` is deprecated as a raw sink. The vault (via
  chronicle) is the raw layer; Sleep/consolidation reads from it instead of
  draining a Qdrant buffer.
- The MCP `memorize_interaction` anti-noise filter (`mcp_server.py:234`) is
  preserved and applied to the vault write.

### 4.5 Curation Gate

The chronicle's existing synthesis steps (`chronicle_distill.py` — Samantha,
`chronicle_refine.py`) already produce the "curated" signal. The change:
**ingesting into `archive_memories` / `work_memories` becomes the gated step**,
not the default. A node ascends to vectors when:

- it is marked important by the operator, or
- distill/refine assigns it significance above a threshold, or
- it is referenced by later sessions (reinforcement), or
- a monthly rollup distills it.

Everything else lives only in the vault.

### 4.6 Search

New first-class action `search_vault` in `bunker_memory_api`:

- `rg -l`/`rg -C` full-text over the vault, scoped by `source`, `month`, `workspace`.
- Returns `{path, snippet, session_id, source}`.
- Compose with `search_memory_research` for hybrid recall:
  semantic hits point to engrams; vault hits point to exact passages.

---

## 5. Migration Mechanism

Goal: reprocess **all** existing chronicle history from every provider,
standardize it, and dump it into the vault.

### 5.1 Sources of Truth (in priority order)

1. **Provider stores (canonical):** opencode.db SQLite, Claude Code JSONL,
   Antigravity exports — via the existing `ChronicleSourcePlugin.discover()/load()`.
   These are the rawest and most complete.
2. **`archive_memories` (fallback):** if a provider store is gone (e.g. old
   Antigravity exports), reconstruct sessions from the collection: points carry
   `session_id`, `sequence_index`, `role`, `refined_content`/`raw_content`.
   Order by `sequence_index` and render with the same schema.

### 5.2 Standardization

A single renderer (`vault_render.py`, shared module) converts any normalized
message list to the canonical markdown of §4.2. The cleaning logic currently
embedded in `antigravity_ingest.py` (`_refine_content`, ANSI/noise stripping)
is extracted into the shared module so the ingester and the vault renderer
produce byte-identical cleaned text.

### 5.3 Idempotency & Registry

- Vault filename = slug of `session_id` (deterministic). Reruns overwrite.
- `vault_registry.json` (next to `chronicle_daily_registry.json`) records
  `{source: {session_id: {rendered_at, message_count, step_count}}}`.
- The migration is safe to run repeatedly; only new/changed sessions are touched.

### 5.4 Execution

A new script `scripts/vault_migrate.py` (or a `--vault-only` mode of
`chronicle_daily.py`):

1. `--all`: force full reprocess of every session of every enabled source.
   (Default: delta, mirroring the chronicle registry.)
2. For each source: `discover()` → for each `cid`: `load(cid)` → render → write
   `<vault>/<AAAA-MM>/<source>/<session>.md` → update registry.
3. If `load()` fails for a source, attempt reconstruction from `archive_memories`.
4. Rebuild generated indexes (`<vault>/index/<source>.md`, `<vault>/<AAAA-MM>/_rollup.md`).
5. Dry-run mode (`--dry-run`) reports counts without writing.

---

## 6. Rollout Plan

| Phase | Scope | Behavior change | Risk |
|---|---|---|---|
| **0** | RFC review; decide §4.3 layout, §4.4 scribe fate, vault location | — | — |
| **1** | Vault renderer + `vault_migrate --all` backfill | None (additive) | Low |
| **2** | `search_vault` MCP action + index generation | None | Low |
| **3** | Scribe dual-write → redirect to vault; deprecate `interaction_memories` | Medium | Medium |
| **4** | Curation gate in chronicle: `archive_memories` ingest gated by significance | High (recall changes) | Medium/High |

Each phase is independently revertible. Phase 3 and 4 are the points of no
architectural return and should be approved explicitly by the operator.

---

## 7. Open Questions

1. **Layout**: A (source-first) or B (month-first)? This RFC recommends B.
2. **Vault location**: `~/.local/share/red-pill/vault/` (default) vs a git repo
   vs inside Agent_Core.
3. **Scribe fate**: does `interaction_memories` get deprecated (Phase 3) or stay
   as a short-term buffer?
4. **Curation threshold**: what defines "significant enough to ascend"? Operator
   flag, distill score, reference count, or a combination?
5. **Retention**: does the vault replace `archive_memories` entirely, or does
   `archive_memories` remain for the atomized/graph form?
6. **Workspace tagging**: should sessions carry their `workspace` so the vault
   can be browsed by project?
7. **Real-time vault**: does the scribe write to the vault live (Phase 2), or is
   the 04:00 batch enough?

---

## 8. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Migration re-ingests everything and hits timeout (the 29-jul lesson) | Delta by default; `--all` is explicit; seeded registry per source; throttled loop |
| Vault grows unbounded on disk | Markdown is tiny vs vectors; git optional; monthly folders make archiving trivial |
| Losing the graph/thread semantics that Qdrant associations provide | `prev/next_session` frontmatter + Obsidian graph view + generated indexes |
| Recall regression during Phase 4 | Semantic store keeps the consolidated engrams; vault fills the exact-recall gap; both compose in search |
| Double-writing during Phase 3 duplicates state | `memory_queue` content_hash dedup already exists; vault writes are idempotent |

---

## 9. Related Documentation

- [RFC-001: Firmware Partition Protection](./RFC_001_FIRMWARE_PROTECTION.md)
- [BUNKER_MANIFESTO](./BUNKER_MANIFESTO.md)
- [FERRARI_PROTOCOL](./FERRARI_PROTOCOL.md)
- [CHRONICLE_INGESTION_GUIDE](../../GUIDES/CHRONICLE_INGESTION_GUIDE.md)
- [DECISION_LOG](../DECISION_LOG.md)
- [ARCHITECTURE](../ARCHITECTURE.md)