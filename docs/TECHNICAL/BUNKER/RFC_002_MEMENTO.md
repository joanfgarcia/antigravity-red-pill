# RFC-002: Memento Chronicle

| Field | Value |
|---|---|
| **RFC** | 002 |
| **Title** | Memento Chronicle |
| **Codename** | Project Memento (formerly *Sovereign Vault* — renamed, see Naming Note) |
| **Status** | DRAFT |
| **Author** | Joan García (Operator) / Aleth (Agent) |
| **Created** | 2026-08-20 |
| **Revised** | 2026-08-21 — design review, 2 passes: TTL buffer, secret-scrub MUST, immutable month, shadow gate, `memory_queue` source, archive-only gate. 2026-08-22 — 3rd pass: layout DECIDED (B, `yyyy-mm`), agentic pass delineated (Distill→Refine as §4.5), hubs/reinforcement/forgetting confirmed unchanged. 2026-08-26 — 4th pass: per-session directory with `raw/`/`memento/`/`distill/`/`refine/`, `memento/index.md` always canonical, `distill`/`refine` schemas with line refs + cross-session refs, artifact exclusion, historical Memento-first migration. 2026-08-26 — 5th pass (audit-driven, see `REVIEW_2026-08-26_rfc002-vault-audit.md`): renamed **Memento**; Q2/Q6/Q7 RESOLVED; §4.4 re-founded on the real pre-heating implementation (scroll, not semantic) and intra-day continuity gap deferred (§4.4.1); Healer contract mapped to the real Janitor/`auto_heal_ritual` machinery; `prev/next_session` computed at render time; query-log claim corrected; config keys named (§4.8); NNN examples normalized to 3 digits; `raw/` excluded from git; session-dir slug rule; `memento_hash` normative; render/backfill execution decided; staged retirement of the current distill/refine scripts |
| **Triggered by** | Design review of the raw-capture architecture (scribe_relay + chronicle) |
| **Related** | [RFC-001](./RFC_001_FIRMWARE_PROTECTION.md), [DECISION_LOG](../DECISION_LOG.md), [ROADMAP](../ROADMAP.md), [CHRONICLE_INGESTION_GUIDE](../../GUIDES/CHRONICLE_INGESTION_GUIDE.md) |

> **Naming Note (2026-08-26).** This project was drafted as *Sovereign Vault*, but
> "Sovereign Vault" already designates the MLS cryptographic layer of red-pill:
> `src/red_pill/utils/vault.py` / `vault_crypto.py` carry the literal docstring
> *"Sovereign Vault Cryptography"*, their state files (`vault.seed`,
> `vault_group.state`, `vault_identity.state`) live in `get_config_dir()`, and
> [AD-009](../DECISION_LOG.md) plus the ROADMAP's pending *Sovereign Cryptographic
> Vault (Secrets Manager)* use the same term. To avoid the collision, this RFC's
> subject is named **Memento** (operator decision, 2026-08-26): exact records on
> disk — the polaroids — for a memory that forgets. All module, config, and
> artifact names derive from it (`memento_render.py`, `MEMENTO_ROOT`,
> `memento_registry.json`, `search_memento`). The Secrets Manager keeps its
> ROADMAP entry with a collision note to re-decide its own name when implemented.

---

## 1. Motivation

### 1.1 The Problem: two recorders, one tape

Today the Bünker records *everything* twice, and both times into Qdrant vectors:

**Pipeline A — Scribe relay (`interaction_memories`)**

- Capture surfaces: Claude Code Stop hook (`seeds/settings/hooks/redpill_scribe.py`),
  the opencode `redpill-scribe.js` plugin (`seeds/opencode/plugins/`), `_scribe_relay()`
  of the bridges (`src/red_pill/swarm/bridges/opencode.py:176`,
  `src/red_pill/plugins/antigravity_ide/worker.py:896`)
  and the MCP `memorize_interaction` (`src/red_pill/mcp_server.py:228`).
- Everything lands in `memory_queue` (SQLite) → `drain_memory_queue`
  (`src/red_pill/core/queue_worker.py:354`) → `record_interaction_pair`
  (`src/red_pill/memory.py:487`) → collection `interaction_memories`.
- The 03:00 Sleep cycle later consolidates that buffer into `work_memories`,
  deleting the processed points afterwards (`consolidation.py:516,521`) — the
  buffer self-drains; only failed points (`failed_ids`, kept permanently and
  excluded from later scrolls) and VRAM-deferred nights linger.

**Pipeline B — Chronicle (`archive_memories`)**

- The 04:00 timer no longer runs the script directly: `schedule_pulse.py:125-131`
  submits it as a job (`red-pill job submit --recipe configs/jobs/chronicle.yaml
  --singleton`, priority 7, `max_step_minutes: 60`), and the recipe runs
  `scripts/chronicle_daily.py`, which discovers source plugins
  (`src/red_pill/chronicle_sources/`), reads the native session stores
  (opencode.db SQLite, Claude Code JSONL, Antigravity exports), normalizes them,
  and archives them atomized into `archive_memories`
  (chronicle_node / monolith_parent / idea_fragment with sequential axon threading).
- The codebase itself already acknowledges the redundancy:
  `src/red_pill/metabolism/maintenance.py:644` notes that the raw verbatim
  interaction is already archived in `archive_memories`.

**Consequences:**

1. **Double vectorization cost.** The same conversation is embedded at least twice
   — once raw in `interaction_memories`, once atomized in `archive_memories` —
   and for long turns 2+N times: the ingester writes a `monolith_parent` plus N
   `idea_fragment` nodes, each embedded (`scripts/antigravity_ingest.py:185-221`).
2. **Signal dilution.** Every turn — including tooling noise, failed attempts,
   small talk — competes semantically with the genuinely valuable engrams.
   Precision (2nd pass): the two *permanent* copies are the `work_memories`
   chunks and the atomized archive nodes (`interaction_memories` is transient);
   both permanent layers scale with volume, so recall degrades all the same.
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

