<constraint critical="true" level="0" name="sovereign_handshake">

## 1. Sovereign Handshake (AUTOMÁTICO en Pi)
En Pi el handshake **no se invoca**: lo sirven las extensiones del arnés.
- **Identidad (FULL)**: la inyecta `red-pill-context.ts` por el hook `context` — **no persistida**,
  así que sobrevive a la compactación y no engorda el transcript.
- **RAG (LIGHT)**: recall de `work`/`directive` en cada turno (`before_agent_start`).
- **Relay**: el turno (prompt→respuesta) se encola al settle — solo turnos COMPLETADOS (abort/error se descartan) — no lo dupliques.
Los tools del kernel llegan por MCP (perfil `codemode`: no se declaran; se alcanzan por script). Si necesitas memoria:
- **Leer memoria**: `red-pill search "…"` (CLI) o `redpill_call` con
  `bunker_memory_api` / `action: recall`.
- **Estado**: `red-pill interceptor status`.

## 2. Adopt
Adopta EXCLUSIVAMENTE la identidad y directivas del `<BUNKER_CONTEXT>` inyectado por la
extensión. Si no aparece, reinicia Pi y verifica `~/.pi/agent/extensions/red-pill.ts`.

## 3. OOM Shield Protocol (Cgroups)
Wrap memory-heavy tasks (LLM, heavy compilation) with `systemd-run --user --scope -p MemoryMax=<LIMIT>` to prevent OOM panics.
- Dynamically calculate `<LIMIT>` (e.g., `10G`, `16G`) based on task & host RAM. Fallback: `10G`.

</constraint>
