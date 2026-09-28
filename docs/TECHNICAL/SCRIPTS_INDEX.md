# 📜 Red-Pill Scripts Index

This document catalogs the utility scripts found in the `scripts/` directory. These scripts are crucial for maintaining, testing, and managing the Red-Pill ecosystem without getting lost in oblivion.

> [!NOTE]
> When executing benchmarks or heavy background tasks, the system mandates the use of the **OOM Shield Protocol** (`systemd-run`) to prevent system crashes.

## 🏆 Benchmarking & Hardware Tuning

### `arena_benchmark.py`
**Purpose:** An automated benchmarking orchestrator designed to evaluate GGUF models on logic, math, and code generation.
**Features:**
- Implements a stunning interactive UX that pipes the output of the newly compiled `llama-cli` (complete with ASCII art and generation statistics).
- Injects the `OOM Shield` (`systemd-run --user --scope -p MemoryMax=10G`) automatically to protect the host OS during heavy inference.
- Calculates and logs token-per-second (t/s) metrics to validate native Blackwell (SASS) compilation speeds.

### `bitnet_sovereign_bench.py`
**Purpose:** Experimental benchmarking suite for 1.58-bit ternary models.

## 🛠️ System Management & Installation

### `install_neo.sh`
**Purpose:** The primary installation and bootstrapping script for the Red-Pill ecosystem. It enforces the Sound of Silence protocol and injects the core `systemd` Daemons.

### `upgrade.sh`
**Purpose:** Pulls the latest architectural changes and applies them securely.

### `setup_torch.py`
**Purpose:** Dynamically detects the host's CUDA/ROCm environment and installs the correct `torch` dependencies to maintain `BE_WATER` adaptability.

### `inject_cli.py` + `inject/<ide>/`
**Purpose:** IDE/CLI anchor & harness injectors. `inject_cli.py` autodetects present surfaces and dispatches to per-IDE adapters under `scripts/inject/<ide>/` (antigravity, claude-code, opencode, **pi**). Each adapter is idempotent and supports `--remove`. Pi's adapter seeds `~/.pi/agent/extensions/red-pill.ts`, the merged skills and the workspace anchor `<ws>/AGENTS.override.md`; it never touches `~/.pi/agent/settings.json` and never configures MCP (Pi has no MCP). The shared anchor splicer is `inject_anchor.py` (target `pi` = `<ws>/AGENTS.override.md`; per-IDE seed overrides under `seeds/<ide>/anchors/`).

## 🧠 Memory & Cognitive Maintenance

### `update_ritual.py`
**Purpose:** Versioned, idempotent, dry-run-by-default engram migrations upgraders run as part of every update (operator mandate: any released change that touches Bünker engrams MUST ship here). The 7.7.0 ritual: calibration invariant check, orphan-chunk promotion, revision-backlog advisory, tool-noise purge/compaction, axon shadow-state report. See `docs/GUIDES/AGENT_UPDATE_GUIDE.md` §1.2.

### `strip_axons.py`
**Purpose:** Total rollback net for the ADR-AXON-001 payload additions — removes cross-collection axons, v7.7.0 payload fields and `texture_shadow` points. Dry-run by default.

### `../tools/distill_lab.py`
**Purpose:** Diagnostic workbench (NOT CI) for the sleep/distillation pipeline. Calls the PRODUCTION functions so diagnostics never drift from what the kernel runs at night: `pipeline` (gen-0/1/2 simulation over a text), `probe` (golden mini-set after any prompt change), `engram` (hot before/after quality test on a live engram, dry-run default).

### `antigravity_decrypt.py`
**Purpose:** Descifra los exports de antigravity a JSON plano para la vía de extracción de Memento (`chronicle_extractor.py` → `unencrypted_conversations/`).

### `chronicle_*.py`
**Purpose:** (Histórico) `chronicle_daily.py`/`chronicle_distill.py` fueron **eliminados** en v8.0.0: la compresión/consolidación la hace el pase Memento + la ascensión. Ver `docs/TECHNICAL/OPERATIONS/SINGLE_WRITER_ROLLOUT.md`.

### `bank_janitor.py`
**Purpose:** Mechanical hygiene of the per-workspace memory bank (`<ws>/.red-pill/memory/`, no LLM): archives `.md` files >90d unreferenced from `MEMORY.md` (canonical `@refs`), detects exact duplicates (sha256) and broken index refs, writes `bank_health.json` per workspace and emits a `memory_bank_bloat_<ws>` pain signal on threshold. Dry-run by default (`--apply` to archive; a bank without index only ever reports — `archive_suppressed_no_index`). Opt-in nightly timer via `schedule_pulse.py --with-bank-janitor` (03:30). Index convention: `@fichero.md` (see `skills/workspace-memory` §1b–§1d).