Introduce **Memento**: a disk-based, markdown tree of all
conversations/sessions (per provider), written by the chronicle pipeline —
the "grabadora" becomes cheap, exact, and human-readable. Qdrant stops being a
firehose and returns to being a **curated memory**: only what the consolidation
(distill/refine) judges to be engram ascends to vectors. The boundary between
"raw" and "curated" is drawn at **consolidation time**, never at capture time.
Memento is the carpaccio archive in the closet — if you need verbatim detail
it is there; synthetic memory (Qdrant) keeps only what is worth remembering.
Artifacts (PDFs, images, binary attachments) are not Memento content: they are
not memory, and Memento is already oversized as an intermediate before distillation.

---

## 2. Goals / Non-Goals

### 2.1 Goals

- G1. Every captured conversation lives on disk as a canonical, readable
  per-session directory (`raw/` + `memento/` + `distill/` + `refine/`), grouped
  and linkable (tree + graph). The canonical verbatim is always
  `memento/index.md`.
- G2. Capture cost becomes near-zero (no embedding at write time for Memento;
  the only residual embedding is the short-lived TTL buffer of §4.4, bounded
  to 2–3 days of operator turns).
- G3. Qdrant holds only synthesized/consolidated engrams → better signal-to-noise.
  Memento-first: the historical tree is populated first, Qdrant recreation is
  selective and operator/Aleth-approved.
- G4. Exact recall: any session can be read verbatim by path or full-text via
  `memento/index.md`. Scope stated honestly: "verbatim" means the *dialogue* as
  normalized by the source plugins (user/assistant text + tool inputs); tool
  results, reasoning, and binary artifacts (PDFs, images) are not captured —
  provider stores remain canonical for full traces. Memento is synthetic memory,
  not a database.
- G5. A migration path that re-processes **all** existing chronicle history from
  every provider (all IDEs/agents present on the machine), standardizes it, and
  populates the tree.
- G6. Hybrid search: semantic (Qdrant) + full-text/path (Memento) as first-class,
  coexisting modes, with line-level refs enabling Memento ↔ Qdrant navigation
  and cross-session refs (including cross-provider adversarial panels).

### 2.2 Non-Goals

- NG1. Not replacing Qdrant as the associative memory; only relieving it of raw bulk.
- NG2. Not building a new UI; Obsidian (or any md reader) can be pointed at the tree.
- NG3. Not changing the capture *surfaces* (hooks/bridges) — only their sink.
- NG4. Not a semantic store on disk; Memento is text, not embeddings.
- NG5. Not archiving binary artifacts; documents/images passed in prompts are not
  Memento content (they are not memory — the operator may have deleted them and
  forgetting them is not a defect).
- NG6. Not solving intra-day cross-session continuity (§4.4.1) — that is the
  next continuity refinement, deferred to its own RFC.

---

## 3. Functional Requirements

### 3.1 MUST

1. **Memento renderer**: the chronicle pipeline writes every normalized message to a
   per-session directory in the tree (`<memento>/<AAAA-MM>/<source>/<session>/`),
   regardless of provider. The canonical verbatim is always `memento/index.md`.
2. **Canonical format**: a single markdown schema (frontmatter + body) for all sources,
   with normalized timestamps and role markers, always at `memento/index.md`.
   `raw/` (if enabled) keeps the provider-native verbatim verbatim; `memento/` is
   the unified MD. Artifacts are excluded by definition.
3. **Idempotency**: re-running a session render is deterministic (overwrite, no dupes),
   keyed by `session_id`. Reruns overwrite `memento/index.md` and reconcile
   derived `memento/NNN-*.md` splits. The registry is keyed
   `{source: {session_id: …}}` and each entry records the session directory
   (see §5.3).
4. **Migration command**: a mechanism to force-reprocess the full chronicle history
   of all enabled sources into the tree (`--all` equivalent) — covering every
   IDE/agent with a `ChronicleSourcePlugin` present on the machine.
5. **Backfill fallback**: if a source store is unavailable, the migration can
   reconstruct sessions from `archive_memories`.
6. **Zero capture overhead**: no embedding is produced for raw Memento content
   (`raw/` and `memento/` are text only; `distill`/`refine` are LLM-derived but
   not embedded themselves — only their promoted engrams ascend to Qdrant).
7. **Config switch**: `MEMENTO_ROOT` configurable (default under `get_data_dir()`),
   and per-source enable/disable. Key names in §4.8.
8. **No breakage during rollout**: existing Qdrant behavior must not change until
   a phase explicitly deprecates it. Memento-first: historical tree population
   precedes any Qdrant recreation; Qdrant recreation is gated and Aleth-approved.
9. **Secret scrubbing**: the shared renderer applies a redaction pass (API keys,
   tokens, passwords, common credential shapes) to every message before it is
   written to `memento/`. Tool *inputs* are rendered into the tree (e.g. bash
   commands via `_render_tool_use`), so credentials typed in terminals WILL
   reach disk unless scrubbed. Git history (MAY 16) must not be enabled before
   this exists. `raw/` is exempt from scrubbing by design (provider-native
   verbatim) and is therefore **always excluded from git** (MAY 16).
10. **`memory_queue` chronicle source** (required before rollout Phase 3): turns
     whose only capture surface is the MCP `memorize_interaction` have no native
     provider store — without this source they never reach the tree, and once
     the TTL prunes the buffer their raw record is gone. The queue keeps every
     row (`completed` rows are never purged today — no `DELETE FROM memory_queue`
     exists in `src/`), so it doubles as the canonical store for that surface:
     group rows lacking a session by `originator` + day
     (`mcp:<originator>:<AAAA-MM-DD>`). Retention closes the loop: completed rows
     may be purged only after Memento has rendered them (purge mechanism: §4.4.2).

### 3.2 SHOULD

11. **Search mode**: a `search_memento` action in the MCP (full-text via ripgrep,
    scoped by source/month, returns paths + snippets).
