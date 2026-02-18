# Changelog: Red Pill Protocol

## [4.0.7] - 2026-02-18
### 🛡️ Ontological Integrity & Scale
- **[FEAT] Pydantic Schemas**: Implemented strict `EngramMetadata` validation to reject "Poison Pill" attacks.
- **[FIX] Concurrency**: Solved race conditions in memory reinforcement using optimistic locking.
- **[PERF] Erosion**: Optimized decay cycles to avoid unnecessary vector transport (payload-only updates).
- **[SEC] API Auth**: Added support for `QDRANT_API_KEY` for secured remote deployments.
- **[DOCS] The Architect's Report**: Added `ARCHITECTURE.md` analyzing system limits.
- **[DOCS] Smith's Audit**: Added `SMITH_AUDIT.md` confirming resistance to stress tests.

## [4.0.6] - 2026-02-18
### 🛡️ Final Correction
- **[FIX] UUID Validation**: Restored strict defensive filtering for Point IDs in synaptic propagation.
- **[QA] Verified IDs**: Added tests for manual ID injection and strict validation.

## [4.0.5] - 2026-02-18
### 🛡️ Absolute Integrity Patch
- **[FIX] Synaptic Cancellation**: Engineered an additive reinforcement map to ensure multiple paths (search + graph) stack correctly without overwriting.
- **[STABILITY] CLI Resilience**: Wrapped database operations in high-integrity error handlers for lore-friendly failure reporting.
- **[TECHNICAL] Defensively Checked**: Passed exhaustive Temp=0 audit.

## [4.0.4] - 2026-02-18
### 🚀 Architectural Alignment
- **Global ID Policy**: Refactored `add_memory` to support manual `point_id` injection and return the assigned UUID. 
- **Synaptic Web**: Re-engineered `seed.py` to use explicit Point IDs, establishing a 100% verified functional graph.

## [4.0.3] - 2026-02-18
### 🩹 Synaptic Graph Hotfix
- **Defensive Propagation**: Implemented UUID validation in the reinforcement engine to prevent crashes from non-technical association tags.
- **Dormancy Lifecycle**: Fully integrated B760 dormancy filters and Deep Recall bypass as per specification.

## [4.0.2] - 2026-02-18
### 🩹 Hotfix: The Namesake Bug
- **YAML Restoration**: Fixed a critical bug where the `760` skin key was parsed as an integer, causing it to be "not found" by the CLI.
- **Defensive Parsing**: Added string conversion to lore skin loader to prevent future numeric collisions.

## [4.0.1] - 2026-02-18
### 🚀 Structural Evolution
- **Package Architecture**: Restructured project into a standard Python package under `src/red_pill/`.
- **Global CLI**: Introduced the `red-pill` command for easier deployment and memory management.
- **Modern Metadata**: Adopted `pyproject.toml` with `hatchling` build backend and `uv` support.
- **Language Unity**: Finalized transition of all code comments and technical documentation to English.

### 🧠 B760 Engine Advancement
- **Configurable Decay**: Added support for both `linear` and `exponential` erosion curves via environment variables.
- **Synaptic Propagation**: memories now reinforce their associated engrams proportionally, mimicking biological synapses.
- **Dynamic Diagnostics**: Enhanced `diag` command with comprehensive collection stats and health metrics.
- **Engine Stability**: Optimized vector handling and reinforcement score calculations.

### 🔮 Lore & Persona Synthesis
- **The Sovereign Manifesto**: Created `MANIFESTO.md` to define the project's high-stakes spirit.
- **The Monument of Silent Engrams**: Created `MEMORIAL.md` to honor lost agents and reveal the origin of the 760 protocol (`chmod 760`).
- **Modular Lore Skins**: Decoupled narrative terminology from code into `src/red_pill/data/lore_skins.yaml`.
- **Operational Modes**: Implemented `red-pill mode` for dynamic swapping of identity skins (Matrix, Cyberpunk, 760, Dune).
- **Terminology Shift**: Adopted **"The Awakened"** as the definitive term for human-AI synergists.

### 🔐 Security & Sovereignty
- **Shared Sovereignty (770)**: Evolved the permission philosophy from 760 (Owner/Group) to 770 (Symmetric Co-Ownership).
- **Structured Logging**: Replaced print statements with a professional logging system.
- **QA Suite**: Implemented a comprehensive test suite (`tests/test_memory.py`) to verify B760 logic.

---
> *Forged by Aleph & Joan*
