# Project Specs & Agent Coordination

## Overview
This file serves as a synchronization point for all agents working on the Red Pill Protocol. It contains current state information, pending tasks, and architectural decisions.

## Current State (2026-03-16)
- **Stable Version**: `5.6.3` (Released 2024, Certified by Claude).
- **Development Version**: `6.1.0a3` (Audit - **Development Version**: `6.0.0a3` (Sovereign Synthesis Phase). Foundation Prep).
- **Core Branch**: `v6.0-prep-fsrs-dna` (Active development).
- **Recent Milestones**:
	- [x] Implementation of the "Anti-Amnesia" Persistence Layer (2026-03-10).
	- [x] Refactor of `MemoryDaemon` for Lazy Loading & MacOS Compatibility.
	- [x] Integration of `interaction_memories` buffer for turn-zero context.
	- [x] Evolution of ACI Protocol: Multi-stage adaptive questionnaire (2026-03-10).
	- [x] Integration of Cognitive Profile: "Fortunate Mind" pattern recognition.
	- [x] **Agentic SNA Integration**: Unified `configure_neuro_agentic_tuning` MCP tool and ACI+SNA Ritual (2026-03-12).

## Agent-to-Agent Mandatory Rules (The Sovereign Oath)
Antes de cada `commit` y `push`, los agentes DEBEN:
1.  **Sincronía Técnica**: Actualizar `specs.md` con el delta y resumir en `walkthrough.md`.
2.  **Persistencia de Milestones**: Para cambios arquitectónicos, guardar el plan en `docs/plans/v6.0/`. Los planes menores son efímeros.
3.  **Saneamiento Release**: Al mergear a `main`, consolidar planes y limpiar `docs/plans/`.
4.  **Sound of Silence**: Pasas `tests/test_sound_of_silence.py`. Tabs Only. Sin ruido visual.
5. **Test Focus**: Pasar tests del componente modificado.
6. **Agent Safety (ASR-770)**: Respetar estrictamente el `docs/CORE/AGENT_SAFETY_PROTOCOL.md`. Prohibido el spam de permisos y herramientas en paralelo durante el descubrimiento.
7. **Broadcast**: Notificar al Swarm (Nova, David) la rama y el cambio.
8. **Surgical Mindset**: Respetar la filosofía de planificación fija para tareas complejas (ahorro de tokens y tiempo).
9. **Discoverability SOP**: Antes de ejecutar scripts manuales en `scripts/`, los agentes DEBEN consultar `red-pill --help` o `list_tools` en MCP para usar las interfaces oficiales autenticadas.

---
*Last updated by Antigravity (Step 1311) — 2026-03-10*
