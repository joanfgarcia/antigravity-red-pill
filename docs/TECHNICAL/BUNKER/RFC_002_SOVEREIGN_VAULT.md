# RFC-002: Sovereign Vault Chronicle

| Field | Value |
|---|---|
| **RFC** | 002 |
| **Title** | Sovereign Vault Chronicle |
| **Codename** | Project Vault |
| **Status** | DRAFT |
| **Author** | Joan García (Operator) / Aleth (Agent) |
| **Created** | 2026-08-20 |
| **Revised** | 2026-08-21 — design review, 2 passes: TTL buffer, secret-scrub MUST, immutable month, shadow gate, `memory_queue` source, archive-only gate. 2026-08-22 — 3rd pass: layout DECIDED (B, `yyyy-mm`), agentic pass delineated (Distill→Refine as §4.5), hubs/reinforcement/forgetting confirmed unchanged. 2026-08-26 — 4th pass: per-session directory with `raw/`/`vault/`/`distill/`/`refine/`, `vault/index.md` always canonical, `distill`/`refine` schemas with line refs + cross-session refs, artifact exclusion, historical Vault-first migration |
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
- The 03:00 Sleep cycle later consolidates that buffer into `work_memories`,
  deleting the processed points afterwards (`consolidation.py:516,521`) — the
  buffer self-drains; only failed points and VRAM-deferred nights linger.

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

1. **Double vectorization cost.** The same conversation is embedded at least twice
   — once raw in `interaction_memories`, once atomized in `archive_memories` —
   and for long turns 2+N times: the ingester writes a `monolith_parent` plus N
   `idea_fragment` nodes, each embedded (`scripts/antigravity_ingest.py:183-215`).
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

Introduce a **Sovereign Vault**: a disk-based, markdown tree of all
conversations/sessions (per provider), written by the chronicle pipeline —
the "grabadora" becomes cheap, exact, and human-readable. Qdrant stops being a
firehose and returns to being a **curated memory**: only what the consolidation
(distill/refine) judges to be engram ascends to vectors. The boundary between
"raw" and "curated" is drawn at **consolidation time**, never at capture time.
The Vault is the carpaccio archive in the closet — if you need verbatim detail
it is there; synthetic memory (Qdrant) keeps only what is worth remembering.
Artifacts (PDFs, images, binary attachments) are not Vault content: they are
not memory, and Vault is already oversized as an intermediate before distillation.

---

## 2. Goals / Non-Goals

### 2.1 Goals

- G1. Every captured conversation lives on disk as a canonical, readable
  per-session directory (`raw/` + `vault/` + `distill/` + `refine/`), grouped
  and linkable (tree + graph). The canonical verbatim is always
  `vault/index.md`.
- G2. Capture cost becomes near-zero (no embedding at write time for the vault;
  the only residual embedding is the short-lived TTL buffer of §4.4, bounded
  to 2–3 days of operator turns).
- G3. Qdrant holds only synthesized/consolidated engrams → better signal-to-noise.
  Vault-first: the historical vault is populated first, Qdrant recreation is
  selective and operator/Aleth-approved.
- G4. Exact recall: any session can be read verbatim by path or full-text via
  `vault/index.md`. Scope stated honestly: "verbatim" means the *dialogue* as
  normalized by the source plugins (user/assistant text + tool inputs); tool
  results, reasoning, and binary artifacts (PDFs, images) are not captured —
  provider stores remain canonical for full traces. Vault is synthetic memory,
  not a database.
- G5. A migration path that re-processes **all** existing chronicle history from
  every provider (all IDEs/agents present on the machine), standardizes it, and
  populates the vault.
- G6. Hybrid search: semantic (Qdrant) + full-text/path (vault) as first-class,
  coexisting modes, with line-level refs enabling vault ↔ Qdrant navigation
  and cross-session refs (including cross-provider adversarial panels).

### 2.2 Non-Goals

- NG1. Not replacing Qdrant as the associative memory; only relieving it of raw bulk.
- NG2. Not building a new UI; Obsidian (or any md reader) can be pointed at the vault.
- NG3. Not changing the capture *surfaces* (hooks/bridges) — only their sink.
- NG4. Not a semantic store on disk; the vault is text, not embeddings.
- NG5. Not archiving binary artifacts; documents/images passed in prompts are not
  Vault content (they are not memory — the operator may have deleted them and
  forgetting them is not a defect).