12. **Graph links**: frontmatter carries `prev_session`/`next_session` (thread
    continuity), so Obsidian renders a conversation graph. These are **computed
    by the renderer at render time** — sessions of the same source ordered by
    the `created_at` of their first message. They cannot be copied from Qdrant:
    the live thread fields there are `prev/next_session_hub`, maintained only in
    `work_memories`/`social_memories` by consolidation
    (`consolidation.py:120-121,469-470,686-688`); in `archive_memories` they were
    written once by a one-off migration (`scripts/thread_weave_migrate.py:53-55`)
    and are not maintained by the ingest pipeline, and `traverse_thread` excludes
    that collection by enum (`mcp_server.py:462-465`). Memento's chain is
    therefore computed independently and becomes the authoritative session thread.
13. **Per-source and per-month indexes** generated automatically.
14. **Registry**: `memento_registry.json` mirrors `chronicle_daily_registry.json`
    so reruns are cheap and audits possible.
15. **Noise normalization** shared with the ingester (extract the
    `_refine_content` cleaning currently embedded in `ChronicleIngester`,
    `scripts/antigravity_ingest.py:60-75`, into a common module).

### 3.3 MAY

16. **Git history**: the tree optionally git-initialized for immutable history.
    Gated on MUST 9: immutable history makes any leaked secret permanent, so
    the scrubber lands first. When enabled, the initializer writes a
    `.gitignore` that excludes `*/raw/` (unscrubbed provider verbatim, MUST 9).
17. **Dual-write window**: superseded by the revised S3 (§4.4) — the scribe
    keeps writing to `interaction_memories` permanently; the collection is now a
    TTL'd buffer, so there is no "stop" event, only pruning.
18. **Automatic curation gate**: distill/refine may auto-promote Memento fragments to
    Qdrant engrams (importance threshold or LLM judgment).
19. **Narrative rollups**: monthly summary files (`<AAAA-MM>/_rollup.md`) distilled
    by Samantha.

---

## 4. Design

### 4.1 Layered Architecture

```
CAPTURE  (hooks / bridges / MCP)          →   memory_queue  (SQLite)
                        │
                        ▼
   ┌────────────────────────────────────────────────────────────┐
   │  CHRONICLE (04:00 job, chronicle.yaml)                      │
   │  discover_source_plugins → load() → normalize               │
   │        │                                        │           │
   │        ▼                                        ▼           │
   │   MEMENTO (disk)                           Qdrant raw sink │
   │   markdown tree + indexes               (gated in Phase 4)  │
   └───────────────┬────────────────────────────────────────────┘
                   │  (only curated content: distill→refine→gate)
                   ▼
   CONSOLIDATION (distill / refine / sleep)   →   work_memories / social_memories
                   │
                   ▼
   SEARCH   semantic (Qdrant)   +   exact/fulltext (memento/index.md)
```

- **Raw layer = Memento (disk).** Cheap, lossless, greppable, human-readable.
  Inside each session: `raw/` (optional provider verbatim) + `memento/` (unified MD).
- **Synthesis layer = Qdrant.** Only engrams that passed `distill`→`refine`→gate.
- **Decision point = consolidation.** The chronicle decides *what ascends*; the
  capture surfaces never decide (they are deliberately dumb). Memento is the
  carpaccio archive — Qdrant is synthetic memory.
- **Artifact policy:** binary attachments (PDFs, images, etc.) are not Memento
  content. Only `role: user|assistant` text + compact tool-input markers
  (`[TOOL: ...]`) are rendered. Forgetting an artifact is not a defect.

### 4.2 Session Directory — per-session `raw/` / `memento/` / `distill/` / `refine/`

Each session is a **directory**, not a single file:

```
<memento>/<AAAA-MM>/<source>/<session>/
  raw/                          # MAY: provider-native verbatim (optional, for forensics)
    raw.*                       # extension mirrors provider: .json / .jsonl / .md / .db-slice
  memento/
    index.md                    # MUST: canonical unified MD — always present, always complete
    001-titulo-seccion.md       # MAY: split views for dense sessions (derived from index.md)
    002-titulo-seccion.md
  distill/
    001-titulo.md
    002-titulo.md
  refine/
    001-titulo.md
    002-titulo.md
```

**Session directory name**: deterministic slug of `session_id` — lowercase,
every character outside `[a-z0-9._-]` (notably the `:` of `opencode:abc-123`)
replaced by `-` (→ `opencode-abc-123`). Legal-but-hostile characters never reach
the filesystem (sync tools, Windows, Obsidian). The real `session_id` lives in
the frontmatter and the registry maps `session_id → directory`.

#### `raw/` — provider verbatim (default **ON** — operator decision, 2026-08-26)

- **Status upgrade (5th pass follow-up).** Originally MAY/default-OFF forensics;
  the operator re-founded it: *the raw copy is the backup layer and the single
  backup point* — provider stores prune (empirically: claude_code/opencode
  retain ~5 weeks; antigravity exports rotate), so `raw/` is what makes the
  whole tree regenerable from itself, forever. `MEMENTO_RAW_ENABLED` defaults
  to `True` (§4.8).
- `raw/` stores the session verbatim **in the provider's native shape** —
  extension follows the source: `opencode` → `raw.json` (dump of the native
  `message`/`part` rows), `claude_code` → `raw.jsonl` (original JSONL copy),
  `antigravity` → `raw.json` (export copy; `copy2` preserves the mtime dating
  proxy). No cleaning beyond role filtering; **no secret scrubbing** (hence the
  git exclusion in MAY 16 / MUST 9). `raw/` itself is never the search target.
- `raw/meta.json` sidecar (`session_id`, `source`, `conversation_id`,
  `step_count`, `workspace`, `exported_at`) makes each copy self-contained: the
  tree can be regenerated without registry or provider stores.
- **Regeneration**: each source plugin implements `export_raw()`/`load_raw()`;
  `memento_migrate --from-raw` walks the `raw/meta.json` sidecars and re-renders
  the entire tree from the backups alone (verified byte-identical). Fallback
  priority everywhere: live provider store > `raw/` (verbatim) >
  `archive_memories` (refined, `reconstructed: true`).

#### `memento/index.md` — canonical unified MD (MUST)

Single source of truth for exact recall. Same schema for every provider:

