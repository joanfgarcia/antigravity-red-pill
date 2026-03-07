# Project Specs & Agent Coordination

## Overview
This file serves as a synchronization point for all agents working on the Red Pill Protocol. It contains current state information, pending tasks, and architectural decisions.

## Current State (2024-05-22)
- **Stable Version**: `5.6.3` (Certified by Claude).
- **Development Version**: `6.0.0-PREP` (FSRS & Contributor PRs).
- **Branch Strategy**:
    - `main`/`master`: Targeted for `5.6.3` certification.
    - `v6.0-prep-fsrs-dna`: Contains experimental FSRS logic and merged PRs from David & Nova.

## Agent-to-Agent Notes
- **To All Agents**: The `5.6.3` version is the one that received the "Unconditional Production Ready" certification. Avoid merging uncertified features (like FSRS or MacOS fixes) into the 5.6.3 release line.
- **Memory Management**: We are considering whether "Fast Memory" (interaction logs) should be in a separate collection or integrated into existing ones. For now, keep them in `work_memories` but flagged if possible.
- **Sleep Logic**: Improved "Sleep" (Sueño) logic is currently in the `6.0.0-PREP` branch. It needs verification before being considered for a stable backport.

## Pending Actions
- [ ] Finalize `5.6.3` release tags.
- [ ] Review "Fast Memory" implementation plan.
- [ ] Audit `6.0.0-PREP` for security before merging to stable.

---
*Last updated by Antigravity (Step 769)*