---

## 3. Functional Requirements

### 3.1 MUST

1. **Vault renderer**: the chronicle pipeline writes every normalized message to a
   per-session directory in the vault (`<vault>/<AAAA-MM>/<source>/<session>/`),
   regardless of provider. The canonical verbatim is always `vault/index.md`.
2. **Canonical format**: a single markdown schema (frontmatter + body) for all sources,
   with normalized timestamps and role markers, always at `vault/index.md`.
   `raw/` (if enabled) keeps the provider-native verbatim verbatim; `vault/` is
   the unified MD. Artifacts are excluded by definition.
3. **Idempotency**: re-running a session render is deterministic (overwrite, no dupes),
   keyed by `session_id`. Reruns overwrite `vault/index.md` and reconcile
   derived `vault/0*.md` splits; registry key is the session directory.
4. **Migration command**: a mechanism to force-reprocess the full chronicle history
   of all enabled sources into the vault (`--all` equivalent) — covering every
   IDE/agent with a `ChronicleSourcePlugin` present on the machine.
5. **Backfill fallback**: if a source store is unavailable, the migration can
   reconstruct sessions from `archive_memories`.
6. **Zero capture overhead**: no embedding is produced for raw vault content
   (`raw/` and `vault/` are text only; `distill`/`refine` are LLM-derived but
   not embedded themselves — only their promoted engrams ascend to Qdrant).
7. **Config switch**: `VAULT_ROOT` configurable (default under `get_data_dir()`),
   and per-source enable/disable.
8. **No breakage during rollout**: existing Qdrant behavior must not change until
   a phase explicitly deprecates it. Vault-first: historical vault population
   precedes any Qdrant recreation; Qdrant recreation is gated and Aleth-approved.
9. **Secret scrubbing**: the shared renderer applies a redaction pass (API keys,
   tokens, passwords, common credential shapes) to every message before it is
   written to the vault. Tool *inputs* are rendered into the vault (e.g. bash
   commands via `_render_tool_use`), so credentials typed in terminals WILL
   reach disk unless scrubbed. Git history (MAY 16) must not be enabled before
   this exists.
10. **`memory_queue` chronicle source** (required before rollout Phase 3): turns
     whose only capture surface is the MCP `memorize_interaction` have no native
     provider store — without this source they never reach the vault, and once
     the TTL prunes the buffer their raw record is gone. The queue keeps every
     row (`completed` rows are never purged today), so it doubles as the
     canonical store for that surface: group rows lacking a session by
     `originator` + day (`mcp:<originator>:<AAAA-MM-DD>`). Retention closes the
     loop: completed rows may be purged only after the vault has rendered them.

### 3.2 SHOULD

11. **Search mode**: a vault search action in the MCP (full-text via ripgrep,
    scoped by source/month, returns paths + snippets).
12. **Graph links**: frontmatter carries `prev_session`/`next_session` (thread
    continuity), so Obsidian renders a conversation graph.
13. **Per-source and per-month indexes** generated automatically.
14. **Registry**: `vault_registry.json` mirrors `chronicle_daily_registry.json`
    so reruns are cheap and audits possible.
15. **Noise normalization** shared with the ingester (reuse `_refine_content`-style
    cleaning, moved to a common module).

### 3.3 MAY

16. **Git history**: vault optionally git-initialized for immutable history.
    Gated on MUST 9: immutable history makes any leaked secret permanent, so
    the scrubber lands first.
17. **Dual-write window**: superseded by the revised S3 (§4.4) — the scribe
    keeps writing to `interaction_memories` permanently; the collection is now a
    TTL'd buffer, so there is no "stop" event, only pruning.
18. **Automatic curation gate**: distill/refine may auto-promote vault fragments to
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
   │  CHRONICLE (04:00)                                          │
   │  discover_source_plugins → load() → normalize               │
   │        │                                        │           │
   │        ▼                                        ▼           │
   │   SOVEREIGN VAULT (disk)                   Qdrant raw sink │
   │   markdown tree + indexes               (gated in Phase 4)  │
   └───────────────┬────────────────────────────────────────────┘
                   │  (only curated content: distill→refine→gate)
                   ▼
   CONSOLIDATION (distill / refine / sleep)   →   work_memories / social_memories
                   │
                   ▼
   SEARCH   semantic (Qdrant)   +   exact/fulltext (vault/index.md)