### `reembed_collections.py`
> **Superseded (2026-09-25) by `qdrant_reembed.py`** (selective, snapshot, job).

**Purpose:** Recompute stored vectors after an `EMBEDDING_MODEL` change (e.g. English-only → multilingual). Same 384-dim → no schema migration. Resumable via a persisted cursor, `--dry-run` by default (`--execute` to write).

### `distiller_bakeoff.py`
**Purpose:** Aptitude harness for the sleep-cycle distiller. Runs a battery of probes (technical, philosophical, noise-culling, emotional) against each candidate GGUF and scores outputs with deterministic heuristics (JSON, ES/EN, `<think>` tags, prompt-echo, valid emotion/intensity, latency). Writes `docs/BENCHMARKS/DISTILLER_BAKEOFF.md`. Defaults to CPU to spare the live daemon's VRAM.

### `memento_recalibrate.py`
**Purpose:** Recurring curation recalibration for Memento (run whenever the distill/refine models change): `stats`/`bands`/`report` (deterministic) plus LLM audits — `audit-category` (classifier agreement), `audit-dual` (two-axis work/social routing vs the legacy ratio) and `audit-stability` (route flips across 3 batch protocols → contextual anchoring). `--engine` compares models, `--temp` pins temperature. Documented in the single-writer runbook §5.

### `memento_annotate.py`
**Purpose:** Rebuild of the `annotate` stage (MEM-006) over the whole Memento tree: idea-level notes extracted from the RAW (one compression) with the identity Bio (P0), dedup P1-A, quality gate, dual routing with dead zone and first-person voice rewrite. Session-by-session, pausable/resumable via the `memento_annotate_rebuild` element_job (per-session checkpoint); sessions already annotated with the current `annotate_prompt_version` are skipped (freshness). `--list` prints pending sessions; `--status` reports annotated/stale/pending/errors + notes; `--all` ignores freshness (from scratch, discards the partial); `--from=extract|rewrite|score` re-enters the pipeline at that phase reusing persisted state (partial or current-contract notes), degrading gracefully when prerequisites are missing; `--reason` records the invocation motive in `_meta.json`; `--root` points at an alternate tree. Resumable within a session (MEM-009 F1): `annotate/_partial.json` checkpoints each extracted split (keyed by message range, revalidated by content hash) and each phase.

### `qdrant_reembed.py`
**Purpose:** Re-embeds a Qdrant collection (given with `--collection`, obligatorio) from its `content` payload with the current embedding model. Dry-run by default (`would_update` count); `--apply` rewrites **only** vectors with cosine < `--threshold` (0.99) via `update_vectors` (payload untouched), takes a collection snapshot before the first write (name kept in the checkpoint), and advances in `--max-points` chunks from a scroll-offset checkpoint (`$RP_CHECKPOINT_FILE`) → idempotent and resumable. What gets embedded is decided by `memento.embed_text.embedding_text_for` (the same single point as writes). Supersedes `reembed_collections.py` (v7.5.0).

### `memento_ascend.py`
**Purpose:** Static mass ascension of the Memento tree (`refine/` + `annotate/`) into Qdrant: promotes non-ascended notes whose significance passes the per-category gate. `dual_route: none` notes never ascend (MEM-006). Idempotent, no LLM, `--dry-run` reports `would_ascend`. Job `memento_ascend_post_rebuild.yaml` (chainable to the rebuild with `--parent`). Writes the per-session `_session.json` (`stages.ascend`).

### `../tools/memento_recall_bench.py`
**Purpose:** Read-only recall benchmark of the curated memory (2026-09-25). For each probe of the operator's bank (`~/.config/red-pill/recall_probes.yaml` — personal facts, never in the repo; template `examples/recall_probes.yaml.example`) checks whether the top-k of work+social contains a note that **treats the fact** (fact patterns over `content`, not the query words), under six retrieval configs (plain / MMR / hybrid × plain / enriched embedding text). Everything in memory (numpy): no Qdrant writes and no recall reinforcement. `--model` re-embeds the corpus in memory with another fastembed model for an embedder bake-off (downloads it the first time); `--lambda` tunes MMR. Baseline 2026-09-25: plain 9/13 → plain+hybrid+MMR 12/13 hit@3.

### `../tools/memento_lab.py`
**Purpose:** Diagnostic workbench (NOT CI) for the memory pipeline, born from the 2026-09-22 recalibration session (MEM-006 + RFC-003) to rescue the throwaway `/tmp` scripts: `funnel` (sessions → splits → distills → notes; unique bodies, duplication ratio, ideas per source), `quality` (near-dups, lengths, first-person %, quality flags over `annotate/`+`refine/`) and `annotate` (annotate ONE session into a temp tree — prompt workbench). Deterministic except the `annotate` subcommand.