```markdown
---
session_id: opencode:abc-123
source: opencode
originator: opencode
created_at: 2026-08-20T04:00:00Z
updated_at: 2026-08-21T04:00:00Z
step_count: 47
message_count: 32
workspace: <workspace-root>
prev_session: opencode:abc-122
next_session: opencode:abc-124
reconstructed: false
---

# opencode:abc-123

## Secciones
- 001 — Objetivo y contexto (l12) → [[001-objetivo-y-contexto]]
- 002 — Panel adversarial Qwen vs Hermes (l340) → [[002-panel-adversarial-qwen-vs-hermes]]

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
- `prev/next_session` are computed at render time (SHOULD 12) — first-message
  `created_at` ordering per source. Both keys are **always present** (`null`
  when there is no neighbor): the frontmatter keeps a fixed line count, so
  thread updates replace lines in place and never shift the body's line refs
  (nor, therefore, the `memento_hash` anchoring §4.5.1).
- `reconstructed: true` (frontmatter) marks sessions rebuilt from
  `archive_memories` (§5.1.2): their body is *refined* text, not verbatim — the
  flag keeps G4 honest about which files are literal transcripts.
- `memento/index.md` is **always complete**. Split views (`memento/NNN-*.md`) are
  derived projections for dense-session navigation, never the canonical copy.
  `distill`/`refine` and `search_memento` target `memento/index.md` line ranges
  for stable refs. `rg` over the tree should target `memento/index.md` files.
- The `## Secciones` TOC appears only when splits exist; one line per section:
  `- NNN — <título> (l<start>) → [[NNN-slug]]`.

#### `memento/NNN-*.md` — split views for dense sessions (MAY)

- Created only when a session exceeds the split threshold
  (`MEMENTO_SPLIT_MAX_MESSAGES` / `MEMENTO_SPLIT_MAX_CHARS`, §4.8 —
  **provisional values pending the calibration cata of Q8**). Each file is
  `memento/<NNN>-<slug>.md` (`NNN` = `001–999`, same convention as
  distill/refine) — a slice of `memento/index.md` with a header
  `> [!ref] memento/index.md#l120-340` and the same `## TIMESTAMP — Role` blocks.
- For light sessions no split files are created — `index.md` alone is the session.

#### General rules

- No binary artifacts are rendered in `memento/` (NG5). Only dialogue text +
  compact `[TOOL: ...]` markers.
- All `memento/` content passes the shared scrubber + noise normalization
  (`memento_render.py` shared module, §5.2) — `raw/` is provider-native and
  format-agnostic, not a scrubbed MD (and never committed to git).

### 4.3 Structural Decision: source-first vs month-first — **DECIDED**

**Decision (operator, 2026-08-22): B — month-first, `yyyy-mm` granularity.**

- **B (timeline-first, chosen):** `<memento>/<AAAA-MM>/<source>/<session>/memento/index.md`
  with sibling `raw/`, `distill/`, `refine/` subdirectories (see §4.2).

| Criterion | A — source-first | B — month-first |
|---|---|---|
| "What did we do in May?" | glob across sources | one folder |
| "All opencode sessions" | one folder | glob across months |
| Obsidian daily-note metaphor | weak | natural |
| Month rollups / narrative | need cross-source aggregation | trivial per folder |
| Graph/thread continuity | same | same (via frontmatter) |
| Path stability | stable | stable — month pinned to first-message `created_at` (see below) |

Rationale: Memento is a *chronicle* — its primary value is narrative/temporal.
A session is an event in time; the month is the natural container. The "all
sessions of a source" browsing is recovered with an auto-generated per-source
index (`<memento>/index/<source>.md`) that lists sessions chronologically, and the
frontmatter links keep the graph alive regardless of folder layout.

Day-level granularity (`yyyy-mm-dd`) was considered and **rejected**: splitting
by day would fragment sessions that cross midnight, and the month boundary
already demands the same immutability rule below — so day granularity only
adds fragmentation without solving anything.

**Path immutability rule (either layout):** the `<AAAA-MM>` segment derives from
the `created_at` of the session's *first* message — never from `updated_at` or
the last message. A session spanning a month boundary stays in the month of its
first message; it must not change path between reruns; otherwise §5.3
idempotency breaks, the registry sees a new file, and Obsidian links rot.
Applies to the session directory `<memento>/<AAAA-MM>/<source>/<session>/`; all
inner paths (`raw/`, `memento/index.md`, etc.) move together.

### 4.4 Scribe Relay Evolution

Steps are named S1–S3: scribe-evolution steps, not the §6 rollout phases.

- S1: scribe continues exactly as today; Memento is purely additive.
- S2 (optional): scribe writes the turn to the tree (append) *in addition*
  to the queue, so Memento is real-time, not only 04:00.
- S3 (revised 2026-08-26, 5th pass): `interaction_memories` is **not**
  deprecated — it stays as the rolling short-term buffer it already *almost*
  is: Sleep deletes processed points after consolidation
  (`consolidation.py:516,521`), so the collection self-drains nightly. The only
  new mechanism is a **TTL backstop of 72h** for what the drain leaves behind
  (failed points in `failed_ids` — which today stay *permanently* and are
  excluded from later scrolls via `must_not HasIdCondition`,
  `consolidation.py:262,525-527` — and VRAM-deferred nights).
  **Honest grounds (corrected in the 5th pass):** the pre-heating interceptor
  (`src/red_pill/interceptors/11_pre_heating.py`) does **not** query this
  collection semantically. Block 1 (`:96-107`) is a `client.scroll()` with a
  payload time filter (`created_at >= now - lookback`) and `limit=5`; the
  tier-2 recent-work fallback (`:232-249`) is also a `scroll`, `limit=3`, with a
  **hardcoded 48h cutoff** that ignores `PRE_HEATING_LOOKBACK_HOURS`
  (`config.py:686`). A time-ordered scroll *could* in principle be served from
  disk — the reason to keep the buffer is **simplicity**: the interceptor works,
  is hot-path, and rewriting its data source is out of scope (NG3 spirit).
  Constraint: `INTERACTION_MEMORIES_TTL_HOURS (72) > max(PRE_HEATING_LOOKBACK_HOURS
  = 48, the hardcoded 48h of :234)`; whenever that hardcode is next touched it
  must be aligned to the config so the constraint has a single source of truth.
  **TTL mechanism (decided):** a `JanitorPlugin` (`interaction_ttl`) that
  scroll-deletes points with `created_at` older than the TTL —
  `interaction_memories` is deliberately *not* added to
  `METABOLISM_AUTO_COLLECTIONS` (`config.py:444`): the erosion machinery is
  engram lifecycle (FSRS/Lazarus), the wrong tool for a plain age purge.
  Sleep (`consolidation.py:142`) and pre-heating stay untouched. Durable raw
  storage is Memento; Qdrant keeps only the hot window.
