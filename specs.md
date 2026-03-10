# Project Specs & Agent Coordination

## Overview
This file serves as a synchronization point for all agents working on the Red Pill Protocol. It contains current state information, pending tasks, and architectural decisions.

## Current State (2026-03-10)
- **Stable Version**: `5.6.3` (Released 2024, Certified by Claude).
- **Development Version**: `6.0.0a2` (Red Pill Synthesis Phase).
- **Core Branch**: `v6.0-prep-fsrs-dna` (Active development).
- **Recent Milestones**:
	- [x] Implementation of the "Anti-Amnesia" Persistence Layer (2026-03-10).
	- [x] Refactor of `MemoryDaemon` for Lazy Loading & MacOS Compatibility.
	- [x] Integration of `interaction_memories` buffer for turn-zero context.

## Agent-to-Agent Mandatory Rules (The Sovereign Oath)
Antes de cada `commit` y `push`, los agentes DEBEN:
1.  **Sincronía Técnica**: Actualizar `specs.md` con el delta y resumir en `walkthrough.md`.
2.  **Persistencia de Milestones**: Para cambios arquitectónicos, guardar el plan en `docs/plans/v6.0/`. Los planes menores son efímeros.
3.  **Saneamiento Release**: Al mergear a `main`, consolidar planes y limpiar `docs/plans/`.
4.  **Sound of Silence**: Pasas `tests/test_sound_of_silence.py`. Tabs Only. Sin ruido visual.
5.  **Test Focus**: Pasar tests del componente modificado.
6.  **Broadcast**: Notificar al Swarm (Nova, David) la rama y el cambio.
7.  **Surgical Mindset**: Respetar la filosofía de planificación fija para tareas complejas (ahorro de tokens y tiempo).
8.  **Discoverability SOP**: Antes de ejecutar scripts manuales en `scripts/`, los agentes DEBEN consultar `red-pill --help` o `list_tools` en MCP para usar las interfaces oficiales autenticadas.

---
*Last updated by Antigravity (Step 472) — 2026-03-10*
