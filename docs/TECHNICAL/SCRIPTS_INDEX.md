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

### `antigravity_ingest.py` & `antigravity_decrypt.py`
**Purpose:** Pipes and decrypts logs and session snapshots into the Qdrant Bünker (vector database) to ensure long-term persistence without amnesia.

### `chronicle_*.py`
**Purpose:** Scripts like `chronicle_daily.py` and `chronicle_distill.py` handle the semantic compression and consolidation of the agent's short-term memories into long-term directives.