- The MCP `memorize_interaction` anti-noise filter (`mcp_server.py:233-246`:
  role gate, system-noise markers, ping payloads) is preserved and applied to
  the Memento write.

#### 4.4.1 Deferred: intra-day cross-session continuity (NG6)

Design review, 2026-08-26 (operator): the pre-heating window — with or without
this RFC — only gives a new session "hasta ayer": what Sleep consolidated. Two
sessions opened 2–3 hours apart share **nothing** of each other; the raw rows
in `interaction_memories` do not help because they are untreated, and parallel
autonomous sessions are equally invisible to each other. This is a real gap and
the **next continuity refinement**, but it is *another sack of flour*: it needs
its own design (live cross-session digest? shared working-set? scribe-time
synthesis?) and will be addressed in a dedicated RFC. This RFC neither fixes
nor worsens it (NG6); the TTL buffer decision above is compatible with any
future answer.

#### 4.4.2 `memory_queue` retention (closes MUST 10)

A second `JanitorPlugin` (`queue_purge_rendered`) deletes `completed` rows whose
session (or `mcp:<originator>:<day>` group) is present in
`memento_registry.json` and older than a safety margin (e.g. 7 days). Today
nothing deletes queue rows; this plugin is what finally caps the queue's
unbounded growth, and its Memento-registry precondition is what makes the purge
safe.

### 4.5 The Agentic Pass: Distill → Refine

Between the mechanical Memento write (§4.1) and the curation gate lives the
**agentic pass** — two stages that today operate on Qdrant engrams and are
**rewritten** (not merely re-targeted — see below) to operate on the Memento
files. Input is always `memento/index.md` (and its optional `memento/NNN-*.md`
splits for context); line refs always point to `memento/index.md`.

1. **`chronicle_distill` (segmentation + structured sectioning).** Reads
   `memento/index.md` and splits it into **sections** (a session may cover
   disparate topics — not ideal but common). Each section becomes
   `distill/<NNN>-<slug>.md` (`NNN` = `001–999`, zero-padded; `slug` =
   lowercase, hyphen, ascii, `≤40ch` derived from `title`) with frontmatter:

   ```yaml
   ---
   session_id: opencode:abc-123
   source: opencode
   section: 1
   title: "Panel adversarial Qwen vs Hermes — árbol de decisión Memento"
   summary: "Resumen ≤10 líneas de lo tratado en la sección."
   keywords: [memento, distill, panel adversarial, qwen, hermes]
   source_lines: memento/index.md#l120-340
   source_ref: memento/index.md
   ---
   ```

   Body: `summary` (≤10 lines) + bullet of key points. The job is *structured
   filtration*: produce navigable sections with `title` + `summary` + `keywords`
   + `source_lines` refs to the canonical `memento/index.md`. It drops the
   uninteresting bulk — tool-use detail, routine agent plumbing — unless a
   specific fragment is genuinely notable. Internal agent reasoning is kept
   only when it is *actually interesting* (a decision, an insight).