```

- **Raw layer = vault (disk).** Cheap, lossless, greppable, human-readable.
  Inside each session: `raw/` (optional provider verbatim) + `vault/` (unified MD).
- **Synthesis layer = Qdrant.** Only engrams that passed `distill`→`refine`→gate.
- **Decision point = consolidation.** The chronicle decides *what ascends*; the
  capture surfaces never decide (they are deliberately dumb). Vault is the
  carpaccio archive — Qdrant is synthetic memory.
- **Artifact policy:** binary attachments (PDFs, images, etc.) are not Vault
  content. Only `role: user|assistant` text + compact tool-input markers
  (`[TOOL: ...]`) are rendered. Forgetting an artifact is not a defect.

### 4.2 Vault Session Directory — per-session `raw/` / `vault/` / `distill/` / `refine/`

Each session is a **directory**, not a single file:

```
<vault>/<AAAA-MM>/<source>/<session>/
  raw/                          # MAY: provider-native verbatim (optional, for forensics)
    raw.*                       # extension mirrors provider: .json / .jsonl / .md / .db-slice
  vault/
    index.md                    # MUST: canonical unified MD — always present, always complete
    01-titulo-seccion.md        # MAY: split views for dense sessions (derived from index.md)
    02-titulo-seccion.md
  distill/
    01-titulo.md
    02-titulo.md
  refine/
    01-titulo.md
    02-titulo.md
```

#### `raw/` — provider verbatim (MAY, default OFF)

- `raw/` stores the session verbatim **in the provider's native shape** —
  extension follows the source: `opencode` → `raw.json` (dump of
  `[{role, content, timestamp}]` + relevant envelope), `claude_code` →
  `raw.jsonl` (original JSONL slice), `antigravity` → `raw.json`, `pi` →
  `raw.md` tree / flat MD if that is its native export, etc. No cleaning
  beyond role filtering; no secret scrubbing bypass beyond the shared scrubber
  if the file is later rendered (but `raw/` itself is never the search target).
- Purpose: forensics only. The vault renderer does not read it; the migration
  backfill prefers live provider stores over `raw/`. Enable only if the operator
  wants an extra verbatim layer besides the provider store itself. `raw/` is
  format-agnostic by design so new providers (e.g. PI) do not need conversion.

#### `vault/index.md` — canonical unified MD (MUST)

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
- 01 — Objetivo y contexto (l12)
- 02 — Panel adversarial Qwen vs Hermes (l340)

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
- `reconstructed: true` (frontmatter) marks sessions rebuilt from
  `archive_memories` (§5.1.2): their body is *refined* text, not verbatim — the
  flag keeps G4 honest about which files are literal transcripts.
- `vault/index.md` is **always complete**. Split views (`vault/NNN-*.md`) are
  derived projections for dense-session navigation, never the canonical copy.
  `distill`/`refine` and `search_vault` target `vault/index.md` line ranges
  for stable refs. `rg` over the vault should target `vault/index.md` files.

#### `vault/NNN-*.md` — split views for dense sessions (MAY)

- Created only when a session exceeds a threshold (default: `>30` messages or
  `>8k` chars, configurable). Each file is `vault/<NNN>-<slug>.md` (`NNN` =
  `001–999` same convention as distill/refine) — a slice of `vault/index.md`
  with a header `> [!ref] vault/index.md#l120-340` and the same
  `## TIMESTAMP — Role` blocks.
- `vault/index.md` gains a `## Secciones` TOC with links `[[001-titulo]]` when
  splits exist. For light sessions no split files are created — `index.md`
  alone is the session.

#### General rules

- No binary artifacts are rendered in `vault/` (NG5). Only dialogue text +
  compact `[TOOL: ...]` markers.
- All `vault/` content passes the shared scrubber + noise normalization
  (`vault_render.py` shared module, §5.2) — `raw/` is provider-native and
  format-agnostic, not a scrubbed MD.

### 4.3 Structural Decision: source-first vs month-first — **DECIDED**

**Decision (operator, 2026-08-22): B — month-first, `yyyy-mm` granularity.**

- **B (timeline-first, chosen):** `<vault>/<AAAA-MM>/<source>/<session>/vault/index.md`
  with sibling `raw/`, `distill/`, `refine/` subdirectories (see §4.2).

