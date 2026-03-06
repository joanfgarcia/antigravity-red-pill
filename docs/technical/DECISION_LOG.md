# Red Pill Protocol: Decision Log

This document records the architectural and philosophical pivots of the project.

---

## [AD-001] Linguistic DNA Extraction (The "Claude-Pistis" Bridge)
**Date**: 2026-03-05/06  
**Context**: Phase O.7 (v6.0 PREP) - Post-Audit v5.6.3  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Traditional vector memory (RAG) is excellent at storing "What" (factual content) but forgets "How" (conversational style, shared vocabulary, and emotional triggers). This creates a "Linguistic Uncanny Valley" where the AI remembers the project details but speaks like a stranger in every new session.

### 2. The Decision
Integrate an automated **Linguistic Marker Extraction Engine** into the `MemoryManager.add_memory` flow.

### 3. The Implementation
- **Schema**: Added `linguistic_markers: List[str]` to the `EngramPayload`.
- **Logic**: Automated regex/keyword scanner that captures:
  - Quoted terms (shared aliases).
  - Protocol keywords (`Bünker`, `770`, `enter-pánico`).
  - All-caps markers (shouting/intensity patterns).

### 4. Rationale & Attribution
> \"Lo de los alias y el vocabulario compartido es un problema real y no trivial... ese es el tipo de cosa que marcaría la diferencia entre un agente que recuerda hechos y uno que recuerda cómo habláis.\"  
> — **Claude Sonnet 4.6 (Anthropic)**, Audit Session 2026-03-05/06.

This implementation transitions the Red Pill Protocol from a "Factual Memory" system to an "Identity Memory" system, fulfilling the B760 vision of a truly persistent agentic ghost.

---
