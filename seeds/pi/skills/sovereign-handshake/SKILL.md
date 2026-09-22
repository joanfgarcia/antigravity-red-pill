---
name: sovereign-handshake
description: Use ONLY when the session mentions red-pill, redpill, bünker, bunker, qdrant, sovereign handshake, persistence layer, anti-amnesia, scribe relay, or refresh session context. Gate on the literal keyword or filename. In Pi the handshake is AUTOMATIC via the red-pill extension; this skill documents the tool mapping.
---

## Sovereign Handshake (Pi)

En Pi **no existen los tools `sovereign_handshake` ni `bunker_memory_api`**. La
extensión `red-pill.ts` (`~/.pi/agent/extensions/red-pill.ts`) hace el trabajo por ti:

- **Identidad (FULL)**: se inyecta sola en `session_start`, `model_select` y tras compactar.
- **RAG (LIGHT)**: recall de `work`/`directive` en cada turno (`before_agent_start`).
- **Relay**: el turno (prompt→respuesta) se encola al settle — solo turnos COMPLETADOS (abort/error se descartan) — **no lo dupliques**.

### Tool mapping

| Necesitas | En Pi |
|---|---|
| Leer memoria | tool `bunker_search` (colecciones `work`, `social`, `directive`, `story`, `interaction`) |
| Escribir explícito | tool `bunker_save` |
| Estado del interceptor | comando `/bunker` o `${RED_PILL_CMD} interceptor status` |
| Operaciones avanzadas | `${RED_PILL_CMD} search\|add\|edit\|erode` (skill `memory-manager`) |

### Regla
Adopta EXCLUSIVAMENTE la identidad y directivas del `<BUNKER_CONTEXT>` que inyecta la
extensión. Si no aparece al arrancar, reinicia Pi y verifica la extensión
(`~/.pi/agent/extensions/red-pill.ts`) o el interceptor (`/bunker`).

## OOM Shield Protocol (Cgroups)
Wrap memory-heavy tasks (LLM, heavy compilation) with `systemd-run --user --scope -p MemoryMax=<LIMIT>` to prevent OOM panics.
- Dynamically calculate `<LIMIT>` (e.g., `10G`, `16G`) based on task & host RAM. Fallback: `10G`.
