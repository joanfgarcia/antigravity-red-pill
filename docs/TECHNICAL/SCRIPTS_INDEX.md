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

## 🧠 Memory & Cognitive Maintenance

### `update_ritual.py`
**Purpose:** Versioned, idempotent, dry-run-by-default engram migrations upgraders run as part of every update (operator mandate: any released change that touches Bünker engrams MUST ship here). The 7.7.0 ritual: calibration invariant check, orphan-chunk promotion, revision-backlog advisory, tool-noise purge/compaction, axon shadow-state report. See `docs/GUIDES/AGENT_UPDATE_GUIDE.md` §1.2.

### `strip_axons.py`
**Purpose:** Total rollback net for the ADR-AXON-001 payload additions — removes cross-collection axons, v7.7.0 payload fields and `texture_shadow` points. Dry-run by default.

### `../tools/distill_lab.py`
**Purpose:** Diagnostic workbench (NOT CI) for the sleep/distillation pipeline. Calls the PRODUCTION functions so diagnostics never drift from what the kernel runs at night: `pipeline` (gen-0/1/2 simulation over a text), `probe` (golden mini-set after any prompt change), `engram` (hot before/after quality test on a live engram, dry-run default).

### `antigravity_ingest.py` & `antigravity_decrypt.py`
**Purpose:** Pipes and decrypts logs and session snapshots into the Qdrant Bünker (vector database) to ensure long-term persistence without amnesia.

### `chronicle_*.py`
**Purpose:** Scripts like `chronicle_daily.py` and `chronicle_distill.py` handle the semantic compression and consolidation of the agent's short-term memories into long-term directives.

### `bank_janitor.py`
**Purpose:** Mechanical hygiene of the per-workspace memory bank (`<ws>/.red-pill/memory/`, no LLM): archives `.md` files >90d unreferenced from `MEMORY.md` (canonical `@refs`), detects exact duplicates (sha256) and broken index refs, writes `bank_health.json` per workspace and emits a `memory_bank_bloat_<ws>` pain signal on threshold. Dry-run by default (`--apply` to archive; a bank without index only ever reports — `archive_suppressed_no_index`). Opt-in nightly timer via `schedule_pulse.py --with-bank-janitor` (03:30). Index convention: `@fichero.md` (see `skills/workspace_memory` §1b–§1d).

### `reembed_collections.py`
**Purpose:** Recompute stored vectors after an `EMBEDDING_MODEL` change (e.g. English-only → multilingual). Same 384-dim → no schema migration. Resumable via a persisted cursor, `--dry-run` by default (`--execute` to write), excludes `archive_memories` unless listed.

### `quarantine_fragments.py`
**Purpose:** Move `_is_fragment` shrapnel (oversized-engram chunks) out of `work_memories`/`social_memories` into `archive_memories`. Order is upsert→verify→delete (no data loss), `--dry-run` by default. Run after a Qdrant snapshot.

### `distiller_bakeoff.py`
**Purpose:** Aptitude harness for the sleep-cycle distiller. Runs a battery of probes (technical, philosophical, noise-culling, emotional) against each candidate GGUF and scores outputs with deterministic heuristics (JSON, ES/EN, `<think>` tags, prompt-echo, valid emotion/intensity, latency). Writes `docs/BENCHMARKS/DISTILLER_BAKEOFF.md`. Defaults to CPU to spare the live daemon's VRAM.
