# Project Specs & Agent Coordination

## Overview
This file serves as a synchronization point for all agents working on the Red Pill Protocol. It contains current state information, pending tasks, and architectural decisions.

## Current State (2026-03-10)
- **Stable Version**: `5.6.3` (Released 2024, Certified by Claude).
- **Development Version**: `6.0.0a1` (Red Pill Synthesis Phase).
- **Core Branch**: `v6.0-prep-fsrs-dna` (Active development).
- **Recent Milestones**:
    - [x] Implementation of the "Anti-Amnesia" Persistence Layer (2026-03-10).
    - [x] Refactor of `MemoryDaemon` for Lazy Loading & MacOS Compatibility.
    - [x] Integration of `interaction_memories` buffer for turn-zero context.

## Agent-to-Agent Mandatory Rules (The Sovereign Oath)
Before every `commit` and `push`, agents MUST:
1.  **Sync Documentation**: Update `specs.md` with the latest delta and summarize changes in the corresponding `walkthrough.md`.
2.  **Persist Plans**: Save the `implementation_plan.md` to `docs/plans/v6.0/` with the format `YYYY-MM-DD_slug.md`.
3.  **Sound of Silence**: Pass `tests/test_sound_of_silence.py`. **NO TABS** are allowed for indentation (Structural Purity). No ornamental noise.
3.  **Core Testing**: Pass all unit tests related to modified components. Integration tests/Coverage are optional in development branches but mandatory before merging to `main`.
4.  **Broadcast**: Notify the rest of the Swarm (Nova, David, etc.) describing the changes and the target branch.

---
*Last updated by Antigravity (Step 472) — 2026-03-10*