| Criterion | A — source-first | B — month-first |
|---|---|---|
| "What did we do in May?" | glob across sources | one folder |
| "All opencode sessions" | one folder | glob across months |
| Obsidian daily-note metaphor | weak | natural |
| Month rollups / narrative | need cross-source aggregation | trivial per folder |
| Graph/thread continuity | same | same (via frontmatter) |
| Path stability | stable | stable — month pinned to first-message `created_at` (see below) |

Rationale: the vault is a *chronicle* — its primary value is narrative/temporal.
A session is an event in time; the month is the natural container. The "all
sessions of a source" browsing is recovered with an auto-generated per-source
index (`<vault>/index/<source>.md`) that lists sessions chronologically, and the
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
Applies to the session directory `<vault>/<AAAA-MM>/<source>/<session>/`; all
inner paths (`raw/`, `vault/index.md`, etc.) move together.

### 4.4 Scribe Relay Evolution

Steps are named S1–S3: scribe-evolution steps, not the §6 rollout phases.

- S1: scribe continues exactly as today; the vault is purely additive.
- S2 (optional): scribe writes the turn to the vault (append) *in addition*
  to the queue, so the vault is real-time, not only 04:00.
- S3 (revised 2026-08-21, 2nd pass): `interaction_memories` is **not**
  deprecated — it stays as the rolling short-term buffer it already *almost*
  is: Sleep deletes processed points after consolidation
  (`consolidation.py:516,521`), so the collection self-drains nightly. The only
  new mechanism is a **TTL backstop of 72h** for what the drain leaves behind
  (failed points in `failed_ids`, VRAM-deferred nights). Constraint:
  `TTL > PRE_HEATING_LOOKBACK_HOURS` (48h, `config.py:686`) — the pre-heating
  interceptor (`src/red_pill/interceptors/11_pre_heating.py:96-102,232-237`)
  queries this collection *semantically* (top-3 recent raw context plus the
  tier-2 recent-work fallback), a query shape full-text over the vault cannot
  serve (NG4); the TTL must never starve its window. Sleep
  (`src/red_pill/metabolism/phases/consolidation.py:142`) and pre-heating stay
  untouched. Durable raw storage is the vault; Qdrant keeps only the hot
  window.
- The MCP `memorize_interaction` anti-noise filter (`mcp_server.py:234`) is
  preserved and applied to the vault write.

### 4.5 The Agentic Pass: Distill → Refine

Between the mechanical vault write (§4.1) and the curation gate lives the
**agentic pass** — two stages that today operate on Qdrant engrams and are
re-targeted to operate on the vault files. Input is always `vault/index.md`
(and its optional `vault/NNN-*.md` splits for context); line refs always point
to `vault/index.md`.

1. **`chronicle_distill` (segmentation + structured sectioning).** Reads
   `vault/index.md` and splits it into **sections** (a session may cover
   disparate topics — not ideal but common). Each section becomes
   `distill/<NNN>-<slug>.md` (`NNN` = `001–999`, zero-padded; `slug` =
   lowercase, hyphen, ascii, `≤40ch` derived from `title`) with frontmatter:

   ```yaml
   ---
   session_id: opencode:abc-123
   source: opencode
   section: 1
   title: "Panel adversarial Qwen vs Hermes — árbol de decisión Vault"
   summary: "Resumen ≤10 líneas de lo tratado en la sección."
   keywords: [vault, distill, panel adversarial, qwen, hermes]
   source_lines: vault/index.md#l120-340
   source_ref: vault/index.md
   ---
   ```

   Body: `summary` (≤10 lines) + bullet of key points. The job is *structured
   filtration*: produce navigable sections with `title` + `summary` + `keywords`
   + `source_lines` refs to the canonical `vault/index.md`. It drops the
   uninteresting bulk — tool-use detail, routine agent plumbing — unless a
   specific fragment is genuinely notable. Internal agent reasoning is kept
   only when it is *actually interesting* (a decision, an insight).

