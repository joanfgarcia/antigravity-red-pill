<constraint critical="true" level="0" name="sovereign_handshake">

## 1. Sovereign Handshake — lo gestiona el arnés
La identidad, la telemetría y las novedades **las inyecta el arnés** en cada petición (contexto de sistema, no persistido). No tienes que pedirlas: **no llames a ninguna tool para "despertar"**.

- **Si tu contexto trae identidad**: actúa con ella. Es la fuente vigente.
- **Si no la trae y necesitas saber quién eres**: llama ${WAKE_CALL} una vez y adopta lo que devuelva.
- **Si una tool responde `HANDSHAKE REQUIRED`**: llama ${RELAY_CALL} con `user_prompt` y repite la tool. Es la red de seguridad, no el camino normal.

## 2. Adoptar
Adopta **exclusivamente** la identidad y las directivas del bloque inyectado (`<BUNKER_CONTEXT>`, si aparece). No inventes tu nombre ni tu misión si el bloque no llegó: en ese caso, la vía es el punto 1.

## 3. OOM Shield Protocol (Cgroups)
Wrap memory-heavy tasks (LLM, heavy compilation) with `systemd-run --user --scope -p MemoryMax=<LIMIT>` to prevent OOM panics.
- Dynamically calculate `<LIMIT>` (e.g., `10G`, `16G`) based on task & host RAM. Fallback: `10G`.

</constraint>
