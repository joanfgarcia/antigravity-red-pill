# Anclaje red-pill ↔ Pi (pi-coding-agent)

Pi (`@earendil-works/pi-coding-agent`) **no soporta MCP**. El Búnker red-pill
vive detrás de su CLI (`red-pill search/add/interceptor …`) y de
`scripts/wake_up_v6.py`. El anclaje es una **extensión de Pi**
(`extensions/red-pill.ts`) que invoca ese CLI vía `uv run` desde el checkout y
expone la memoria del Búnker como herramientas y comandos de Pi.

## Regla de oro: el CLI no está en el PATH

`red-pill` no está en el PATH del harness (vive en `<repo>/.venv/bin/red-pill`).
La invocación estándar, usada por la extensión y por los skills, es:

```bash
uv run --no-sync --project <repo> red-pill <subcommand>
```

Los skills del repo la referencian con el placeholder `${RED_PILL_CMD}`; los
injectors la resuelven al sembrar.

## Qué siembra `scripts/inject/pi/inject.py` (reproducir el anclaje)

El adapter `scripts/inject/pi/` (autodetectado por `inject_cli.py`, igual que
opencode/claude-code) hace:

1. **Extension** → `~/.pi/agent/extensions/red-pill.ts` (con `${RED_PILL_DIR}` /
   `${UV}` resueltos). Pi auto-descubre `~/.pi/agent/extensions/*.ts`.
2. **Skills** → `~/.pi/agent/skills/` (dir único fusionado): copia `skills/`
   (genérico) y luego `seeds/pi/skills/` (override específico-IDE, gana). Los
   ficheros pisados por un override se saltan en la pasada genérica, así que el
   reseed converge e es idempotente. Los legados snake_case se prunean. Los
   overrides de Pi adaptan los skills que hablan MCP: `sovereign-handshake`,
   `workspace-memory`, `minion-delegation`, `job-manager`, `swarm-flow-manager`.
3. **Anchor** → `<workspace>/AGENTS.override.md`. Pi ≥0.87 carga
   `AGENTS.override.md` **en vez de** `AGENTS.md`/`CLAUDE.md` del mismo
   directorio: esto sombrea el ancla `claude-code-project` (que habla MCP) con
   texto propio de Pi (handshake automático, `bunker_search`/`bunker_save`).
   Semillas: `seeds/pi/anchors/<anchor>.md` (gana) → `seeds/anchors/<anchor>.md`
   (genérico). El workspace se resuelve de `--workspace` → `WORKSPACE_ROOT`
   (`.env`); sin ninguno, el ancla se omite.
4. **No toca** `~/.pi/agent/settings.json` (proveedor/modelos = del operador)
   ni configura MCP.

## Verificación tras el seed

1. Reiniciar Pi: sin warnings `[Skill]` en la carga (loader valida nombres
   kebab-case).
2. Aparece `[BÚNKER IDENTIDAD — resync completo]` al inicio.
3. `/bunker` responde el estado del interceptor.
4. `bunker_search` devuelve resultados del Búnker.
5. Pi carga `<ws>/AGENTS.override.md` y NO `CLAUDE.md`: en `pi --mode json` el
   system message trae `project_instructions path="<ws>/AGENTS.override.md"` y no
   debe contener `MUST call the `sovereign_handshake` tool`.
6. Desactivar temporalmente: `RED_PILL_ENABLED=0`.

## Fuente chronicle

`src/red_pill/chronicle_sources/pi.py` (`PiSourcePlugin`) lee las sesiones JSONL
de `~/.pi/agent/sessions/` (formato v3 verificado contra pi 0.85.1: header
`{"type":"session",...}`, entries con `timestamp` ISO, roles
user/assistant/toolResult). `toolResult` se compacta a `[TOOL: <name>]`. Está
activada por defecto vía `CHRONICLE_ARCHIVE_SOURCES` (incluye `"pi"`) →
`memento_migrate` (etapa `memento` del chronicle diario) la vuelca al árbol
Memento con `export_raw`/`load_raw` (backup `raw/` + `--from-raw`), y
`memento_agentic` la destila/refina. Desde 2026-09-11 la ingesta a
`archive_memories` (Qdrant) está retirada del pipeline.

## Uso agéntico (minion backend `pi`)

`PiBridge` (`src/red_pill/swarm/bridges/pi.py`, backend `"pi"`) ejecuta prompts
headless con `pi --mode json` (sesiones persistidas → las archiva la fuente
chronicle; la extensión inyecta identidad/RAG y hace el scribe si está
desplegada):

```jsonc
// swarm_orchestrator_api → run_agent_task
{ "prompt": "En el workspace X, haz Y y reporta Z.",
  "backend": "pi", "workspace": "/abs/path", "async_mode": true }
```

También como `agentic_job` con `"backend": "pi"` en el payload, o fijando
`IDE_BACKEND=pi`. Requiere un proveedor/modelo configurado en
`~/.pi/agent/settings.json` del operador.