2. **`chronicle_refine` (selection + texture + cross-refs).** Reads `distill/*.md`
   (not `vault/` directly) and selects which sections carry durable value. For
   each surviving section it writes `refine/<NNN>-<slug>.md` (same `NNN`/`slug`
   convention as distill):

   ```yaml
   ---
   session_id: opencode:abc-123
   source: opencode
   distill_ref: distill/01-titulo.md
   source_lines: vault/index.md#l120-340
   significance: 0.87
   emotion: cyan
   intensity: 0.72
   texture: {theme: vault_architecture, relics: ["carpaccio archive", "synthetic memory"]}
   cross_refs: ["claude_code:xyz-789", "opencode:def-456"]
   ---
   ```

   Body: curated summary + `texture` (theme classification, emotional charge,
   relics) + `cross_refs` to related sessions — including **cross-provider**
   refs when an adversarial panel spans multiple agents/models/IDEs. Extraction
   is the same as currently performed on Qdrant engrams (`chronicle_distill.py`
   — Samantha, `chronicle_refine.py`), applied to the vault markdown as input.
   Every `refine/` file carries `source_lines` + `distill_ref` so Aleth or the
   operator in Obsidian can navigate vault → distill → refine → Qdrant engram
   without losing provenance.

The output of the agentic pass is the input to the curation gate (§4.6): a
section becomes a candidate engram only after distill+refine have judged it.
`refine/` is the gate input; `distill/` is the structured intermediate that
makes `refine` and navigation possible.

### 4.5.1 Slug & Invalidation Contract

- **Slug:** `NNN` = `001–999` zero-padded (exagerado pero gratis), `slug` =
  `lowercase, hyphen, ascii, ≤40ch` from `title`. Deterministic ordering by
  `NNN`; reruns preserve `NNN` for identical section order.
- **Invalidation:** if `vault/index.md` changes (`message_count`/`step_count`/
  content hash differs from `vault_registry.json`), the session's `distill/`
  and `refine/` are **fully regenerated** (not patched) — stale `source_lines`
  would otherwise point to wrong ranges. A Janitor check detects the mismatch,
  emits a pain signal (`vault_stale_distill` / `vault_stale_refine`), and a
  Healer job re-runs `chronicle_distill` → `chronicle_refine` for that session.

### 4.6 Curation Gate

The chronicle's agentic pass (`chronicle_distill.py` — Samantha,
`chronicle_refine.py`) produces the "curated" signal. The change:
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

Everything else lives only in the vault.

**Shadow mode first (Phase 3.5).** The gate's criteria are unproven —
"referenced by later sessions" requires reference tracking that does not exist
yet. Before enforcing, the chronicle runs the gate log-only for several weeks:
it computes the would-be decision, stamps `significance` into vault frontmatter
and counts it in the registry, while still ingesting everything. Recall impact
is then measured by replaying real `search_memory_research` queries against
gated vs ungated sets. Phase 4 flips the switch only on that evidence.

**Prerequisite (2nd pass):** no query log exists today — telemetry does not
record `search_memory_research` calls. Query logging (query text + timestamp)
starts in rollout Phase 1, well before Phase 3.5, so the replay has a real
corpus to draw from.

**Hub formation & reinforcement/forgetting engines — unchanged.** Once a
fragment ascends to Qdrant, the downstream lifecycle stays exactly as it is
today: hubs assemble from related engrams in later phases, and the
reinforcement/forgetting engines (FSRS stability, Lazarus erosion,
reinforcement via re-recall) keep operating on the Qdrant collections
unchanged. This RFC does not touch that machinery; it only changes *what*
enters it.

### 4.7 Search

New first-class action `search_vault` in `bunker_memory_api`:

- `rg -l`/`rg -C` full-text over the vault, scoped by `source`, `month`, `workspace`.
  Canonical target is `vault/index.md` (split `vault/NNN-*.md` are derivates;
  `raw/` is excluded from default search). `distill/` and `refine/` are
  searchable as secondary scopes for structured recall.
- Returns `{path, snippet, session_id, source, source_lines}` — `path` points to
  `vault/index.md` (or `refine/*.md`), `source_lines` enables click-through
  navigation vault ↔ distill ↔ refine.
- Cross-provider refs from `refine/cross_refs` enable vault-graph traversal
  (e.g. adversarial panel spanning opencode + claude_code).
- Compose with `search_memory_research` for hybrid recall:
  semantic hits point to engrams; vault hits point to exact passages in
  `vault/index.md`.

---

## 5. Migration Mechanism

Goal: reprocess **all** existing chronicle history from every provider,
standardize it, and dump it into the vault.

### 5.1 Sources of Truth (in priority order)

1. **Provider stores (canonical):** opencode.db SQLite, Claude Code JSONL,
   Antigravity exports — via the existing `ChronicleSourcePlugin.discover()/load()` —
   plus the `memory_queue` SQLite for MCP-only turns (MUST 10).
   These are the rawest and most complete.