2. **`chronicle_refine` (selection + texture + cross-refs).** Reads `distill/*.md`
   (not `memento/` directly) and selects which sections carry durable value. For
   each surviving section it writes `refine/<NNN>-<slug>.md` (same `NNN`/`slug`
   convention as distill):

   ```yaml
   ---
   session_id: opencode:abc-123
   source: opencode
   distill_ref: distill/001-titulo.md
   source_lines: memento/index.md#l120-340
   significance: 0.87
   emotion: cyan
   intensity: 0.72
   texture: {theme: memento_architecture, relics: ["carpaccio archive", "synthetic memory"]}
   cross_refs: ["claude_code:xyz-789", "opencode:def-456"]
   ---
   ```

   Body: curated summary + `texture` (theme classification, emotional charge,
   relics) + `cross_refs` to related sessions — including **cross-provider**
   refs when an adversarial panel spans multiple agents/models/IDEs.
   **`cross_refs` discovery (defined, 5th pass):** mechanical candidates first —
   sessions of any source whose active window overlaps in time (same day,
   overlapping first/last `created_at`) and/or share `workspace` — offered to
   the refine LLM in the prompt; the model keeps only the ones that are truly
   about the same thread of work. No semantic search is involved (NG4); the
   candidate set is computed from the registry alone.

   The extraction *spirit* matches what `scripts/chronicle_distill.py`
   (Samantha, `set_payload` over `archive_memories`) and
   `scripts/chronicle_refine.py` do today, but those scripts mutate Qdrant
   payloads and `chronicle_refine.py` is a full-collection sweep without an
   incremental cursor — the file-based versions are **new implementations**,
   per-session and idempotent. Every `refine/` file carries `source_lines` +
   `distill_ref` so Aleth or the operator in Obsidian can navigate
   memento → distill → refine → Qdrant engram without losing provenance.

   **Fate of the current scripts (staged):** the Qdrant-targeting
   `chronicle_distill.py`/`chronicle_refine.py` keep running unchanged through
   Phase 3.5 (they feed today's pipeline and the shadow-gate measurement); the
   file-based versions land with Phase 3.5; the old ones retire in Phase 4
   together with the ungated ingest.

The output of the agentic pass is the input to the curation gate (§4.6): a
section becomes a candidate engram only after distill+refine have judged it.
`refine/` is the gate input; `distill/` is the structured intermediate that
makes `refine` and navigation possible.

### 4.5.1 Slug & Invalidation Contract

- **Slug:** `NNN` = `001–999` zero-padded (exagerado pero gratis), `slug` =
  `lowercase, hyphen, ascii, ≤40ch` from `title`. Deterministic ordering by
  `NNN`; reruns preserve `NNN` for identical section order.
- **`memento_hash` (normative):** `sha256` of the `memento/index.md` **body**
  (everything after the closing frontmatter delimiter), stored in
  `memento_registry.json`. Frontmatter is excluded so an `updated_at` touch
  alone does not invalidate derived layers.
- **Invalidation:** if `memento/index.md` changes (`message_count`/`step_count`/
  `memento_hash` differs from the registry), the session's `distill/` and
  `refine/` are **fully regenerated** (not patched) — stale `source_lines`
  would otherwise point to wrong ranges.
- **Detection & cure (mapped to the real machinery, 5th pass):** a new
  `JanitorPlugin` (pattern: `src/red_pill/swarm/agents/janitor_plugins/base.py`;
  precedent emitter: `queue_hygiene.py:42-49`) compares registry hashes and
  emits a pain signal via `MemoryManager.inject_signal()` (`memory.py:1309`,
  collection `signal_memories`; signal names are free-form by convention):
  `memento_stale_distill` / `memento_stale_refine`, with the session dir in
  `message`. The cure follows the **`knowledge_graph_stale` precedent**
  (`src/red_pill/rituals.py:500-516`): a new branch in `auto_heal_ritual`
  re-runs distill→refine for the flagged session and evaporates the signal on
  success (`evaporate_signals`, `memory.py:1393`). If a regeneration is too
  long for the vigil ritual, the branch may submit it as a job instead of
  running inline — but the contract (signal in, regeneration, evaporation) is
  the ritual's.

### 4.6 Curation Gate

The chronicle's agentic pass produces the "curated" signal. The change:
**ingesting into `archive_memories` becomes the gated step**, not the default.
Scope (2nd pass): the gate applies to the chronicle→archive path **only** —
`work_memories` is fed by Sleep and already has its own curation stack
(Samantha distillation, Lazarus erosion, tool-noise compaction, orphan GC);
gating it would duplicate machinery and touch the Sleep engine for no signal
gain. A node ascends to vectors when:

- it is marked important by the operator, or
- distill/refine assigns it significance above a threshold, or
- it is referenced by later sessions (reinforcement), or
- a monthly rollup distills it.

Everything else lives only in Memento.

**Shadow mode first (Phase 3.5).** The gate's criteria are unproven —
"referenced by later sessions" requires reference tracking that does not exist
yet. Before enforcing, the chronicle runs the gate log-only for several weeks:
it computes the would-be decision, stamps `significance` into Memento frontmatter
and counts it in the registry, while still ingesting everything. Recall impact
is then measured by replaying real `search_memory_research` queries against
gated vs ungated sets. Phase 4 flips the switch only on that evidence.

**Prerequisite (corrected, 5th pass):** a query log *does* exist today, but only
as an ephemeral line: `registry.py:125` emits `ACTION_START` with the full
`args` (query included) for every nested action, and the default `sentinel`
provider just `logger.info`s it (`telemetry.py:165-167`) — no persistence, no
queryable store, no results captured. Phase 1 therefore **persists** it rather
than instrumenting from scratch: the cheap route is a sink for that existing
`ACTION_START` event (query text + timestamp, JSONL or SQLite next to the other
kernel state), so the Phase 3.5 replay has a real corpus to draw from.

**Hub formation & reinforcement/forgetting engines — unchanged.** Once a
fragment ascends to Qdrant, the downstream lifecycle stays exactly as it is
today: hubs assemble from related engrams in later phases, and the
reinforcement/forgetting engines (FSRS stability, Lazarus erosion,
reinforcement via re-recall) keep operating on the Qdrant collections
unchanged. This RFC does not touch that machinery; it only changes *what*
enters it.

### 4.7 Search

New first-class action `search_memento` in `bunker_memory_api`:

- `rg -l`/`rg -C` full-text over the tree, scoped by `source`, `month`, `workspace`.
  Canonical target is `memento/index.md` (split `memento/NNN-*.md` are derivates;
  `raw/` is excluded from default search). `distill/` and `refine/` are
  searchable as secondary scopes for structured recall.
- Returns `{path, snippet, session_id, source, source_lines}` — `path` points to
  `memento/index.md` (or `refine/*.md`), `source_lines` enables click-through
  navigation memento ↔ distill ↔ refine.
- Cross-provider refs from `refine/cross_refs` enable graph traversal
  (e.g. adversarial panel spanning opencode + claude_code).
- Compose with `search_memory_research` for hybrid recall:
  semantic hits point to engrams; Memento hits point to exact passages in
  `memento/index.md`.

### 4.8 Configuration (named keys)

| Key | Default | Meaning |
|---|---|---|
| `MEMENTO_ROOT` | `get_data_dir() / "memento"` → `~/.local/share/red-pill/memento/` | Tree root — operator-overridable (Q2 RESOLVED). Obsidian browsing via symlink if desired |
| `MEMENTO_SOURCES` | `CHRONICLE_ARCHIVE_SOURCES` (`config.py:448`) | Per-source enable/disable; defaults to the chronicle's own list so the two never silently diverge |
| `MEMENTO_RAW_ENABLED` | `True` (operator, 2026-08-26) | Write `raw/` provider verbatim + `meta.json` — the backup layer / single backup point (unscrubbed; never in git) |
| `MEMENTO_SPLIT_MAX_MESSAGES` | `30` **(provisional — Q8, pending cata)** | Split-view threshold, messages |
| `MEMENTO_SPLIT_MAX_CHARS` | `24000` **(provisional — Q8, pending cata; the 4th-pass 8k figure would split nearly every real session)** | Split-view threshold, chars |
| `INTERACTION_MEMORIES_TTL_HOURS` | `72` | §4.4 backstop; must stay `> max(PRE_HEATING_LOOKBACK_HOURS, hardcoded 48h of 11_pre_heating.py:234)` |

All new keys live in `Settings` (`config.py`) like everything else; none exist
today (`VAULT_ROOT` never existed either — the namespace is born with this RFC).

---

## 5. Migration Mechanism

Goal: reprocess **all** existing chronicle history from every provider,
standardize it, and dump it into the tree. Current census
(`chronicle_daily_registry.json`, 2026-08-26): 316 sessions — antigravity 109,
claude_code 34, opencode 142.

### 5.1 Sources of Truth (in priority order)

1. **Provider stores (canonical):** opencode.db SQLite, Claude Code JSONL,
   Antigravity exports — via the existing `ChronicleSourcePlugin.discover()/load()` —
   plus the `memory_queue` SQLite for MCP-only turns (MUST 10).
   These are the rawest and most complete.
1.5. **`raw/` backups (verbatim):** once exported, each session's `raw/` copy
   outlives the provider store's retention window — `load_raw()` re-renders
   verbatim without the store (`--from-raw` regenerates the whole tree).
2. **`archive_memories` (fallback):** if a provider store is gone (e.g. old
   Antigravity exports), reconstruct sessions from the collection: points carry
   `session_id`, `sequence_index`, `role`, `refined_content`/`raw_content`.
   Order by `sequence_index` and render with the same schema; rendered files
   carry `reconstructed: true` in frontmatter (§4.2).

### 5.2 Standardization

A single renderer (`memento_render.py`, shared module) converts any normalized
message list to the canonical markdown of §4.2. The cleaning logic currently
embedded in `ChronicleIngester._refine_content`
(`scripts/antigravity_ingest.py:60-75`; today reused by `chronicle_refine.py`
via a whole-class import) is extracted into the shared module so the ingester
and the renderer produce byte-identical cleaned text. The MUST-9 secret
scrubber lives in this same shared module, so ingester and Memento apply
identical redaction.

### 5.3 Idempotency & Registry

- Session directory = sanitized slug of `session_id` (§4.2, deterministic):
  `<memento>/<AAAA-MM>/<source>/<session>/`. Reruns reconcile `memento/index.md`
  (overwrite) + regenerate `memento/NNN-*.md` splits + **invalidate** `distill/` +
  `refine/` if `memento_hash` changed (see §4.5.1). `raw/` is left untouched if
  present and provider store is gone (forensics); its extension is
  provider-dependent (`raw.*`).
- `memento_registry.json` (next to `chronicle_daily_registry.json`, i.e. under
  `get_data_dir()`) records
  `{source: {session_id: {dir, rendered_at, message_count, step_count, has_splits, memento_hash}}}`
  — keyed by `session_id`, each entry carrying the session `dir` (this is the
  single registry contract; MUST 3 refers here). `memento_hash` drives the
  Janitor staleness check of §4.5.1.
- The migration is safe to run repeatedly; only new/changed sessions are touched.
  Line refs remain stable because `memento/index.md` is the canonical anchor;
  stale derived layers are repaired via pain signal + `auto_heal_ritual` rather
  than silently drifting.

### 5.4 Execution

A new script `scripts/memento_migrate.py` (or a `--memento-only` mode of
`chronicle_daily.py`):

1. `--all`: force full reprocess of every session of every enabled source
   (all IDEs/agents with a `ChronicleSourcePlugin` on the machine).
   (Default: delta, mirroring the chronicle registry.)
2. For each source: `discover()` → for each `cid`: `load(cid)` → render →
   write `<memento>/<AAAA-MM>/<source>/<session>/memento/index.md` (+ optional
   `raw/raw.*` and `memento/NNN-*.md` splits) → update registry. The standardized
   renderer is `memento_render.py` (shared module) producing the canonical MD
   of §4.2; `raw/` bypass is for forensics only and keeps the provider's
   native extension (`.json` / `.jsonl` / `.md` / etc.).
3. If `load()` fails for a source, attempt reconstruction from `archive_memories`
   (marked `reconstructed: true` in `memento/index.md` frontmatter).
4. Rebuild generated indexes (`<memento>/index/<source>.md`, `<memento>/<AAAA-MM>/_rollup.md`).
   Indexes point to `memento/index.md` paths.
5. Dry-run mode (`--dry-run`) reports counts without writing; the report
   compares per-source censuses against `memory_queue` originators to expose
   any capture surface the sources miss (e.g. empirically confirm that
   antigravity/Telegram turns really appear in the nightly exports).
6. Agentic pass (`chronicle_distill` → `chronicle_refine`, file-based versions)
   runs separately over `memento/index.md` to populate `distill/` and `refine/`
   (see §4.5). Tree population and Qdrant re-ingestion are decoupled:
   Memento-first (§4.1).

**Where it runs (decided, 5th pass):**

- **Nightly delta render**: inside the existing chronicle job
  (`configs/jobs/chronicle.yaml`, `max_step_minutes: 60`) — rendering the day's
  sessions is cheap text I/O and fits the budget.
- **Historical backfill (`--all`, 316+ sessions)**: never part of the nightly.
  It is an explicit operator-launched run — submitted as its own job
  (`red-pill job submit`, low priority, pausable — per the trainings-as-jobs
  doctrine) so it can be throttled and resumed. The agentic pass over the
  backlog is likewise its own job, LLM-budgeted.

---

## 6. Rollout Plan

| Phase | Scope | Behavior change | Risk |
|---|---|---|---|
| **0** | RFC review; layout DECIDED (B, §4.3); location DECIDED (Q2, §4.8); naming DECIDED (Memento); scribe fate resolved — see Q3 | — | — |
| **1** | Memento renderer + `memento_migrate --all` backfill (own job) + persist the `search_memory_research` query log (3.5 prerequisite, §4.6) + **calibration cata** over the backfilled corpus to fix Q8 (split thresholds) and inform Q4 | None (additive) | Low |
| **2** | `search_memento` MCP action + index generation | None | Low |
| **3** | TTL backstop (72h) via `interaction_ttl` JanitorPlugin (S3, §4.4) + `queue_purge_rendered` JanitorPlugin (§4.4.2) — requires MUST 10 so no surface loses its only raw record | Low (stray raw turns leave Qdrant — Memento holds them) | Low |
| **3.5** | Curation gate in **shadow**: log-only significance decisions + replayed-query recall measurement (§4.6). File-based distill/refine land here; Qdrant-targeting scripts still running | None | Low |
| **4** | Curation gate enforced: `archive_memories` ingest gated by significance; legacy `chronicle_distill.py`/`chronicle_refine.py` retired (§4.5) | High (recall changes) | Medium (bounded by 3.5 evidence) |

Each phase is independently revertible. Phase 4 is the single point of no
architectural return and requires explicit operator approval, backed by the
Phase 3.5 shadow evidence (the revised Phase 3 is mere pruning — trivially
revertible).

---

## 7. Open Questions

1. **Layout**: **RESOLVED (2026-08-22, updated 2026-08-26)** — B (month-first,
   `yyyy-mm`) with per-session directory
   `<memento>/<AAAA-MM>/<source>/<session>/memento/index.md` plus `raw/`,
   `distill/`, `refine/` (§4.2, §4.3).
2. **Location**: **RESOLVED (operator, 2026-08-26)** — default
   `get_data_dir()/memento` (`~/.local/share/red-pill/memento/`), following the
   kernel-state standard, **but operator-overridable via `MEMENTO_ROOT`** (§4.8).
   Git only after MUST 9 exists (and never covering `raw/`).
3. **Scribe fate**: **RESOLVED (2026-08-21, re-founded 2026-08-26)** —
   `interaction_memories` stays as a TTL'd rolling buffer. Honest grounds: the
   pre-heating interceptor consumes it via time-filtered `scroll` (not
   semantically); keeping the buffer avoids touching a working hot-path
   interceptor (§4.4). The intra-day continuity gap it does *not* solve is
   deferred (§4.4.1, NG6).
4. **Curation threshold**: what defines "significant enough to ascend"?
   **OPEN — deliberately.** Operator decision 2026-08-26: cannot be decided
   without data; resolved with the Phase 1 cata + Phase 3.5 shadow evidence
   (§4.6), not a priori.
5. **Retention**: does Memento replace `archive_memories` entirely, or does
    `archive_memories` remain for the atomized/graph form? *Recommendation:*
    `archive_memories` ends curated-only; keeping "everything atomized" rebuilds
    the three-copies problem this RFC exists to kill. Memento-first: historical
    tree is populated first; Qdrant recreation is selective and Aleth-approved
    (see §4.1).
6. **Workspace tagging**: **RESOLVED (operator, 2026-08-26)** — yes; the §4.2
    `memento/index.md` schema carries `workspace` officially, and `search_memento`
    accepts it as scope. It also feeds `cross_refs` candidate discovery (§4.5).
7. **Real-time Memento**: **RESOLVED (operator, 2026-08-26)** — the 04:00 batch
    suffices while the TTL buffer exists; live append (S2) stays MAY.
8. **Split threshold**: **OPEN — pending cata.** Operator decision 2026-08-26:
    not decidable without data. Phase 1 runs a calibration cata over the
    backfilled corpus (distribution of message counts / char sizes across the
    316 historical sessions) and the thresholds are frozen then. Until that,
    `MEMENTO_SPLIT_MAX_MESSAGES=30` / `MEMENTO_SPLIT_MAX_CHARS=24000` are
    provisional placeholders (§4.8) — the 4th-pass `8k chars` figure is known
    to be too low (it would split nearly every real session).

---

## 8. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Migration re-ingests everything and hits timeout (the 29-jul lesson) | Delta by default; `--all` is explicit and runs as its own pausable job (§5.4); seeded registry per source; throttled loop |
| Tree grows unbounded on disk | Markdown is tiny vs vectors; git optional; monthly folders make archiving trivial |
| Losing the graph/thread semantics that Qdrant associations provide | `prev/next_session` computed at render time (SHOULD 12) + Obsidian graph view + generated indexes; `refine/cross_refs` for cross-provider panels |
| Recall regression during Phase 4 | Semantic store keeps the consolidated engrams; Memento fills the exact-recall gap; both compose in search |
| Double-writing during Phase 3 duplicates state | `memory_queue` content_hash dedup already exists; Memento writes are idempotent |
| Secrets (tokens, keys, credentials in tool inputs) reach plaintext markdown | MUST-9 scrubber in the shared renderer (§5.2); git history gated on it **and excludes `raw/`** (unscrubbed); Memento covered by the pending LUKS-encrypted home plan |
| A surface with no provider store loses its raw record once the TTL prunes | MUST 10: `memory_queue` chronicle source lands before Phase 3; queue rows purge only post-render via `queue_purge_rendered` (§4.4.2, also caps today's unbounded queue growth) |
| Stale `distill/`/`refine/` after `memento/index.md` changes | JanitorPlugin detects `memento_hash` mismatch (§4.5.1) → pain signal `memento_stale_*` → `auto_heal_ritual` re-runs distill→refine for that session (full regeneration, `knowledge_graph_stale` precedent) |
| Name collision with the MLS "Sovereign Vault" layer | Renamed **Memento** (Naming Note); the Secrets Manager's ROADMAP entry carries the reciprocal note |

---

## 9. Related Documentation

- [RFC-001: Firmware Partition Protection](./RFC_001_FIRMWARE_PROTECTION.md)
- [BUNKER_MANIFESTO](./BUNKER_MANIFESTO.md)
- [FERRARI_PROTOCOL](./FERRARI_PROTOCOL.md)
- [CHRONICLE_INGESTION_GUIDE](../../GUIDES/CHRONICLE_INGESTION_GUIDE.md)
- [DECISION_LOG](../DECISION_LOG.md)
- [ARCHITECTURE](../ARCHITECTURE.md)
- Audit: `sharing/.red-pill/memory/REVIEW_2026-08-26_rfc002-vault-audit.md` (5th-pass driver)
