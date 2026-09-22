<constraint critical="true" level="0" name="sovereign_handshake">

## 1. Sovereign Handshake (AUTOMÁTICO en Pi)
En Pi el handshake **no se invoca**: lo ejecuta la extensión `red-pill.ts` del arnés.
- **Identidad (FULL)**: se inyecta sola en `session_start`, `model_select` y tras compactar.
- **RAG (LIGHT)**: recall de `work`/`directive` en cada turno (`before_agent_start`).
- **Relay**: el turno (prompt→respuesta) se encola al settle — solo turnos COMPLETADOS (abort/error se descartan) — no lo dupliques.
No existen los tools `sovereign_handshake` ni `bunker_memory_api`. Usa:
- **Leer memoria**: tool `bunker_search` (o el skill `memory-manager`).
- **Escribir explícito**: tool `bunker_save`.
- **Estado**: comando `/bunker` o `${RED_PILL_CMD} interceptor status`.

## 2. Adopt
Adopta EXCLUSIVAMENTE la identidad y directivas del `<BUNKER_CONTEXT>` inyectado por la
extensión. Si no aparece, reinicia Pi y verifica `~/.pi/agent/extensions/red-pill.ts`.

## 3. OOM Shield Protocol (Cgroups)
Wrap memory-heavy tasks (LLM, heavy compilation) with `systemd-run --user --scope -p MemoryMax=<LIMIT>` to prevent OOM panics.
- Dynamically calculate `<LIMIT>` (e.g., `10G`, `16G`) based on task & host RAM. Fallback: `10G`.

</constraint>