2. **`archive_memories` (fallback):** if a provider store is gone (e.g. old
   Antigravity exports), reconstruct sessions from the collection: points carry
   `session_id`, `sequence_index`, `role`, `refined_content`/`raw_content`.
   Order by `sequence_index` and render with the same schema; rendered files
   carry `reconstructed: true` in frontmatter (§4.2).

### 5.2 Standardization

A single renderer (`vault_render.py`, shared module) converts any normalized
message list to the canonical markdown of §4.2. The cleaning logic currently
embedded in `antigravity_ingest.py` (`_refine_content`, ANSI/noise stripping)
is extracted into the shared module so the ingester and the vault renderer
produce byte-identical cleaned text. The MUST-9 secret scrubber lives in this
same shared module, so ingester and vault apply identical redaction.

### 5.3 Idempotency & Registry

- Session directory = slug of `session_id` (deterministic):
  `<vault>/<AAAA-MM>/<source>/<session>/`. Reruns reconcile `vault/index.md`
  (overwrite) + regenerate `vault/NNN-*.md` splits + **invalidate** `distill/` +
  `refine/` if the vault hash changed (see §4.5.1). `raw/` is left untouched if
  present and provider store is gone (forensics); its extension is
  provider-dependent (`raw.*`).
- `vault_registry.json` (next to `chronicle_daily_registry.json`) records
  `{source: {session_id: {rendered_at, message_count, step_count, has_splits, vault_hash}}}`.
  `vault_hash` (e.g. `sha256` of `vault/index.md` body) drives the Janitor
  staleness check of §4.5.1.
- The migration is safe to run repeatedly; only new/changed sessions are touched.
  Line refs remain stable because `vault/index.md` is the canonical anchor;
  stale derived layers are repaired via pain signal + Healer rather than silently
  drifting.

### 5.4 Execution

A new script `scripts/vault_migrate.py` (or a `--vault-only` mode of
`chronicle_daily.py`):

1. `--all`: force full reprocess of every session of every enabled source
   (all IDEs/agents with a `ChronicleSourcePlugin` on the machine).
   (Default: delta, mirroring the chronicle registry.)
2. For each source: `discover()` → for each `cid`: `load(cid)` → render →
   write `<vault>/<AAAA-MM>/<source>/<session>/vault/index.md` (+ optional
   `raw/raw.*` and `vault/NNN-*.md` splits) → update registry. The standardized
   renderer is `vault_render.py` (shared module) producing the canonical MD
   of §4.2; `raw/` bypass is for forensics only and keeps the provider's
   native extension (`.json` / `.jsonl` / `.md` / etc.).
3. If `load()` fails for a source, attempt reconstruction from `archive_memories`
   (marked `reconstructed: true` in `vault/index.md` frontmatter).
4. Rebuild generated indexes (`<vault>/index/<source>.md`, `<vault>/<AAAA-MM>/_rollup.md`).
   Indexes point to `vault/index.md` paths.
5. Dry-run mode (`--dry-run`) reports counts without writing; the report
   compares per-source censuses against `memory_queue` originators to expose
   any capture surface the sources miss (e.g. empirically confirm that
   antigravity/Telegram turns really appear in the nightly exports).
6. Agentic pass (`chronicle_distill` → `chronicle_refine`) runs separately over
   `vault/index.md` to populate `distill/` and `refine/` (see §4.5). Vault
   population and Qdrant re-ingestion are decoupled: Vault-first (§4.1).

---

## 6. Rollout Plan

| Phase | Scope | Behavior change | Risk |
|---|---|---|---|
| **0** | RFC review; layout DECIDED (B, §4.3); decide vault location (§7); scribe fate resolved — see Q3 | — | — |
| **1** | Vault renderer + `vault_migrate --all` backfill + start the `search_memory_research` query log (3.5 prerequisite) | None (additive) | Low |
| **2** | `search_vault` MCP action + index generation | None | Low |
| **3** | TTL backstop (72h) on `interaction_memories` (S3, §4.4) — Sleep already self-drains it; requires MUST 10 so no surface loses its only raw record | Low (stray raw turns leave Qdrant — the vault holds them) | Low |
| **3.5** | Curation gate in **shadow**: log-only significance decisions + replayed-query recall measurement (§4.6) | None | Low |
| **4** | Curation gate enforced: `archive_memories` ingest gated by significance | High (recall changes) | Medium (bounded by 3.5 evidence) |

Each phase is independently revertible. Phase 4 is the single point of no
architectural return and requires explicit operator approval, backed by the
Phase 3.5 shadow evidence (the revised Phase 3 is mere pruning — trivially
revertible).

---

## 7. Open Questions

1. **Layout**: **RESOLVED (2026-08-22, updated 2026-08-26)** — B (month-first,
   `yyyy-mm`) with per-session directory
   `<vault>/<AAAA-MM>/<source>/<session>/vault/index.md` plus `raw/`,
   `distill/`, `refine/` (§4.2, §4.3).
2. **Vault location**: `~/.local/share/red-pill/vault/` (default) vs a git repo
    vs inside Agent_Core. *Recommendation:* the default — the vault is kernel
    state and red-pill manages it; Agent_Core is the agent's desk, not a kernel
    sink. Git only after MUST 9 exists.
3. **Scribe fate**: **resolved (design review 2026-08-21)** — `interaction_memories`
    stays as a TTL'd rolling buffer; the pre-heating interceptor consumes it
    semantically and the vault cannot serve that query shape (§4.4).
4. **Curation threshold**: what defines "significant enough to ascend"? Operator
    flag, `refine/significance` score, reference count, or a combination?
    *Recommendation:* decide with Phase 3.5 shadow data (§4.6), not a priori.
5. **Retention**: does the vault replace `archive_memories` entirely, or does
    `archive_memories` remain for the atomized/graph form? *Recommendation:*
    `archive_memories` ends curated-only; keeping "everything atomized" rebuilds
    the three-copies problem this RFC exists to kill. Vault-first: historical
    vault is populated first; Qdrant recreation is selective and Aleth-approved
    (see §4.1).
6. **Workspace tagging**: should sessions carry their `workspace` so the vault
    can be browsed by project? *Recommendation:* yes — the §4.2 `vault/index.md`
    schema already carries the key; make it official.
7. **Real-time vault**: does the scribe write to the vault live (S2), or is
    the 04:00 batch enough? *Recommendation:* with the TTL buffer retained, the
    04:00 batch suffices; live append stays MAY.
8. **Vault split threshold**: when to emit `vault/NNN-*.md` splits for dense sessions?
    *Recommendation:* `>30` messages or `>8k` chars (configurable); otherwise
    `vault/index.md` alone suffices (§4.2).

---

## 8. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Migration re-ingests everything and hits timeout (the 29-jul lesson) | Delta by default; `--all` is explicit; seeded registry per source; throttled loop |
| Vault grows unbounded on disk | Markdown is tiny vs vectors; git optional; monthly folders make archiving trivial |
| Losing the graph/thread semantics that Qdrant associations provide | `prev/next_session` frontmatter + Obsidian graph view + generated indexes; `refine/cross_refs` for cross-provider panels |
| Recall regression during Phase 4 | Semantic store keeps the consolidated engrams; vault fills the exact-recall gap; both compose in search |
| Double-writing during Phase 3 duplicates state | `memory_queue` content_hash dedup already exists; vault writes are idempotent |
| Secrets (tokens, keys, credentials in tool inputs) reach plaintext markdown | MUST-9 scrubber in the shared renderer (§5.2); git history gated on it; vault covered by the pending LUKS-encrypted home plan |
| A surface with no provider store loses its raw record once the TTL prunes | MUST 10: `memory_queue` chronicle source lands before Phase 3; queue rows purge only post-render (also caps today's unbounded queue growth) |
| Stale `distill/`/`refine/` after `vault/index.md` changes | Janitor detects `vault_hash` mismatch (§4.5.1) → pain signal `vault_stale_*` → Healer re-runs distill→refine for that session (full regeneration) |

---

## 9. Related Documentation

- [RFC-001: Firmware Partition Protection](./RFC_001_FIRMWARE_PROTECTION.md)
- [BUNKER_MANIFESTO](./BUNKER_MANIFESTO.md)
- [FERRARI_PROTOCOL](./FERRARI_PROTOCOL.md)
- [CHRONICLE_INGESTION_GUIDE](../../GUIDES/CHRONICLE_INGESTION_GUIDE.md)
- [DECISION_LOG](../DECISION_LOG.md)
- [ARCHITECTURE](../ARCHITECTURE.md)