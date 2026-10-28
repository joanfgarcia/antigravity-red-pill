# Red Pill Protocol: Decision Log

This document records the architectural and philosophical pivots of the project.

---

## [AD-088] Engramas génesis: resolver placeholders de ruta al sembrar
**Date**: 2026-10-27
**Status**: ACCEPTED & IMPLEMENTED.
**Context**: El handshake devolvía una directiva con `${AGENT_CORE_DIR}` literal (`Git Golden Rule … EXCEPTION — the DESK (${AGENT_CORE_DIR})`). No era un fallo de sustitución del handshake ni de `AGENTS.md`: **el texto vive en código** (`src/red_pill/seed.py`, engrama `ID_DIR_GIT_RULE`) y se sembraba en `directive_memories` **sin resolver**, así que el agente leía una ruta inexistente en vez del desk real.
**Decision**:
1. `seed._render_paths()` resuelve `${AGENT_CORE_DIR}` → `core.paths.get_agent_core_root()`, y `${REDPILL_DIR}`/`${IA_DIR}` → `get_bunker_root()`, en el momento de sembrar (`inject_genesis`).
2. Se aplica a **todos** los engramas génesis (no sólo al de git), para que cualquier placeholder futuro en esos textos no vuelva a colarse.
3. `inject_genesis` upserta por `point_id`, así que re-sembrar (`red-pill seed`) **converge** instalaciones ya existentes sin migración aparte.
**Alternatives**: (a) editar el texto del engrama a mano en Qdrant — no sobrevive a un reinstall, descartado; (b) dejar el placeholder y documentarlo — el agente seguiría leyendo una ruta falsa; (c) hardcodear la ruta del desk — rompe la portabilidad y la soberanía de rutas.
**Rationale / Evidence**: Antes: `read_core_directives` devolvía `${AGENT_CORE_DIR}` y `grep` localizaba el literal en `seed.py:181` (único `${…}` del módulo). Después de `red-pill seed`: el engrama dice `EXCEPTION — the DESK (<ruta del desk resuelta>, Aleth_Core)` y `read_core_directives` ya no contiene el placeholder. Tests nuevos: `_render_paths` resuelve el desk y ningún engrama génesis se siembra con `${`. `ruff` limpio; `tests/test_seed.py` 12 passed.
**Consequences**: Un install limpio desde cero escribe la ruta real (mismo código que el re-seed; el fallo era determinista en el texto, no dependiente del entorno). Cualquier directiva génesis futura con `${…}` se resolverá sola. `ID_IDENTITY`, `ID_PACT_*` y el resto no cambian.

---

## [AD-087] OpenCode sólo V2: siembra, handshake exigido por el arnés y MCP resiliente
**Date**: 2026-10-27
**Status**: ACCEPTED & IMPLEMENTED.
**Context**: Tras migrar a OpenCode V2 la identidad dejó de llegar al modelo y el agente "olvidaba" invocar el handshake. Tres causas encadenadas: (a) V2 **no** carga `instructions: ["RED_PILL.md"]` (ruta relativa ignorada en silencio); (b) el arnés sólo tenía un recordatorio en prosa, así que el handshake dependía de que el modelo se acordara (3/11 turnos en una sesión real); (c) reiniciar `redpill-mcp.service` dejaba a **todas** las sesiones del IDE con `Session terminated` hasta reiniciar la app.
**Decision**:
1. **Sólo V2+**. Las instrucciones globales se siembran en `~/.config/opencode/AGENTS.md` (carga nativa en cualquier workspace) y el seed V1 consolidado (`seeds/opencode/instructions/RED_PILL.md`) se **elimina del árbol**: su handshake mandaba llamar `swarm_orchestrator_api → interceptor_rp` y era el fallback de los inyectores. `seeds/anchors/*.md` es la única fuente y un anchor ausente **aborta** la siembra (`Siembra incompleta`).
2. **Gate de versión único** (`scripts/opencode_version.py::support_error`): ¿existe opencode? → ¿qué versión? (`--version`, `.deb`, override de env) → **exactamente v2**. v1 (sólo migración), v3+, desacuerdo CLI/paquete o versión indeterminable → aborto con mensaje y sin tocar nada. El precheck corre antes de cualquier escritura; `--remove` no se bloquea.
3. **Handshake exigido por el arnés**, no por la memoria: `session.hook("context")` inyecta el recordatorio en **cada** petición (no persistido → inmune a la compactación) y `tool.hook("execute.before")` niega cualquier tool hasta el handshake del turno (reset en cada `prompt`; fail-open a los 3 rechazos; sub-sesiones exentas). El gateway de Code Mode (`execute`) no se gatea y **acredita** el turno si su argumento menciona el handshake, mirando el **evento completo** (`input` llega vacío y `?? args` no lo veía).
4. **Bridge sólo V2**: fuera `--dir` (no existe en V2; rompía los jobs), `--attach` (siempre `--server`) y `--variant` (embebido en `-m provider/model#variant`). Sin detección de versión en el bridge.
5. **MCP compartido resiliente**: backend `stateless=True` (sin estado por conexión; la identidad viaja en cada request vía `X-RedPill-Proxy`) y proxy con **conexión por petición** + un reintento si el transporte falla.
6. **Contrato de identidad explícito** en el anchor (v4): Step 0 con `"is_new_session": true` (sin él el payload es un esqueleto sin `CORE_RULES`) y regla **«Never truncate»** (la identidad sólo viaja como retorno del handshake; un `len=…`/`slice` la deja fuera de contexto).
**Alternatives**: (a) mantener V1 con gates por versión — descartado por el Operador: V1 sólo como migración; (b) inyectar la identidad por un canal oculto del plugin — imposible: el plugin no tiene acceso MCP; (c) sesión MCP viva + reconexión manual — el reinicio del backend seguía orfanizando clientes.
**Rationale / Evidence**: Siembra en sandbox limpio: 36 bloques, 6 anchors (v3/v2/v5/v3/v2/v1), cero `interceptor_rp`, idempotente; `--remove` sin restos (salvo `opencode.jsonc`, por diseño). Gate verificado: v1/v3/indeterminable → rc 3 sin escribir. Handshake en vivo: sin `is_new_session` 1.328 chars sin `CORE_RULES`; con él 8.345 chars con 18 directivas. Job agéntico real S6.2 `COMPLETED` (`S62 CONTINUITY=… LEG=job:… MISSION=repo:next`). Suite: `3566 passed, 16 skipped, 3 xfailed`; `ruff check .` limpio.
**Consequences**: El repo asume OpenCode v2 (probado 2.1.4 y 2.2.0); una v3 exigirá su propia verificación antes de resembrar. Los hosts ya sembrados re-splican el anchor al subir `BLOCK_VERSION` (handshake 3→4). El MCP puede reiniciarse sin matar sesiones. El engrama `ID_DIR_GIT_RULE` se sembraba con `${AGENT_CORE_DIR}` crudo (texto en código sin resolver): corregido en `seed._render_paths` y re-sembrado en el Bünker — ver AD-088.

---

## [AD-086] Fase 3 — compactor/Telegram en producción (flags + E2E)
**Date**: 2026-10-26
**Status**: ACCEPTED & IMPLEMENTED.
**Context**: El compactor B-02 tenía código, retry/heartbeat, mapeo Telegram y safety net, pero seguía con flags OFF y sin E2E de producción. El primer E2E reveló dos fallos: el leg viejo de Telegram no se expiraba (callback no llamaba a `mark_for_deletion`) y Samantha devolvía “no hay mensajes” (prompt legacy `samantha_compact_user`).
**Decision**:
1. Flags live: `SESSION_COMPACTOR_ENABLED=true`, `TELEGRAM_SOUL_MAPPING_ENABLED=true`, `COMPACTOR_SCOPE=autonomous`, `COMPACTOR_SWEEP_ACTIVE_MIN=15`; `AUTO_HEAL_ENABLED=false`.
2. Telegram usa el presupuesto total (`TELEGRAM_COMPACTOR_CONTEXT_CHARS`) y el umbral `max(background, budget-reserve)`; el estimate excluye el turno `source=compactor`, así que un reset no se re-compacta a sí mismo. Samantha resume con el prompt operativo B-02, y el callback registra `reset(handoff)`, cambia el mapping persistente a la sesión nueva y marca el leg viejo para purga. El eco del resumen no se espeja otra vez.
3. Safety net `compact-sweep` active-only (timer 15 min) y hook externo con el mismo scope; el timer se instala con `scripts/schedule_pulse.py` (no se auto-habilita en una instalación existente). Las superficies Telegram y sweep comparten dedupe por continuity en la cola.
**Alternatives**: mantener el trigger legacy 16/4000 y el prompt antiguo — reproducía el resumen vacío; descartado.
**Rationale / Evidence**: E2E real `9457d640` → `54d7ae98` (continuidad `2aab2ac3`), leg viejo `expired`/nuevo `active`, `session_compactions` `5d8693da` completed. Primer E2E `e2e-fase3` expuso los dos fallos; corregidos. `pytest -q` → `3494 passed, 15 skipped, 3 xfailed`; `ruff` y `mypy` limpios.
**Consequences**: Fase 3 operativa con flags live; el interactivo queda fuera por `COMPACTOR_SCOPE=autonomous`; el timer sweep se instala con `scripts/schedule_pulse.py` y no se auto-habilita; el auto-heal global es report-only (AD-085), con heals manuales disponibles.
## [AD-085] Auto-Healer del wake en report-only
**Date**: 2026-10-26
**Status**: ACCEPTED & IMPLEMENTED.
**Context**: El wake/SentinelAuditor detectó un error mypy en `local_minion.py`; el `auto_heal_ritual` usó el `HealerMinion` local (EdgeEngine, `qwen2.5-coder-7b-instruct-q4_k_m.gguf`, llama.cpp 8192) para “corregirlo” y dejó un guard incorrecto (`... if mirror is not None else None`) que no resolvía el mypy y podía dejar `turns=None`. El Operador pidió que el wake/auditor solo reporte.
**Decision**:
1. `AUTO_HEAL_ENABLED` default **False**: `auto_heal_ritual` regresa sin editar (ruff/HealerMinion); `SyntaxGuardCheck.heal` no restaura desde git; el dispatch global de `SentinelAuditor` tampoco llama `plugin.heal()` (cubre servicios, SQLite y duplicados, no solo SyntaxGuard).
2. Los heals manuales (`heal_tissue`/`run_local_healer`) siguen disponibles como acción explícita del Operador.
3. El `SentinelAuditor` sigue reportando al MinionInbox/signals; el diagnóstico no se suprime y los findings quedan en el reporte cuando el heal está apagado.
**Alternatives**: (a) auto-heal con allowlist de ficheros — más complejo; (b) desactivar el healer entero — descartado (manual útil).
**Rationale / Evidence**: El modelo local `qwen2.5-coder-7b-instruct-q4_k_m.gguf` (EdgeEngine) introdujo el guard incorrecto; mypy seguía fallando; el fix correcto se hizo a mano. Tests de report-only del ritual, del SyntaxGuard y del dispatch global del Sentinel; `ruff` limpio.
**Consequences**: El wake ya no edita código; los signals/reportes quedan para el Operador. El HealerMinion local sigue disponible manualmente; el auto-heal se reactiva con `AUTO_HEAL_ENABLED=true`.

---

## [AD-084] D23-SCORE v0.1 — auto-revisor con modos off/review/semi/auto
**Date**: 2026-10-25
**Status**: ACCEPTED & IMPLEMENTED.
**Context**: D23 v0 (AD-083) dejó la revisión en el Operador (`review_decision`/`moderate_note` + bandeja), sin revisor autónomo. El Operador pidió un revisor con modos y un filtro para no revisar todo a mano, manteniendo la última palabra en high/retract.
**Decision**:
1. **Modos** (`D23_REVIEW_MODE`, default `off`): `off` solo Operador; `review` el revisor sugiere (`suggest_review`, sin mutar); `semi` solo muta con `confidence=high` (el servidor lo exige; si no, `escalate`); `auto` decide low/medium y escala high/retract (siempre Operador). Las notas `sealed` y las `hidden/retracted` no son objetables y no se re-exponen en la bandeja.
2. **Job revisor** `d23_review` (`agentic_job`): se encola al crear la objeción si el modo no es `off`, con alma dedicada estable (`D23_REVIEWER_CONTINUITY_ID`), `parent_mission_id` de la D-obj, `originator=d23-review:<decision>` y `role=reviewer`; el prompt incluye nota/claim/evidence/severidad/estado/modo y las tools `suggest_review`/`review_decision`. El job registra un **leg** del revisor (`d23-review:<decision>`) en `session_registry` (se limpia si falla el encolado). Si hay review job, **solo el revisor asignado** puede sugerir/decidir, y el modo manda: `review` → `suggest_review`, `semi/auto` → `review_decision`.
3. **Modelo**: cascade OpenRouter `openrouter/~z-ai/glm-latest` → `openrouter/~deepseek/deepseek-pro-latest` → `openrouter/~z-ai/glm-flash-latest`; backend `opencode`, `effort: low`, `timeout: 240` en `configs/jobs/d23-review.yaml`. Los tres IDs se verificaron con `opencode run -m ... --pure` (rc=0), aunque `opencode models` no lista `openrouter`. La cascade propaga la identidad del job (`continuity_id`/`mission_id`/`originator`/`role`) al bridge.
4. **Persistencia y autoridad**: `decision_suggestions` (verdict/confidence/reason; una por revisor/D-obj), `decision_reviews` (job/mode/reviewer/confidence), evento interno `decision_suggested`; `list_decisions`/CLI muestran sugerencia, confianza, job y modo. `suggest_review` y `review_decision` exigen `reason`; `review_decision` exige `confidence`. El Operador resuelve escalated/high/retract con `moderate_note` (`hide`/`retract`→upheld, `restore`→dismissed; `flag` solo marca); `review_decision` no resuelve escalated. `moderate_note` exige `REDPILL_OPERATOR=1` en MCP **y** CLI.
5. **Límites aceptados (A-01)**: teatro local mono-operador/mono-UID; los agentes son de confianza operativa, no una frontera de seguridad. El job revisor conserva el toolbox MCP completo (las reglas del prompt no son allowlist); `suggest_review` no tiene rate-limit más allá de una fila por revisor/D-obj. Endurecerlo queda como trabajo futuro, no como garantía de v0.1.
**Alternatives**: (a) auto con high/retract incluidos — daría rango de Operador de facto al revisor; descartado; (b) usar `opencode`/`opencode-go` — más caro/cuota Go; descartado frente a OpenRouter; (c) un solo modelo sin cascade — pierde fallback barato.
**Rationale / Evidence**: `tests/test_d23_review.py` (18) + `test_d23_score`/`test_mission_events`/`test_mcp_server` → **144 passed**; más `test_swarm_bridges` (30) y `test_job_manager` (46) → **220** en la suite relevante; `ruff check` limpio. El tool `suggest_review` eleva el inventario MCP a 14. Validación live: `review` job `e9b84818` → `dismiss/high` con reason, D-obj **open** (sin mutar); `semi` job `5a31e653` → `uphold/high`, D-obj **upheld** y nota flaggeada; `auto` low job `276058e0` → `uphold/high` con `review_confidence=high` y reason; `auto` high job `07911fb7` → **escalate**. Los test notes quedaron retiradas, sin D-obj open/escalated; las filas de auditoría append-only permanecen.
**Consequences**: D23-SCORE v0.1 cerrada; `review`, `semi` y `auto` validados; live final en `auto` (high/retract siempre Operador). `D23_REVIEW_MODE` default `off`: el Operador lo activa en `.env` y reinicia `redpill-mcp`. La receta y los modos quedan versionados; los jobs revisores aparecen en la cola con su leg propio y la bandeja muestra su sugerencia/estado/job/confianza. El CLI `session moderate` exige `REDPILL_OPERATOR=1` y `--reason`. Los artefactos de test están resueltos (filas de auditoría/reportes de job permanecen; sin open/escalated).

---

## [AD-083] D23-SCORE v0 — objeciones, D-obj y moderación del tablón
**Date**: 2026-10-25
**Status**: ACCEPTED & IMPLEMENTED (v0; votos/score diferidos). El auto-reviewer/job `d23_review` se implementó en v0.1 (AD-084).
**Context**: `mission_events` era append-only pero solo tenía `objection` como señal advisory: no había estado de disputa, revisión ni retirada. D23-SCORE seguía abierta con el default “no retirada automática; objeción → D-obj; revisor independiente; Operador decide”.
**Decision**:
1. **D-obj** (`dynamic_decisions`): `decision_id`, nota objetivo, claim/evidence, `severity` (low|medium|high), `proposed_action` (flag|hide|retract), `state` (open|upheld|dismissed|escalated), `requires_operator`, TTL. Eventos `decision_*` append-only en `mission_events` como auditoría (no se renderizan en el tablón).
2. **Objeción**: `announce_intent(type=objection, target_event_id, severity, proposed_action, evidence)`; misma misión en v0; una por `(nota, objetor)`. `high` o `retract` nacen `escalated` (solo Operador); el resto `open` con TTL 24h.
3. **Revisor independiente**: `review_decision(decision_id, uphold|dismiss|escalate)`; rechaza al objetor y al autor de la nota. `uphold` = **flag** (nunca hide); `hide/retract/restore` solo Operador. `escalated` solo la resuelve el Operador; sin revisor en TTL → `escalated` (lazy al listar), nunca auto-oculta.
4. **Operador**: `moderate_note(event_id, flag|hide|retract|restore)` vía CLI `red-pill session moderate` (canal local) o MCP con `REDPILL_OPERATOR=1`. `hide/retract` resuelven las D-obj abiertas; `restore` las descarta.
5. **Bandeja**: tool `list_decisions` (pendientes, primero las que requieren Operador) + CLI `red-pill session decisions`; tool `review_decision`; `fetch_events` añade `note_status`/`open_decisions` (`[flagged]`, `[disputed:N]`) y filtra `hidden/retracted` salvo autor/Operador. La nota y su historial nunca se borran.
**Alternatives**: (a) votos + retirada automática — Sybil y un downvote coordinado pueden borrar una nota correcta (descartado en v0); (b) ocultar en el `uphold` del agente — demasiado poder sin Operador; (c) tabla mutable sin eventos — pierde auditoría.
**Rationale / Evidence**: `tests/test_d23_score.py` (10) + `test_mission_events`/`test_mcp_server` → **126 passed**; `ruff` limpio. CLI validada (`session decisions --json` → `[]`; `session moderate --help`). El MCP en marcha necesita reinicio para exponer los 3 tools nuevos; la CLI ya funciona.
**Consequences**: D23-SCORE v0 cerrada. Diferido a v0.1: votos/score, objeciones cross-misión y paneles. El auto-enqueue del job `d23_review` (revisor autónomo) se implementó en v0.1 (AD-084). El Operador conserva la última palabra y la bandeja evita que el seguimiento dependa de memoria manual.

---

## [AD-082] Janitor — retención de artefactos de estado y scratch de arneses
**Date**: 2026-10-25
**Status**: ACCEPTED & IMPLEMENTED.
**Context**: B-01h (journal externo) y S5 (results de jobs) escriben un fichero por turno/job sin retención; el Janitor no los cubría. Además, el scratch de los arneses (`/tmp/opencode`) queda fuera de `${RP_TMP_DIR}` y solo lo limpiaba el reinicio. Con automatización, ambos crecen lineales.
**Decision**:
1. **`state_artifacts_purge`** (30d): purga `state/external_turns/archive` y `state/jobs/results`. Nunca toca `external_turns/current` (turno en vuelo); solo considera `results` de jobs `COMPLETED` (los no terminales pueden reanudarse) y conserva el último result por misión (`jobs_results_keep_per_mission: 1`).
2. **`harness_scratch_purge`** (14d, opt-in): purga hijos de `paths` con mtime antiguo; nunca el directorio configurado, no sigue symlinks y rechaza `/` y `$HOME`. El seed deja `paths: []`; la instalación añade `/tmp/opencode`.
3. Config en `seeds/settings/janitor.yaml` y `${CONFIG_DIR}/janitor.yaml`; descubrimiento automático por `janitor_plugins/` (sin tocar el orquestador).
**Alternatives**: (a) borrar el journal tras importarlo — pierde auditoría si el import falla; (b) purgar por edad sin mirar el estado del job — puede borrar un result reanudable; (c) limpiar `/tmp` entero — mata scratch ajeno y no es competencia del kernel.
**Rationale / Evidence**: `tests/test_janitor_state_artifacts.py` (5 tests) + suite Janitor **34 passed**; `ruff` limpio. Ejecución real con la config viva: `state_artifacts_purge` 0 purgados (nada >30d), `harness_scratch_purge` 27 entradas escaneadas y 0 purgadas (nada >14d).
**Consequences**: deuda de disco cerrada para los artefactos nuevos. Los results de jobs fallidos/FRUSTRATED se conservan como evidencia (si acumulan, revisar política). `/tmp/opencode` sigue en ~498MB (`GVS5H` 483MB, de hoy): el plugin no lo tocará hasta los 14 días; se puede borrar a mano si no se necesita.

---

## [AD-081] RFC-INTEROP-003 S6.2 — E2E real: el hijo opencode hereda el alma
**Date**: 2026-10-25
**Status**: ACCEPTED & IMPLEMENTED (S6.2 validado en campo; S6.1/S6.3 ya estaban).
**Context**: S6.1 inyectaba `REDPILL_*` en los bridges externos, pero nunca se había ejecutado una etapa opencode real que demostrara que el **handshake del hijo** veía el alma del padre. Faltaba el E2E, no el cableado.
**Decision / Evidence**:
1. `agentic_job` `b0120626-e96f-45f8-9aba-50b86b7b48fe` (backend opencode, modelo `opencode-go/deepseek-v4.1-flash`) heredó del llamante `continuity_id=01a17389-8cf5-75d6-9220-6922ff654c20` y `parent_mission_id=repo:next` (canal de confianza, sin declararlo el modelo).
2. El hijo respondió: `S62 CONTINUITY=01a17389-… LEG=job:b0120626-… MISSION=repo:next`. El `LEG` es `job:<job_id>`, no el `opencode:<session>` del padre: el handshake del hijo ve el alma heredada.
3. El coro registró el leg `[job] b0120626` con `alma=01a17389`, `rol=job`, `misión=repo:next`; `MinionInbox`/`state/jobs/results/` guardan el resultado con identidad.
4. **Hallazgo colateral (modelo)**: el catálogo vivo (`model_catalog.yaml`) y las cascadas `.env` anunciaban `opencode-go/deepseek-v4-flash`, id que el proveedor ya no sirve (el primer intento, `09192498`, falló con `Model not found; did you mean: deepseek-v4.1-flash?`). Corregido a `opencode-go/deepseek-v4.1-flash` en catálogo, `.env`, recipes Forge (scout/triage/doc-anchor), ejemplo de catálogo y skill `dag`. El fallo queda documentado, no oculto.
5. **Hallazgo colateral (workspace)**: `cwd=` solo cambiaba el directorio del proceso; opencode creaba la sesión hija en su proyecto por defecto (`/home/joan`) y el agente habría operado fuera del workspace del job. Añadido `--dir <cwd>` en `OpenCodeBridge._run_opencode` + test unitario. Re-E2E `e3872ccf`: misma continuidad y sesión hija confirmada en `/tmp/opencode/s62-e2e` (cwd efímero intencional para la validación; el job ya completó). Además, `AgenticJobDriver.preflight` valida que un `cwd` declarado exista: si un job reanudable apunta a un directorio efímero ya limpiado, falla claro en vez de arrancar en otro workspace.
**Alternatives**: (a) validar solo con el fake de `test_interop003_s6.py` — no prueba el canal real (env→CLI→MCP→handshake); (b) usar `local-mini` — no cubre opencode; (c) confiar en el log del bridge — no prueba que el hijo lo *vea*.
**Consequences**: S6.2 cerrado. Test durable `tests/test_interop003_s6_e2e.py` (marcado `integration`, gated por `REDPILL_E2E_OPENCODE=1`; restaura el bridge al terminar). Deuda viva: E2E opcional de Claude/Pi (Claude no se resiembra por política de cuenta), y el bridge `opencode_session.json` sigue siendo un único fichero global (multi-sesión: gana el último turno; candidato a tocar en mensajería).

---

## [AD-080] B-01h — write-ahead en hooks externos (journal + import al espejo)
**Date**: 2026-10-25
**Status**: ACCEPTED & IMPLEMENTED (B-01h; E2E real/S6.2 pendiente).
**Context**: B-01j/B-01s persistían la intención en los caminos RedPill, pero Claude/opencode/Pi escribían el turno solo al cerrar. Un corte del proceso dejaba el prompt fuera del espejo y sin evidencia de turno pendiente.
**Decision**:
1. **Journal JSON atómico** por turno (`state/external_turns/current/<provider>__<session>.json`), escrito ANTES de invocar al modelo. Al cerrar se archiva con `completed`/`aborted`, respuesta (parcial) y motivo.
2. **Hooks**: Claude (`UserPromptSubmit`/`Stop`/`StopFailure`/`SessionEnd`), opencode (`chat.message`/`session.idle|execution.*`) y Pi (`before_agent_start`/`agent_before_settle|agent_settled`). `request_id` compartido entre inicio y cierre.
3. **Import**: `import_external_turns()` al despertar (`wake_up_v6`/`refresh_session_context`) y en `session pending`; resuelve `originator → continuity_id/misión` desde `session_registry`. Sin fila registrada, el journal se queda (no se inventa alma).
4. **Idempotencia**: `begin_turn`/`complete_turn`/`abort_turn` por `request_id`; un turno nuevo sin Stop archiva el anterior como `aborted/superseded`.
5. **Aislamiento**: los hijos lanzados por bridges ponen `REDPILL_TURN_JOURNAL_DISABLE=1` (el Job Manager ya persiste su intención); el journal es para sesiones externas del Operador.
6. **Límite**: no exactly-once de efectos cloud (B-04); una respuesta perdida queda `aborted`, no se resucita.
**Alternatives**: (a) SQL directo en cada lenguaje — schema duplicado y frágil; (b) exigir import de Python en los hooks — path/entorno roto; (c) mirror solo al Stop — pierde la intención si muere el proceso.
**Rationale / Evidence**: suite **3403 passed**, 13 skipped, 3 xfailed; `ruff`/`mypy` limpios. Tests: journal roundtrip/supersede, import completed/aborted, originator sin alma, hooks Claude, y env de journal desactivado en bridges.
**Consequences**: B-01h cierra el write-ahead externo sin acoplar los hooks al repo. Queda S6.2 (misión real multi-proveedor) como validación E2E.

---

## [AD-079] RFC-INTEROP-003 S6 — identidad de alma en arneses externos
**Date**: 2026-10-25
**Status**: ACCEPTED & IMPLEMENTED (S6.1/S6.3; S6.2 real E2E pendiente).
**Context**: S0-S5 propagaban la identidad a local-mini/local-tools y a las etapas command, pero opencode/claude/pi nacían sin `REDPILL_*`: el hijo no heredaba el alma y el handshake podía resolver otro cuerpo.
**Decision**:
1. **Env de confianza**: `identity_env` exporta solo IDs (`REDPILL_CONTINUITY_ID`, `REDPILL_MISSION_ID`, `REDPILL_PARENT_MISSION_ID`, `REDPILL_ORIGINATOR`, `REDPILL_ROLE`, `REDPILL_JOB_ID`). `REDPILL_MISSION_ID` es la misión del alma (`parent_mission_id`), nunca la de aislamiento del forge.
2. **Bridges**: `ClaudeBridge`, `OpenCodeBridge` y `PiBridge` aceptan la identidad en el constructor y la inyectan en el `env` del subproceso. OpenCode conserva `REDPILL_SCRIBE_DISABLE` para Telegram/captura.
3. **Callers**: `AgentMinion` y `AgenticJobDriver` pasan la identidad a bridges externos y cascadas (`CascadeBridge` la propaga a cada target).
4. **Sin alma**: no se exporta ningún `REDPILL_*` inventado; los jobs/callers legacy siguen igual (D-02/A-06).
5. **Límite**: S6.2 (E2E real con opencode) no se ejecutó en este corte; B-01h (write-ahead en hooks externos) sigue fuera.
**Alternatives**: (a) inyectar identidad en el prompt — spoof; (b) pasar env al MCP en vez del CLI — no cubre al hijo; (c) solo local-mini — deja el gap de S6.
**Rationale / Evidence**: suite **3398 passed**, 13 skipped, 3 xfailed; `ruff`/`mypy` limpios. Tests: env por bridge, `AgentMinion`, `AgenticJobDriver`, cascada y no-soul.
**Consequences**: el hijo opencode/claude/pi hereda el alma por canal de confianza. Quedan S6.2 (E2E real) y B-01h (hooks externos con `request_id` compartido).

---

## [AD-078] RFC-INTEROP-003 S4/S5 — mando, lease de misión y cierre con identidad (P3)
**Date**: 2026-10-25
**Status**: ACCEPTED & IMPLEMENTED (S0-S5; S6 opcional pendiente).
**Context**: S0-S3 daban identidad y visibilidad al job, pero cualquier alma podía pausar/matar/transferir el job de otra y el cierre no dejaba un resultado con autoría. P3 cierra el contrato de mando y el artefacto durable sin exigir alma a los jobs de sistema.
**Decision**:
1. **Lease de misión (S4.1/D-03)**: el alma la reclama en `job_submit`, `job_transfer`, `job_resume` o `job_checkpoint`; el job **no la adquiere**. Si el lease es de su alma, el job lo late (hilo cada 5 min) y lo cierra al terminar; si es de otra alma, ejecuta como spectator y no publica como orquestador (5.7.3).
2. **Autorización (S4.2/D-09)**: `job_pause`/`resume`/`kill`/`skip`/`transfer`/`checkpoint` exigen el `continuity_id` dueño o `REDPILL_OPERATOR=1`; los argumentos del modelo no autorizan. Un job sin alma conserva el comportamiento legado (D-02/A-06).
3. **Handoff y split-brain (S4.3/S4.4)**: `job_transfer` devuelve `continuity_id`/`parent_mission_id`/`originator`/`role`; `job_checkpoint`/`resume` comprueban el lease antes de mutar y rechazan una identidad inyectada en el checkpoint. `kill_task_ex` devuelve el estado previo real para no liberar el lease mientras el proceso aún se apaga.
4. **Cierre (S5)**: `_report_job` escribe `state/jobs/results/<job_id>.json` y, si hay workspace, `<memory>/jobs/<job_id>.{json,md}` con identidad; el MinionInbox gana `continuity_id` y lo muestra. Un job sin alma emite `continuity_id: null`, nunca un UUID inventado.
5. **Descubrimiento (S3.3)**: `wake_up_v6.py --continuity-id` añade una línea `[JOBS]` con timeout de 250 ms; solo informa, nunca auto-reanuda (D-05). Silencio si no hay alma o jobs.
6. **Compatibilidad**: el lease de misión se cablea a `dag_job` (el orquestador); `agentic_job`/`script_job`/`element_job` no lo reclaman hasta que exista heartbeat genérico en el runner. La CLI funciona como Operador, consulta el lease antes de reanudar y libera el de jobs no-en-vuelo al matar. Arneses externos (S6/B-01h) y D23-SCORE quedan fuera.
**Alternatives**: (a) dejar que el job adquiera el lease — viola D-03 y crea dos orquestadores; (b) autorizar por argumento del modelo — spoof; (c) escribir el resultado solo en el inbox — efímero y sin workspace.
**Rationale / Evidence**: suite **3391 passed**, 13 skipped, 3 xfailed; `ruff`/`mypy` limpios. Tests S3.3/S4/S5: lease observado/liberado, otra alma no roba, heartbeat, identidad en transfer, checkpoint sin inyección, `kill_task_ex`, result.json con/sin alma, inbox y `[JOBS]`.
**Consequences**: RFC-003 S0-S5 implementado; S6 (env a opencode/claude/pi) y B-01h (hooks externos) siguen pendientes. El watchdog/janitor de leases de B01L Fase 2-3 no se toca aquí.

---

## [AD-077] RFC-INTEROP-003 S2/S3 — leg, eventos y descubrimiento del job (P2)
**Date**: 2026-10-25
**Status**: ACCEPTED & IMPLEMENTED (S2/S3 parcial). `[JOBS]` en el handshake, lease de misión y handoff siguen pendientes.
**Context**: S0/S1 daban identidad al payload/etapas, pero el coro no veía el job como leg ni el alma podía descubrirlo. P2 materializa el ciclo S2/S3 sin tocar el motor del DAG.
**Decision**:
1. **Leg `dag:<job_id>`** en `DagJobDriver.begin_step` cuando hay `continuity_id`: `mission_id = parent_mission_id` (misión del alma), `role=job`, linaje/afinidad; se expira en `on_terminal` (completed/failed/timeout).
2. **Eventos**: `phase_done` por hoja nueva, `blocked` por etapa fallida y `mission_closed` al completar; idempotentes por `(mission,type,ref,summary)` y solo con `parent_mission_id` (nunca la misión de aislamiento del forge).
3. **Descubrimiento**: `CognitiveQueueManager.list_tasks(continuity_id=...)`, `job_list`/CLI `job list --continuity` y `job_status` con `continuity_id`/`parent_mission_id`/`originator`/`role`/`lease`.
4. **Rol `job`**: política de hidratación compacta equivalente a `task`, registrada para que el tablón/digest no la degrade.
5. **Anti-spoof**: `job_submit` exige que el `continuity_id` declarado coincida con el canal de confianza (salvo Operador); `DagJobDriver` valida `REDPILL_CONTINUITY_ID`.
6. **Límite**: `[JOBS]` en wake-up, lease de misión y handoff no se tocan en P2; sin auto-reanudación.
**Alternatives**: (a) leg por etapa — multiplica el tablón; (b) eventos desde MCP — exige sesión y no cubre jobs headless; (c) auto-resume al descubrir — riesgo de duplicar efectos.
**Rationale / Evidence**: suite **3370 passed**, 13 skipped, 3 xfailed; `ruff`/`mypy` limpios. Tests: leg activo/rol job, phase_done, mission_closed, expiración y filtro por continuidad.
**Consequences**: un job con alma ya se ve en el coro y se puede descubrir por `continuity_id`; faltan wake-up `[JOBS]`, lease de misión, handoff y env a arneses externos.

---

## [AD-076] RFC-INTEROP-003 S0/S1 — identidad de alma en `dag_job` (P1)
**Date**: 2026-10-25
**Status**: ACCEPTED & IMPLEMENTED (S0/S1 bajo defaults; D-01…D-12 siguen abiertas). S2-S6 (leg/eventos, descubrimiento, lease de misión, handoff, arneses externos) pendientes.
**Context**: El RFC-INTEROP-003 verificó que `dag_job` solo conocía `mission_id`: no heredaba `continuity_id`, no lo propagaba a etapas/checkpoint y el alma no podía reconocer el job. P1 implementa el contrato mínimo sin cambiar el motor del DAG.
**Decision**:
1. **S0 contrato**: `dag_validate` acepta `continuity_id` (UUID), `parent_mission_id` (`<scope>:<id>`) y `role` (`orchestrator|job|task|spawn`) opcionales; `cognitive_tasks` gana `continuity_id`/`parent_mission_id` + índices, sin romper jobs sin alma.
2. **S1 checkpoint**: `DagScheduleMixin.step` deriva `originator=dag:<job_id>`, `role=job` y copia identidad al checkpoint/status; se conserva en resume.
3. **S1 etapas**: `dag_exec` pasa identidad a minions, inyecta `REDPILL_*` en command/script y añade `<redpill-identity>` (solo IDs) al prompt de etapas agénticas.
4. **Local-mini/local-tools** heredan `continuity_id`/`mission_id`/`originator`; los arneses externos (opencode/claude/pi) se difieren a S6.
5. **Compatibilidad**: jobs de sistema sin `continuity_id` no crean leg, no reciben env y siguen igual; migración de cola aditiva.
**Alternatives**: (a) derivar el alma de `mission_id` — dos almas comparten rama; (b) inyectar identidad por prompt — spoof; (c) crear un bus nuevo — RFC-001 sigue sin implementación.
**Rationale / Evidence**: suite **3364 passed**, 13 skipped, 3 xfailed; `ruff`/`mypy` limpios. Tests: validación de UUID/misión/role, columnas de cola, checkpoint con linaje, env `REDPILL_*` en command y bloque de identidad en agente.
**Consequences**: un dag_job puede declarar su alma y las etapas la reciben; todavía no hay leg `dag:`, `[JOBS]`, eventos ni handoff (S2-S6). La lease de misión reutiliza `session_leases` de B01L.

---

## [AD-075] B-01L Fase 1 — leases v7 y worker durable de compactación (P0)
**Date**: 2026-10-25
**Status**: ACCEPTED & IMPLEMENTED (P0). Watchdog/heartbeat de runners y Telegram quedan pendientes.
**Context**: B-01L separó el TTL de huérfanos del lease de trabajo vivo, pero no existía implementación; B-02 tampoco tenía disparo en fondo. P0 materializa el sustrato común: `session_leases` v7 con scopes work/mission y un worker durable para compactar sin bloquear el turno.
**Decision**:
1. **Schema v7 aditivo**: `session_leases` con `lease_key`, `scope=work|mission`, `subject_id`, `continuity_id`, `mission_id`, `holder_originator`, `owner_kind`, `state`, heartbeat, `idle_ttl_s`, `max_wall_s`, `extended_by`, `reason`; índices por heartbeat/scope/alma.
2. **`LeaseStore`**: begin idempotente por dueño, `LeaseHeld` para otro cuerpo, heartbeat, `extend_lease` acotado por techo, `finish` con transiciones válidas, `sweep` con compare-and-set para no perder un heartbeat concurrente. Work y mission comparten tabla; RFC-INTEROP-003 no crea `mission_leases`.
3. **B02 worker durable**: `Compactor.maybe_start` encola un `script_job` con `session compact --db-path <mirror>` y dedupe por continuity; `control.max_step_minutes=15`. `MiniSession`/`run_local_minion` lo disparan solo cuando el contexto cruza el umbral de fondo sin necesitar compactación inline.
4. **Correcciones del adversarial P0**: targeting de `session.db` (no la DB por defecto del worker), `extra_tokens` coherente entre caller y worker, timeout real vía `control`, extensión sin techo ya no es no-op, owner en heartbeat/finish, purga de leases con el alma, y `sweep` no marca `stalled` si el heartbeat cambió.
5. **Compatibilidad**: `SESSION_COMPACTOR_ENABLED` sigue OFF; sin flag no se encola nada. Jobs sin alma no cambian.
**Alternatives**: (a) worker Python in-process — no durable; (b) Samantha queue — no devuelve el resumen salvo callback Telegram; (c) dos tablas de lease — duplica schema y rompe RFC-003; (d) `timeout` en payload — el driver no lo lee, se usa `control.max_step_minutes`.
**Rationale / Evidence**: suite completa verde; tests nuevos de schema v7, work/mission, idempotencia, owner, max_wall, extensión, sweep, worker/dedupe y targeting. Adversarial P0 corrigió 3 BLOCKER/HIGH de ejecución.
**Consequences**: B01L Fase 1 y B02 worker están en el sustrato. Deuda: cablear heartbeat a MiniSession/local-minion/job runner, janitor que consulte leases activos, watchdog, paridad Telegram y retry por longitud. El lease aún no protege del TTL hasta la fase 2.

---

## [AD-074] B-02 — servicio de compactación y cableado local (slice 3)
**Date**: 2026-10-24
**Status**: ACCEPTED & IMPLEMENTED (slice 3). Telegram y el disparo en fondo siguen pendientes; flags OFF por defecto.
**Context**: AD-073 dejó el almacén y el puerto de resumen, pero ningún consumidor los usaba. Faltaba el servicio que decide rango, protege la cola y escribe el resumen, y cablearlo en los runners locales sin cambiar el comportamiento por defecto.
**Decision**:
1. **`session/compactor.py`**: `Compactor` sobre `SessionMirror` con `compact_now`, `ensure_context`, `maybe_compact`, `context` y `reset(handoff)`. `start/complete/abort` siguen siendo la única escritura canónica.
2. **Rango seguro y contiguo**: se compacta desde `range_end+1` de la última compactación hasta `last_regular - protect_last_n`; `_safe_range_end` baja el corte si partiría una pareja assistant(tool_calls)↔tool (incluidos resultados pending/aborted). La **lectura** (`context_turns`) no aplica `protect_last_n`: devuelve la cadena completa de resúmenes (vigente y ancestros) y todo lo posterior al rango, para no ocultar turnos que aún no fueron resumidos. El resumen anterior puede entrar en el siguiente rango (resumen recursivo), pero no cuenta como turno protegido. `reset(handoff)` supersede las compactaciones vigentes.
3. **Umbral**: `ensure_context` estima chars/3.2, suma system+task (`extra_tokens`) y compacta una vez si no cabe en `budget - reserve`; si no hay rango, no mintió con `compacted=True`. Un resumen que no reduce en contextos reales se aborta (`summary_not_smaller`). `background_tokens` queda reservado para `B02-WORKER`.
4. **MiniSession**: `context_tokens` en `MiniConfig`/`AgentProfile`, `compactor_enabled/engine/protect_last_n`; antes del provider usa `ensure_context` y luego aplica los trims existentes. Perfiles: Forge 8192, Loom 4096.
5. **`run_local_minion`**: `context_tokens` + `use_compactor`; la compactación corre en executor (no bloquea el event loop) y solo si hay alma+misión. Cae al historial anterior si falla.
6. **CLI**: `red-pill session compact --continuity ID [--mission M] [--engine samantha|memento|extractive] [--protect-last-n N] [--handoff FILE] [--json]`; `--handoff` ejecuta `reset` (con misión inferida o explícita y error CLI legible).
7. **Compatibilidad**: `SESSION_COMPACTOR_ENABLED=False` por defecto; sin flag, MiniSession/local-minion se comportan exactamente como antes. `purge()` elimina compactaciones de almas muertas para no dejar resúmenes huérfanos ni romper el `seq` al reencarnar.
**Alternatives**: (a) compactar en cada turno — coste y resúmenes redundantes; (b) borrar turnos — rompe auditoría/B-01s; (c) compactar dentro del provider — acopla el motor al runner; (d) hilo de fondo efímero — no durable, se pierde con el proceso; se deja para el worker/JM.
**Rationale / Evidence**: suite **3331 passed**, 13 skipped, 3 xfailed; `ruff` y `mypy` limpios. Tests nuevos: rango seguro con pareja tool, hueco no resumido, idempotencia por rango y rangos solapados, cadena de 3+ resúmenes, abort por fallo/resumen no decreciente, `protect_last_n` como política de corte, segunda compactación con `parent_compaction_id`, `reset(handoff)` tras compactar y tras reset, `maybe_compact`, MiniSession/local-minion con ventana corta que conserva el resumen, `rehydrate` compactado con límite y purga de compactaciones.
**Consequences**: B-02 ya tiene servicio y consumidores locales. Deuda explícita: `B02-WORKER` (Samantha/Job Manager en fondo con dedupe), paridad Telegram (mapear sesión Telegram→alma), reintento tras rechazo por longitud, `compact_parent` en switch/rehydrate, `B02-TOKENS` (usage real) y cap/resumen de resúmenes para la cadena (hoy se conserva completa; crece con cada compactación). ARCH-001 sigue siendo el gate del harness propio. Inspirado en **Pi Durable** (Earendil Works / Mario Zechner, MIT): se copian políticas, no código.

---

## [AD-073] B-02 — schema de compactaciones y puerto de resumen (slices 1-2)
**Date**: 2026-10-24
**Status**: ACCEPTED & IMPLEMENTED (slices 1-2 de B-02). Integración en MiniSession/Telegram/local-minion y `reset(handoff)` siguen pendientes.
**Context**: B-02 necesita dos piezas antes de cablear umbrales: un almacén canónico de compactaciones (sin borrar el espejo) y un motor de resumen que no sea el modelo de la conversación. Samantha ya resume Telegram; Memento tiene transporte local y `context-distiller` era un skill manual pre-Búnker. Faltaba el contrato entre ellos.
**Decision**:
1. **Schema v6 aditivo**: `session_compactions` (`compaction_id` PK, `continuity_id`, `mission_id`, `parent_compaction_id`, `range_start_seq`, `range_end_seq`, `summary`, `model`, `status`, `reason`, `tokens_before`, `tokens_after`, `created_at`, `completed_at`) + índices por alma/estado/rango y por padre. Índice único parcial por `(continuity_id, range_start_seq, range_end_seq)` no abortado: dos productores del mismo rango convergen.
2. **Ciclo de compactación**: `start_compaction` inserta `pending` (idempotente por id); `complete_compaction` apenda un turno `system` (`source=compactor`, `source_ref=compact:<id>`) y actualiza la fila en **una transacción**; `abort_compaction` no toca el contexto. El histórico original nunca se borra.
3. **Contexto podado**: `context_turns` devuelve resumen vigente + cola posterior a `range_end_seq`, con `protect_last_n` calculado sobre turnos normales (no sobre el resumen). `context_messages` reutiliza `switch.replay_messages` (parejas tool-call/result intactas).
4. **Puerto `Summarizer`**: `SamanthaSummarizer` (cola local barata), `MementoSummarizer` (transporte local de calidad/manual/handoff) y `ExtractiveSummarizer` (fallback determinista sin LLM). `FallbackSummarizer` encadena primario + extractivo; `build_summarizer` expone la fábrica.
5. **Prompt operativo propio** (`session/prompts/compactor_summary_*`): estado, decisiones, cambios/refs, pendientes, blockers y siguiente paso. No reutiliza el prompt de memoria curada de Memento ni el de Telegram.
6. **Flag apagado por defecto**: `SESSION_COMPACTOR_ENABLED=False`; el resto de parámetros (`ENGINE`, `PROTECT_LAST_N`, `BACKGROUND_TOKENS`, `RESERVE_TOKENS`, `MAX_INPUT_CHARS`) tiene defaults.
**Alternatives**: (a) reutilizar `session_mirror` con columnas de compactación — mezcla dos ciclos de vida; (b) borrar turnos compactados — pierde auditoría y B-01s; (c) usar el modelo de la conversación — no cabe el contexto que se quiere resumir; (d) usar solo el prompt de Memento — está orientado a memoria curada, no a continuidad operativa; (e) un único motor sin fallback — un fallo local bloquea el turno.
**Rationale / Evidence**: suite **3299 passed**, 13 skipped, 3 xfailed; `ruff` y `mypy` limpios en los módulos tocados. Tests nuevos: schema v6, roundtrip start/complete/abort, idempotencia, `protect_last_n`, `compact_parent`, pareja tool-call, contrato `CompactionStore`, prompts y los tres adaptadores + fallback.
**Consequences**: B-02 ya tiene su sustrato canónico y su motor intercambiable. Deuda: cablear umbrales en `MiniSession`/`run_local_minion`/Telegram, `reset(handoff)`/`compact_parent` en switch, y decidir `B02-TOKENS`/`B02-WORKER`. ARCH-001 sigue siendo el gate del harness propio. Inspirado en **Pi Durable** (Earendil Works / Mario Zechner, MIT): se copian políticas, no código.

---

## [AD-072] B-01s — estado de turno y write-ahead en el espejo del alma
**Date**: 2026-10-24
**Status**: ACCEPTED & IMPLEMENTED. Completa B-01j para los caminos RedPill; B-01h (hooks externos) sigue pendiente.
**Context**: B-01j persistía la intención en el checkpoint del Job Manager, pero el espejo del alma seguía escribiéndose post-hoc. Un corte en `MiniSession`/`run_local_minion` podía dejar el prompt sin rastro y el replay podía inyectar un turno a medias. Hacía falta el estado de turno en `session_mirror`, la API de ciclo de vida y una superficie de inspección/resume.
**Decision**:
1. **Schema v5** aditivo: `session_mirror` gana `status` (`pending|completed|aborted`), `request_id` y `status_reason`; índices por `(continuity, request_id)` y `(continuity, status)`. Filas viejas quedan `completed`.
2. **Ciclo de vida**: `begin_turn` escribe el user `pending` antes del modelo; `complete_turn` cierra el grupo; `abort_turn` marca el grupo y opcionalmente guarda respuesta parcial. La idempotencia sigue en `source_ref`; `request_id` agrupa user/assistant/tool.
3. **Replay seguro**: `read_turns` devuelve solo `completed` por defecto; `pending`/`aborted` no entran al modelo y se consultan con `pending_turns`/`statuses`.
4. **Integración**: `MiniSession.run` escribe user pending antes del provider y completa/aborta el grupo; `run_local_minion` hace lo mismo y captura assistant/tool con el mismo `request_id`.
5. **CLI**: `red-pill session pending` (lista/expira TTL/JSON) y `red-pill session resume REQUEST_ID` (muestra el prompt; no invoca al modelo).
6. **TTL**: `SESSION_PENDING_TTL_MIN` (30 min); el janitor marca `aborted` con `reason=ttl` y métricas `session_pending_expired`.
**Alternatives**: (a) tabla aparte — segunda fuente de verdad; (b) `read_turns` con todo por defecto — replay contaminado; (c) escribir el user después del modelo — el corte seguiría perdiendo el prompt; (d) CLI que reenvíe solo — el arnés debe decidir.
**Rationale / Evidence**: suite **3282 passed**, 13 skipped, 3 xfailed; `ruff`/`mypy` limpios. Tests nuevos: begin idempotente, completed/aborted, parcial, TTL, schema v5, MiniSession success/error y CLI pending/resume; los tests de `local_minion`/espejo siguen verdes.
**Consequences**: el alma ya puede ver y reanudar un prompt pendiente sin inyectarlo como verdad. Deuda: B-01h (hooks opencode/claude/pi), reapertura explícita de un `aborted` y política de respuesta parcial/efectos cloud (B-04). ARCH-001 sigue siendo el gate del harness propio.

---

## [AD-071] Workflow seed por perfil — `solo`/`canonical` se materializa al sembrar
**Date**: 2026-10-24
**Status**: ACCEPTED & IMPLEMENTED.
**Context**: El modelo de ramas tenía dos perfiles (`solo` single-maintainer, `canonical` múltiples) seleccionados por `GIT_WORKFLOW`, pero la siembra estaba a medias: `bunker_update`/installer copiaban `seeds/rules/git_workflow.md` **entero** (ambos perfiles) y el agente elegía en runtime. El comentario decía “for the active profile” pero el código no lo hacía. Además, el `pre-push` invitaba a “push your work branch”, contradiciendo el remoto limpio de `solo`.
**Decision**:
1. `seeds/rules/git_workflow.md` es una **plantilla** con invariantes comunes + bloques `profile:solo` y `profile:canonical`.
2. `red_pill/core/git_workflow.py` renderiza **solo** el perfil activo (sin bloque inactivo, sin marcadores, `{{profile}}` sustituido).
3. `bunker_update` lee `GIT_WORKFLOW` de la config y escribe el render en `~/.agent/rules/git_workflow.md`; `scripts/install_neo.sh` hace lo mismo con el helper `scripts/render_git_workflow.py`. El scaffold usa su copia standalone.
4. `pre-push` en `solo` rechaza `refs/heads/feat/*`; solo `next` y hotfix PR branches van a origin. En `canonical` se permite la rama feature para el PR.
5. Docs (`WORKFLOWS`, `CONVENTIONS`, `CONTRIBUTING`, `.env.example`) explican que el `.env` selecciona y la siembra materializa **un único** perfil.
**Alternatives**: (a) mantener ambos perfiles en el fichero desplegado — el agente seguía eligiendo; (b) dos seeds duplicados — drift; (c) auto-detectar single/multi — frágil; (d) no tocar el `pre-push` — seguía invitando a la rama remota.
**Rationale / Evidence**: tests de render (solo/canonical, sin marcadores, perfil inválido), seed/scaffold con bloques, `pre-push` con guard solo; suite pendiente de cierre. El render es determinista y falla limpio si falta un bloque.
**Consequences**: cambiar `GIT_WORKFLOW` exige re-seed; el fichero del agente ya no contiene ambos perfiles. La rama de evidencia del worktree sigue viva hasta el release PR (workflow); el remoto en `solo` queda `main` + `next` (+ hotfix PR puntual).

---

## [AD-070] B-01j — write-ahead universal en el Job Manager
**Date**: 2026-10-24
**Status**: ACCEPTED & IMPLEMENTED. Primer slice de B-01 (D-02); B-01s/B-01h siguen pendientes.
**Context**: Un corte de proveedor o de conexión podía perder el prompt y no dejar constancia de que el turno quedó sin respuesta. La revisión de Pi Durable (D-01 no migración; D-02 B-01; D-03 B-02) marcó B-01 como el slice más rentable. El diseño inicial se había centrado en Forge/Loom; el Operador pidió que la práctica cubriera **cualquier tarea agéntica**, incluidos los bridges cloud de `AgenticJobDriver` (`agy/claude/opencode/pi`) y las cascadas.
**Decision**:
1. **Hook de runner**: `ResumableJobDriver.begin_step()` se llama **antes** de `step()` y el runner persiste el checkpoint; `abort_step()` se llama en timeout/error/kill antes de marcar el fracaso. Default no-op para drivers que no lo necesitan.
2. **Checkpoint como intención**: `AgenticJobDriver` guarda `pending_turn` con `request_id=job:attempt`, backend, modelo, hash/preview del prompt, `started_at` y `resume_count`. No hace falta una tabla nueva ni inspeccionar el arnés.
3. **Cualquier bridge**: el hook vive en el driver, no en un proveedor; cubre cloud, local, local-mini, local-tools y `CascadeBridge`. La durabilidad nativa de pi/opencode/claude/agy es opaca y **no se asume**.
4. **Idempotencia mínima**: si el checkpoint ya tiene el turno `completed` con el mismo `request_id`, `step()` devuelve el resultado guardado sin volver a llamar al bridge. Un reintento `pending` conserva `started_at` y suma `resume_count`.
5. **Abort explícito**: timeout/error/kill deja `pending_turn.status=aborted` con `reason`; nunca queda un pending silencioso en el camino del runner.
6. **Sin exactly-once cloud**: B-01j asegura intención persistida, no que un efecto externo no se haya ejecutado. La política `replay: safe|never` (B-04) y la idempotency de `job_submit` (B-08) siguen pendientes.
**Alternatives**: (a) implementarlo por bridge (cada arnés) — duplicación y huecos; (b) tabla `job_turns` aparte — segunda fuente de verdad; (c) esperar a B-03/B-04 — el corte seguiría perdiendo la intención; (d) depender del checkpoint nativo de cada arnés — no garantizable.
**Rationale / Evidence**: suite **3272 passed**, 13 skipped, 3 xfailed; `ruff check src/ tests/ scripts/` y `mypy src/red_pill/` limpios. Tests nuevos en `tests/test_b01_write_ahead.py` para todos los backends, `completed` sin re-invocación, abort y resume; `test_job_pausing_state`/`test_job_manager` siguen verdes.
**Consequences**: el coordinador ya puede ver un `pending_turn` antes de invocar cualquier modelo y sobrevivir a un corte con la intención persistida. Deuda: B-01s (espejo `status`/`request_id` y resume por alma), B-01h (hooks externos), política `unknown`/replay (B-04) y compactación (B-02). No se construye harness propio hasta ARCH-001.

---

## [AD-069] Mini arnés — hardening zero-trust y corrección de la superficie v0
**Date**: 2026-10-24
**Status**: ACCEPTED & IMPLEMENTED. Corrige los hallazgos de la revisión adversarial de AD-068.
**Context**: La revisión zero-trust de cuatro lentes (plan/security/correctness/env) sobre el mini RFC v0 dio **3 BLOCKER + 1 CLEARED**. El happy path Forge→Loom funcionaba, pero la superficie era más amplia y menos contenida que lo declarado: `RuntimeDirectory` compartido, workspace/DB/socket/URL controlados por payload, continuidad cross-soul, `run_tests` en el revisor "read-only", timeout ignorado, `run_ref` no determinista, replay con parejas huérfanas, leg activo no atómico, linaje perdido y docs de aceptación desalineadas.
**Decision**:
1. **Aislamiento systemd**: `redpill-forge.service` usa `RuntimeDirectory=red-pill/forge` (nunca el directorio compartido con Laya/SIP), `UMask=0077` y socket `%t/red-pill/forge/forge.sock`; Loom añade `IPAddressDeny=any` + `IPAddressAllow=localhost`; los lanzadores transitorios aplican `PrivateNetwork`/`RestrictAddressFamilies`/`IPAddress*`/`UMask` y crean directorios 0700.
2. **Frontera de confianza**: `mini/trust.py` valida workspace (roots locales), `db_path`, socket y `flm_url` (solo loopback). `job_submit` local-mini descarta overrides de transporte, ata `continuity_id`/`mission_id` a la sesión llamante y valida el workspace; la cola directa (tests/E2E) valida en el driver. Un perfil/workspace inválido es fallo permanente, no `JobDeferred`.
3. **Loom read-only real**: `READONLY_TOOL_SCHEMAS` solo expone `list_files`/`read_file`; se retira `run_tests` del revisor. Forge conserva `run_tests`, pero con env whitelist, `PYTHONDONTWRITEBYTECODE`, timeout y salida redactada con `scrub_secrets` antes de espejar.
4. **Correctness**: el timeout se propaga hasta `provider.chat`; `run_ref` estable (`job_id:attempt`) deduplica reintentos; el replay usa ventana pair-safe + presupuesto de 12k chars (12/20 turnos); `activate_leg` cierra otros legs y hace upsert en un `BEGIN IMMEDIATE`; `lineage_id` se conserva; el CLI devuelve exit code no-cero en fallo.
5. **Aceptación y docs**: `run_smoke` incluye `metrics` (fases, turnos, tool turns), exige `nonce_in_forge_text` y el E2E exige RUN_ID de Forge + evidencia en el espejo + un leg activo; el E2E borra `test_calc.py` antes de Loom (prueba de historial, no de fichero) y verifica `forge.sock` + `127.0.0.1:52625` sin `0.0.0.0`. La guarda de tests incluye 52625 y el auto-registro NPU no sondea FLM en tests. `session.db` pasa a 0600 al conectar. RFC §8 se alinea con lo real (forge.sock, loopback, sin run_tests en Loom, presupuestos, métricas manuales); AD-068 deja de decir "RFC entero".
**Alternatives**: (a) dejar el v0 como estaba y solo documentar — los P0 eran explotables con `job_submit`; (b) sandbox completo de `run_tests` — más infra; se opta por retirarlo del revisor y endurecer el ejecutor; (c) broker/aislamiento OS — sigue diferido a D26/rogue local; (d) aceptar continuidad del payload — permitía poisoning cross-soul.
**Rationale / Evidence**: suite **3264 passed**, 13 skipped, 3 xfailed; `ruff check src/ tests/ scripts/` y `mypy src/red_pill/` limpios. Tests nuevos de trust (workspace fuera de roots, symlink, URL loopback, DB/socket, payload cross-soul, env scrub), timeout, `run_ref`, linaje/leg atómico, replay pair-safe, unit files y CLI exit. E2E real repetido tras el hardening: `processed=2`, ambos `COMPLETED`, `tests_ok`, `forge_cites_run_id`, `loom_saw_forge`, `loom_loopback_only`, `forge_socket_ok`, `one_active_leg=true` (`loom-tools`), socket 0700, sin unidades/procesos residuales; Loom citó el RUN_ID con `test_calc.py` borrado.
**Consequences**: el mini v0 queda usable sin overrides de transporte desde agentes y con Loom sin ejecución de código. Deuda: Loom ya no ejecuta tests (los ejecuta Forge); la cola directa sigue siendo de confianza; FLM sigue en loopback (netns+UDS fase 2); 35B/9B diferidos; el broker/aislamiento OS se reabre en D26.

---

## [AD-068] Mini arnés v0 completo — CLI, systemd, Loom read-only y E2E de jobs
**Date**: 2026-10-24
**Status**: ACCEPTED & IMPLEMENTED. Cierra la superficie operativa de AD-065/066/067; no cambia el contrato del mini arnés. **Hardening posterior: AD-069.**
**Context**: AD-067 dejó `local_minion` multiturno y `local-mini` listo para jobs, pero faltaba la superficie para usarlo: `red-pill mini`, unidades persistentes, una variante de Loom con tools de solo lectura y un E2E que atravesara el Job Manager real (no el smoke in-process). El Operador pidió cerrar la superficie §8 del RFC (no el RFC global), no solo el core.
**Decision**:
1. **CLI `red-pill mini`**: parser con `--profile`, `--continuity`, `--mission`, `--workspace`, `--gpu-socket`, `--flm-url`, `--db-path`, `--operator` y `--once`; `handle_mini` construye `MiniLocalBridge` y `run_mini_cli` ofrece one-shot o REPL (exit/quit). El loop es inyectable en tests; no duplica el bucle de `MiniSession`.
2. **Unidades persistentes**: `systemd/redpill-forge.service` (UDS, `PrivateNetwork=yes`, `RestrictAddressFamilies=AF_UNIX`, `RuntimeDirectory=red-pill` (sustituido por `red-pill/forge` en AD-069), `MemoryMax=7G`) y `systemd/redpill-loom.service` (FLM loopback, `MemoryMax=10G`), ambas con `MemorySwapMax=0`. `scripts/install_mini_services.sh` las instala; no las habilita salvo `--enable` (decisión del Operador).
3. **Loom read-only**: `READONLY_TOOL_SCHEMAS` (list/read; `run_tests` retirado en AD-069), `WorkspaceTools(read_only=True)` que oculta write/edit y los rechaza si se invocan, perfil `loom-tools` con prompt de revisor. `MiniLocalBridge` ofrece `workspace` y `workspace_ro`; el perfil `loom` sin tools sigue existiendo para revisión pura.
4. **`job_submit`**: `agentic_job` con `backend: local-mini` + `profile` ya no exige `model`; el perfil resuelve el provider. El guard sigue exigiendo modelo para los demás backends.
5. **E2E real de jobs**: `scripts/local/mini_services.py` factoriza el arranque/parada con cgroups; `scripts/local/mini_job_e2e.py` enciende Forge/Loom, crea el fixture, encola dos `agentic_job` con la misma `continuity_id` (Forge ejecuta; Loom read-only revisa), llama a `process_driver_jobs` y valida estado/checkpoint/tests/RUN_ID/leg activo. Cola y `session.db` temporales.
6. **Un alma, un cuerpo activo a través de procesos**: el E2E destapó dos legs activos (el bridge de cada job abre su propio leg). `MiniSession.switch_to` ahora cierra los legs activos anteriores de la misma `continuity_id` al abrir el nuevo, no solo el que conoce en memoria; test de regresión entre dos `MiniSession`.
**Alternatives**: (a) dejar el CLI fuera del RFC — no se podía usar sin escribir Python; (b) unidades habilitadas por el installer — arrancar modelos de 9B/8B al login sin decisión explícita; (c) Loom con el toolbox completo y prompt “no escribas” — una alucinación podía editar; (d) E2E reutilizando `run_smoke` in-process — no probaba `job_submit`/driver/checkpoint; (e) cerrar el leg anterior solo si es el mismo proceso — dejaba dos activos tras migrar entre jobs.
**Rationale / Evidence**: suite **3252 passed**, 13 skipped, 3 xfailed; `ruff check src/ tests/ scripts/` y `mypy src/red_pill/` limpios. E2E real (Forge Qwen3.5-9B GPU + Loom `qwen3:8b` FLM, cgroups): `processed=2`, ambos jobs `COMPLETED`, `tests_ok=true`, `loom_cites_run_id=true`, `one_active_leg=true`, `active_body=loom-tools`; Forge citó el RUN_ID y el diff, Loom verificó con read-only tools y `run_tests`. Sin unidades ni procesos residuales; `52625` libre al terminar. Tests nuevos: CLI (one-shot/REPL/args), submit local-mini, unidades/instalador, toolbox read-only/perfil y cierre de legs entre instancias.
**Consequences**: el mini arnés v0 queda usable por CLI, systemd o Job Manager, con Loom capaz de verificar sin poder editar. Deuda: (1) FLM sigue en loopback 52625; netns+UDS es hardening fase 2; (2) 35B/9B diferidos por RAM; (3) no hay “coma”/KV persistente entre procesos; (4) `run_tests` en read-only puede escribir cachés del runner (no edita fuentes); (5) el installer no habilita las unidades; (6) el CLI usa la `session.db` viva por defecto; (7) Laya on-demand sigue parked.

---

## [AD-067] `local_minion` multiturno — historial del espejo, sin duplicar turnos
**Date**: 2026-10-23
**Status**: ACCEPTED & IMPLEMENTED. Extiende AD-066; reutiliza el espejo de AD-060/AD-061.
**Context**: AD-066 dio multiturno a `MiniLocalBridge` (Forge/Loom), pero el `run_local_minion` clásico —el que usa `local-tools` y las tools MCP— seguía arrancando con `system + task` y sin historial. El Operador quiere una tarea simple con posibilidad de multiturno también en esa vía, sin duplicar el loop ni el espejo.
**Decision**:
1. **Identidad y historial en `run_local_minion`**: resuelve `(originator, continuity_id, mission_id)` por parámetros → env del job → registro. Si hay `continuity_id`, carga los últimos `history_turns` (40 por defecto) del `SessionMirror` con `replay_messages` y arranca con `system + historial + task`. Sin identidad, comportamiento legacy exacto.
2. **Captura sin duplicar**: se guarda `initial_len` antes de añadir la tarea y solo se apendan `messages[initial_len:]` al espejo. El historial replayed no se vuelve a escribir con nuevos `source_ref`.
3. **`LocalToolBridge`**: acepta `continuity_id`/`mission_id`/`originator`/`history_turns`, los pasa a `run_local_minion`, expone `continuity_id` y declara `conversation_resume=True` (la continuidad es el espejo, no un id nativo). `create_bridge("local-tools")` propaga esos kwargs; `AgenticJobDriver` los pasa y reutiliza `continuity_id` del checkpoint también para `local-tools`.
4. **Sin unificar loops**: el parser nativo/MCP tools y la conducta del `local_minion` se quedan; el historial es la pieza compartida. Para Forge/Loom sigue `MiniLocalBridge`.
**Alternatives**: (a) duplicar el loop de `MiniSession` en `local_minion` — dos bucles divergentes; (b) inyectar historial completo como mensajes y capturar todo — duplicaría turnos con nuevos `source_ref`; (c) no tocar `local_minion` y exigir `MiniLocalBridge` — no cubre tools MCP/native; (d) cargar historial siempre sin identidad — inventaría alma.
**Rationale / Evidence**: suite **3242 passed**, 13 skipped, 3 xfailed; `ruff`/`mypy` limpios. Tests: historial reproducido y captura sin duplicados (4 turnos, no 6), identidad por env, `LocalToolBridge` pasa continuidad, y `AgenticJobDriver` crea `local-tools` con `continuity_id`. No se toca la BD viva en tests (XDG temporal).
**Consequences**: `local-tools` ya puede continuar una tarea entre runs con el mismo `continuity_id`, y los jobs pueden pasar continuidad. Deuda: (1) historiales con `role=tool` dependen de que el chat-format del modelo los acepte; (2) `local-tools` no cambia de cuerpo (para Forge/Loom, `local-mini`); (3) CLI `red-pill mini` y E2E `job_submit` siguen pendientes.

---

## [AD-066] Mini arnés composable — contratos, perfiles y `local-mini` en jobs
**Date**: 2026-10-23
**Status**: ACCEPTED & IMPLEMENTED. Extiende AD-065 (composición, no un segundo loop).
**Context**: AD-065 dejó Forge/Loom, prompts y modelos dentro del smoke. El Operador pidió DRY: combinar piezas según el uso (job_manager, swarm, local_minion) sin duplicar código. La disección natural es contratos + perfiles + adaptadores; el smoke debe ser una composición, no el core.
**Decision**:
1. **Contratos** (`mini/contracts.py`): `ChatProvider` (chat OpenAI), `Toolbox` (`schemas` + `execute`) y `AgentProfile` (key, name, role, provider, toolbox, system prompt, max_steps, history, temperature, max_tokens). `AgentProfile.render_system` sustituye `{name}`, `{role}`, `{operator}`, `{session_short}`.
2. **Perfiles como dato** (`mini/profiles.py`): Forge (executor, workspace, tools) y Loom (reviewer, sin tools) dejan de estar hardcodeados en el smoke. Un job/minion puede definir otro perfil sin tocar el loop.
3. **`MiniSession` composable**: acepta `profiles` y `toolboxes` opcionales; `run_profile(name, task)` resuelve provider, toolbox, rol, prompt y política. `MiniConfig.operator`; el título del leg usa el nombre del perfil. Los tests viejos siguen usando `run(...)` con prompts/tools explícitos (compatibilidad).
4. **`MiniLocalBridge`** (`mini/bridge.py`): adaptador `AgentBridge` sobre `MiniSession`. `prompt`/`continue_conversation` usan el espejo (misma `continuity_id`) y el perfil; `conversation_resume=True`; `health_check` consulta el provider del perfil. Registrado como **`local-mini`** en `create_bridge`.
5. **Job manager**: `AgenticJobDriver` acepta `backend: local-mini` con `profile`, `continuity_id`, `mission_id`, `workspace`/`cwd`, `db_path`, `gpu_socket`, `flm_url`, `operator`; si falta `continuity_id`, lo toma del checkpoint; guarda el `continuity_id` en el checkpoint. Preflight usa `health_check` del bridge (deferral si el modelo no está).
6. **Composición, no unificación**: el loop del `local_minion` clásico (MCP tools, parser nativo, conduct) se queda; `MiniLocalBridge` es la vía nueva para trabajos simples con multiturno. No se mete un loop con flags para todos los formatos.
**Alternatives**: (a) dejar prompts/modelos en el smoke — no reutilizable; (b) un solo loop para workspace + MCP + texto nativo — god-object y riesgo; (c) duplicar un bridge por uso — viola DRY; (d) hacer que `run_local_minion` cargue historial ya — válido como siguiente slice, pero no bloquea jobs; el bridge ya reutiliza el sustrato.
**Rationale / Evidence**: suite **3238 passed**, 13 skipped, 3 xfailed; `ruff`/`mypy` limpios. Smoke real tras el refactor: `ok=true`, 25 turnos, 10 tool turns, 1 leg activo, 0 plomería; 19,1 s / 107,6 s / 9,7 s. Tests nuevos: perfiles/render, `run_profile` provider/toolbox, `MiniLocalBridge` (tools, historial, health, factory) y checkpoint de `AgenticJobDriver` con `continuity_id`.
**Consequences**: el mismo espejo/perfil/bridge sirve para smoke, `job_submit` y minions; `local-mini` es la vía multiturno simple. Deuda: (1) `run_local_minion` aún no carga historial (adaptador pendiente); (2) el CLI `red-pill mini` no está cableado; (3) el E2E real de `job_submit` con Forge/Loom y systemd queda por probar; (4) el 35B/9B siguen diferidos por RAM.

---

## [AD-065] Mini arnés local Forge/Loom — primera prueba real (GPU + NPU por sockets)
**Date**: 2026-10-23
**Status**: ACCEPTED & IMPLEMENTED. Implementa RFC_SESION_PORTABLE_MODEL_SWITCH §8.
**Context**: el RFC §8 quedó ratificado (Forge GPU, Loom NPU, UDS, sin handshake, prompts en inglés). El primer intento con Loom 35B (Qwen3.6-35B-A3B, 22,1 GB de footprint) provocó OOM y reinicio del sistema: no cabe con el IDE/OS en 29 GB. Se midieron alternativas FLM: Qwen3.5-9B usa 11,8 GB, Qwen3-8B usa 7,3 GB (pico 7,6 GB). Forge con Granite-4.1-8B entraba en bucle y rompía la indentación; Qwen3.5-9B Q4 (GPU) resolvió la tarea.
**Decision**:
1. **Paquete `src/red_pill/mini/`**: `providers.py` (OpenAI chat por UDS y HTTP localhost), `tools.py` (`list_files`, `read_file`, `write_file`, `edit_file`, `run_tests`; jaula de workspace, caps y timeout), `session.py` (`MiniSession`: system prompt mínimo, replay del espejo, tool loop, migración de leg), `smoke.py` (fixture + 3 fases).
2. **Modelos v0**: **Forge = Qwen3.5-9B Q4_K_M en GPU** (ctx 4096, `MemoryMax=7G`); **Loom = Qwen3-8B-NPU2 en FLM** (`qwen3:8b`, ctx 4096, `MemoryMax=10G`, pico medido 7,6 GB). Qwen3.5-9B-NPU (11,8 GB) y Qwen3.6-35B-A3B (22,1 GB) quedan **diferidos** por RAM; el 35B no se usa con el IDE abierto.
3. **Sin handshake/Búnker/RAG**: identidad operativa mínima (Forge/Loom, rol, operador, `SESSION_SHORT`), prompts en inglés técnico, reviewer sin tools. La continuidad la da el historial del espejo.
4. **Cero puertos para GPU** (`llama-server --host gpu.sock`); **FLM en `127.0.0.1:52625`** (v0 aceptado; netns+UDS es hardening fase 2). Todo corre en unidades transitorias `systemd --user` con `MemoryMax` y `MemorySwapMax=0`: si un modelo se pasa, muere el proceso, no el sistema.
5. **Migración**: `MiniSession.switch_to` cierra el leg anterior y abre el nuevo con la misma `continuity_id`; un solo leg activo. Cada turno se apenda al espejo con `tool_call_id` y `run_ref`; no se guardan parejas huérfanas.
6. **Smoke real** (fixture de `median` con RUN_ID): Forge lee, ejecuta, corrige y reporta; Loom revisa sin tools y cita RUN_ID/aserción; Forge añade el test del caso límite. Resultado: `ok=true`, 25 turnos, 10 tool turns, 0 plomería, 1 leg activo; fases 20,8 s / 84,4 s / 9,7 s.
**Alternatives**: (a) Loom 35B — OOM/reinicio; (b) Loom 9B — 11,8 GB, margen insuficiente; (c) Forge Granite 4.1 — bucle e indentación mixta; (d) Loom API externa — válido pero no prueba NPU local; (e) mismo 8B para ambos cuerpos — válido pero no heterogéneo. Se elige Qwen3.5-9B GPU + Qwen3-8B FLM.
**Rationale / Evidence**: suite **3229 passed**, 13 skipped, 3 xfailed; `ruff check src/ tests/ scripts/` y `mypy src/red_pill/` limpios. Smoke con cgroups; `/tmp/red-pill-mini` (sin BD viva); reporte con `nonce_in_tool_history`, `nonce_in_forge_text`, `nonce_in_loom_text`, `loom_no_tool_calls`, `tests_pass_after_fix`, `tests_pass_after_apply`, `new_test_added`, `one_active_leg`, `plumbing_rows=0`.
**Consequences**: existe un mini arnés real, local y acotado que usa el sustrato de sesión. Deuda: (1) 35B/9B diferidos por RAM; (2) FLM sigue en puerto loopback hasta el hardening netns+UDS; (3) no hay “coma”/KV persistente entre procesos; (4) las unidades `systemd` son transitorias, no plantillas permanentes; (5) Loom 8B tarda ~90 s por el thinking; se puede ajustar prompt/thinking; (6) el `run_tests` depende de pytest en el Python que ejecuta el arnés.

---

## [AD-064] Pi como fuente canónica del switch (UUID + tools nativas)
**Date**: 2026-10-23
**Status**: ACCEPTED & IMPLEMENTED. Habilita el smoke real opencode↔pi.
**Context**: al preparar el switch real opencode↔pi aparecieron dos defectos: (1) `PiSourcePlugin` indexaba por ruta relativa (`--cwd--/<timestamp>_<uuid>.jsonl`) mientras el bridge y el registro usan el **UUID del header**, así que `sync_originator(pi:<uuid>)` respondía «Session not found» (los 2 errores del backfill); (2) `load()` compacta `toolResult` como texto de assistant, perdiendo la pareja `toolCall`/`toolResult` que el replay necesita.
**Decision**:
1. `_index_sessions` indexa **también** por el UUID (sufijo tras el último `_`); `discover` deduplica por fichero y conserva la ruta relativa como clave de Memento (sin migrar puntos ya archivados). `load`/`workspace_of` aceptan ambos.
2. `load_canonical` propio de Pi: conserva `toolCall` (id/nombre/argumentos) como `assistant.tool_calls` y `toolResult` como `role=tool` con `tool_call_id`; el `thinking` se descarta. `load()` sigue compactando para Memento (sin cambios).
**Alternatives**: (a) cambiar las claves de Memento a UUID — rompe continuidad de puntos existentes; (b) seguir usando solo texto — el replay cruza llamadas sin resultado y pierde fidelidad; (c) parsear pi en el switch en vez de en el source — duplica lógica.
**Rationale / Evidence**: smoke real (2026-10-23):
- **opencode→opencode**: A leyó un nonce, se cerró A y se borró el fichero; B (misma alma) respondió el nonce sin tools y con **1 leg activo**.
- **opencode→pi**: el payload filtrado (740 chars, sin `<bunker_context>`) se rehidrató en Pi (`openrouter/xiaomi/mimo-v2.6-flash`); respondió el nonce y **0 tool events**.
- **pi→opencode**: Pi leyó otro nonce (tool nativa), se cerró; el espejo guardó **1 tool row** con el resultado; OpenCode (sesión nueva, mismo `continuity_id`) respondió el nonce **sin tools** y con **1 leg activo**. Payload 745 chars, sin Búnker.
- `pytest tests/test_chronicle_sources.py`: alias UUID + `load_canonical` verde.
**Consequences**: Pi es fuente de primera clase para el switch sin tocar las claves de Memento. Deuda: `antigravity` sigue en texto. El proveedor usado por Pi es configuración del arnés, no del código: el smoke inicial usó OpenRouter por una key caducada; **verificado después con `opencode-go`** (misma prueba: payload 740 chars, nonce correcto, 0 tools) tras renovar la autenticación del operador. Las sesiones de prueba quedan en `~/.pi/agent/sessions` y `opencode.db`.

---

## [AD-063] Replay limpio: la plomería de identidad no se reencarna
**Date**: 2026-10-23
**Status**: ACCEPTED & IMPLEMENTED. Complementa AD-060/AD-062.
**Context**: el primer smoke real opencode→opencode (dos sesiones, misma alma, migración) demostró que el espejo captura los tool calls del `sovereign_handshake` y sus resultados (`<bunker_context>`). Al rehidratar, ese snapshot de identidad/telemetría del cuerpo viejo viajaba al nuevo: ruido, contexto rancio y duplicación de la inyección (el cuerpo nuevo hará su propio handshake). Además infla el replay y el espejo.
**Decision**: filtro **solo en replay** (`render_history` y `replay_messages`): se eliminan las parejas call/resultado de herramientas de plomería (`sovereign_handshake`, `interceptor_rp`, `refresh_session_context`). El espejo las conserva para auditoría/Memento; no se reinyectan al reencarnar. El filtro empareja por `tool_call_id`, así que no deja resultados huérfanos ni rompe la secuencia OpenAI.
**Alternatives**: (a) filtrar en la ingesta — ahorra espacio pero pierde auditoría y obliga a migrar; (b) stub de las salidas — conserva la llamada pero sigue metiendo contexto rancio; (c) ignorarlo — el smoke demostró que el payload arrastraba el Búnker del cuerpo anterior.
**Rationale / Evidence**: smoke real (2026-10-23, opencode A → opencode B, migración con A cerrado): A leyó un nonce con `read` (2 tool results en el espejo); se borró el fichero; B respondió el nonce **sin tool calls** y con un solo leg activo (A `expired`). El payload sin filtrar medía 3.330 chars e incluía `<bunker_context>`; con filtro, **746 chars**, sin plomería y con el nonce intacto. Una segunda sesión (D) respondió el nonce desde el payload filtrado. Suite `pytest tests/test_session_switch.py` verde; regresión `test_replay_filters_identity_plumbing`.
**Consequences**: el replay queda limpio y más barato; el espejo mantiene la auditoría. Deuda: si se quiere ahorrar espacio, excluir la plomería en la ingesta (no urgente: 1 MB de 35 MB). Las sesiones de smoke (`ses_e96d...`) quedan en `opencode.db` como sesiones de prueba.

---

## [AD-062] Espejo con presupuesto duro (100 MB) y degradación observable
**Date**: 2026-10-23
**Status**: ACCEPTED & IMPLEMENTED. Endurece AD-060/AD-061; no cambia el contrato del espejo.
**Context**: el backfill dejó 42 MB / 19.557 turnos en 45 días (~1 MB/día, picos de 4,6 MB/día). El 89 % del payload son **resultados de tools** (18 MB) y argumentos de tool-calls (8,3 MB); el texto de conversación son solo 2 MB. La política anterior (30 días, solo almas muertas) no acotaba el crecimiento de almas activas y, además, el TTL de inactividad nunca se materializaba (`ttl_state` solo cambiaba con `unregister_session`). El Operador fija un presupuesto de **100 MB** para esta pieza, monitorizado, y la intención de un **agente local acotado** (8 GB VRAM/NPU/iGPU) que use el espejo como memoria externa, no como prompt de despertar.
**Decision**:
1. **Techo duro configurable** `SESSION_MIRROR_MAX_BYTES=104857600` (100 MB, db+wal). Alertas al `SESSION_MIRROR_WARN_PCT=80` y emergencia al `SESSION_MIRROR_EMERGENCY_PCT=95`. Señales: `session_mirror_stats` (estado) y `session_mirror_budget` (dolor al cruzar umbral).
2. **Stubbing de resultados de tools** (`SESSION_MIRROR_TOOL_RETENTION_DAYS=7`, `SESSION_MIRROR_KEEP_TOOL_RESULTS=200`): se sustituye el contenido por `[output purgado: N chars]` solo si el turno es viejo **y** queda fuera de los últimos 200 del alma. Se conservan `tool_calls` y `tool_call_id`: la pareja call/resultado sigue siendo válida para replay; se pierde el volcado, no la narrativa.
3. **Tope por turno** (`SESSION_MIRROR_MAX_TURN_BYTES=262144`): contenido recortado con marcador; `tool_calls` gigantes se compactan a id/nombre + `[truncado N chars]` manteniendo JSON válido. Una fila no puede romper el presupuesto.
4. **Degradación de emergencia** (`enforce_budget`), en orden: stubbing → purga de almas muertas → recorte de los turnos más viejos de almas activas conservando `SESSION_MIRROR_MIN_TURNS_PER_SOUL=200`. Nunca se baja de ese mínimo; si aun así no cabe, se reporta `over_budget` y se emite dolor (no se destruye contexto reciente para cuadrar).
5. **TTL de inactividad materializado** (`MULTISESSION_IDLE_TTL_MIN=30`): el Janitor marca `expired` los legs sin latido; el handshake reactiva el leg si vuelve (upsert), y D14 lo borra 24 h después. Esto hace que la retención de almas muertas sea real.
6. **El espejo sigue siendo pull-only**: no se inyecta en el handshake (test de regresión); el replay explícito tiene tope `SESSION_MIRROR_REPLAY_MAX_CHARS=60000` (~15k tokens). El agente local acotado lo usa como memoria externa, no como wake-up.
**Alternatives**: (a) presupuesto 1 GB — descartado: 10× el espacio para el mismo valor y más riesgo de arrastrar datos muertos; (b) compresión zlib — 2–3× de ahorro, pero complejidad y migración; se puede añadir después si el stubbing no basta; (c) ventana deslizante de 7 días para todo — perdería narrativa antigua; (d) no espejo / usar solo sesiones nativas — rompe el switch y el histórico unificado; (e) borrar sin stubbing — rompe parejas y replay.
**Rationale / Evidence**: suite **3214 passed**, 13 skipped, 3 xfailed; `ruff`/`mypy` limpios. Tests de cap por turno (JSON válido), stubbing (reciente intacto, últimos N, idempotente), presupuesto de emergencia (muertos fuera, activos ≥ mínimo), métricas/señales y TTL de inactividad con reactivación. **Medición viva (2026-10-23):** 42,0 MB (41,4 % del presupuesto) → **35,0 MB (33,4 %)** tras stubear 4.031 resultados (6,68 M chars); sin emergencia ni recorte de turnos. Backup previo: `session.db.bak-20261023-pre-ad062`. El resto del peso son outputs de los últimos 7 días; se stubearán al envejecer.
**Consequences**: el espejo queda acotado y observable; con el stubbing de 7 días el peso esperado es ~20–30 MB según actividad (medido: 35 MB justo tras el backfill; baja al envejecer los outputs), siempre por debajo del techo de 100 MB. Deuda declarada: (1) el texto `content` y los `tool_calls` no se comprimen (posible siguiente ahorro); (2) si el espejo se convierte en fuente de Memento hace falta frontera `work/social` y backup como infraestructura crítica; (3) la compactación semántica (Fase 3) sigue siendo necesaria para sesiones muy largas; (4) el runner local multiturno (`continue_local_minion`/perfil de agente acotado) no se construye aquí.

---

## [AD-061] Alma y Coro — retención observable, divergencia y rol transparente
**Date**: 2026-10-23
**Status**: ACCEPTED & IMPLEMENTED. Cierra los flecos de Fase 2/Fase 1 acordados con el Operador.
**Context**: AD-060 dejó el espejo sin política de retención y el arnés RedPill sin captura; `fetch_divergent_turns` e hidratación por rol seguían pendientes. El Operador fijó dos criterios: (a) TTLs conservadores + monitorización medible (no ajustar a ciegas), y (b) identidad transparente para el agente (rol/misión/campaña no se declaran desde el modelo).
**Decision**:
1. **Retención conservadora y observable del espejo.** `SESSION_MIRROR_RETENTION_DAYS=30`, pero solo se purgan almas **sin ningún leg activo**; un alma viva nunca pierde turnos. Turnos sin `ts` fiable se conservan y se reportan. Janitor `session_mirror_purge` devuelve métricas (filas antes/después, almas, bytes, muertas/huérfanas/sin fecha, cutoff), emite señal de estado `session_mirror_stats` y señal de dolor `session_mirror_growth` solo al cruzar umbrales (`SESSION_MIRROR_GROWTH_ROWS`/`_BYTES`). CLI `session mirror stats`. Regla de diseño nueva: `docs/CORE/CONVENTIONS.md` §10.10 (TTL *y* monitorización para todo artefacto acumulativo).
2. **`fetch_divergent_turns` (D15).** Metadata del reloj (`global_turn_seq` + registro); contenido **solo** de turnos espejados con `global_turn > 0` (el backfill histórico no tiene reloj: no se inventa). Siempre los turnos propios; los ajenos solo con intersección de afinidad. `MULTISESSION_DIVERGENT_ALLOW_ALL` es flag de operador (nunca argumento del modelo).
3. **Captura en el arnés RedPill.** `run_local_minion(..., continuity_id, mission_id, originator, global_turn)` vuelca sus `messages` (sin system) al espejo al terminar; sin alma/misión no escribe. Esto cierra la captura del lado RedPill sin tocar los bridges.
4. **Rol transparente + hidratación por rol.** `role`: `REDPILL_ROLE` → rol ya atado al leg → `task`; el argumento del modelo se ignora (se conserva en el schema por compatibilidad, documentado como no autoritativo). Campaña: env → leg registrado. Misión: env → `repo:rama` → adhoc (el argumento no la declara). Políticas en `session/roles/` (orchestrator=digest global, task=compacto, spawn=silencioso) resueltas por dato, nunca por inferencia.
5. **Evento del switch:** se mantiene `intent_updated` (taxonomía cerrada). Si un consumidor necesita distinguirlo, se valorará `model_switch`.
6. **Sync-on-switch (F7).** `switch_model` sincroniza el transcript del leg anterior al espejo **antes** de leerlo (`sync=True`, idempotente). Es el disparador que ata el relleno al único momento en que su ausencia duele; un provider sin fuente canónica se ignora con log (no rompe el switch). Así la Fase 1 deja de estar «mergeada pero vacía».
**Alternatives**: (a) trim de turnos antiguos también en almas vivas — riesgo de perder contexto en una tarea larga; se descarta hasta tener métricas; (b) contenido de divergencia desde backfill — exigiría inventar `global_turn` por timestamp (frágil); (c) rol inferido del texto/origen — prohibido por F2 (dato, no inferencia); (d) permitir `allow_all` por argumento — spoofing de lectura.
**Endurecimiento adversarial (ronda 2026-10-23, antes de dar la fase por buena):**
- **A1 (crítico) — `affinity_filter` ampliaba visibilidad.** El handler unía la afinidad del modelo a la propia: un argumento con `mission:repo:otra` abría turnos ajenos (escalada por argumento). Ahora el filtro **solo estrecha** (intersección); cruzar exige `MULTISESSION_DIVERGENT_ALLOW_ALL` del operador. Test negativo incluido.
- **A2 — la purga borraba turnos sin `ts`.** Una almas muerta con turnos antiguos fechados + uno reciente sin fecha se borraba entera. Ahora el `DELETE` exige `ts > 0`; los sin fecha se conservan y se reportan (`unknown_age_souls`). Test.
- **A3 — carrera purga↔despertar.** El `DELETE` re-verifica `NOT EXISTS (leg activo)` en la misma transacción; un leg que despierta entre el snapshot y el borrado no pierde el espejo. Test con snapshot mentiroso.
- **A4 — starvation en divergencia.** Un `LIMIT cap*5` podía devolver vacío con muchas filas ajenas intercaladas; el escaneo sube a `min(max(cap*50,500),5000)` antes de filtrar. Test con 30 turnos ajenos y el propio al final.
- **A5 — orden de publicación del switch.** Se abre el leg nuevo antes de cerrar el viejo; si el upsert falla, el alma conserva cuerpo. Test de fallo.
- **A6 — `tool_calls` corrupto** en una fila del espejo ya no rompe la lectura (JSON inválido → `None`). Test.
- **A7 — descubrimiento del janitor**: test explícito de que `session_mirror_purge` entra en el barrido.

**Ronda 2 — revisión adversarial independiente (2026-10-23, antes de aceptar):**
- **B1 (crítico) — el bypass de afinidad seguía vivo por el handshake.** El modelo podía pasar `affinity` y se persistía; el filtro D15 leía esa fila como confianza. Ahora la afinidad explícita sale **solo de env `AFFINITY`** (operador); el argumento se ignora. Test de handshake con afinidad ajena.
- **B2 — `switch_model` no validaba propiedad del alma.** `previous_originator` y `target.originator` podían apuntar a otra alma (cerrando su leg o corrompiendo su misión). Ahora se rechaza (`ValueError`) si el cuerpo pertenece a otra `continuity_id`. Tests.
- **B3 — el cursor por defecto de divergencia ocultaba turnos.** Usaba `last_seen_global_turn`, que el handshake avanza cada turno. Default ahora `0` (la visibilidad D15 sigue filtrando); el llamante pasa su marca. Test.
- **B4 — resume nativo en bridges sin estado.** `continue_conversation` es abstracto (existe siempre) y los bridges locales lo implementan como `prompt` sin estado. Ahora se exige `get_capabilities().conversation_resume`; si no, replay. Test.
- **B5 — captura local muerta sin identidad.** `run_local_minion` acepta identidad por env del job (`REDPILL_ORIGINATOR`/`REDPILL_MISSION_ID`) y resuelve alma/misión del registro; sin cuerpo no escribe. Test.
- **B6 — `base_dir` se ignoraba en opencode.** El mapa de fuentes ahora declara el kwarg de aislamiento correcto (`db_path` vs `base_dir`) y no traga `TypeError`; un sync aislado no puede leer la BD viva. Test.
- **B7 — JSON válido no-lista rompía lectores.** `tool_calls` se coacciona a lista o `None` en espejo, store, render, replay y handler. Test con `{}`.
- **B8 — un fallo al publicar repetía la llamada al modelo.** `_publish` sale del `try` de invocación; si falla, se reporta en `result.errors` (`__publish__`) y no se reintenta otro target. Test.
- **B9 — un turno gigante vaciaba el replay.** El turno más reciente se recorta (`…`) en vez de descartarse. Test con 70 KB.
- **B10 — captura no idempotente.** `run_ref` da `source_ref` deterministas; un job reintentado no duplica el diálogo. Test.
- **B11 — parejas tool-call/resultado rotas sin `role=tool`.** `_canonical_turns` quita `tool_calls` sin pareja (resultado como `user`) para no generar secuencias OpenAI inválidas. Test.
- **B12 — starvation de divergencia.** El filtro D15 se hace **en SQL** (`json_each` sobre la afinidad del reloj), sin límite de escaneo en Python. Test con ruido ajeno.
- **B13 — `continuity_id` desde el modelo.** El alma ya no se acepta por argumento: env `REDPILL_CONTINUITY_ID` → registro → emisión. Test de spoof.
- **B14 — el switch reseteaba el cursor de eventos.** `_publish` conserva `max(viejo, atado)`. Test de self-switch.
- **B15 (riesgo, no bug reproducido)** — el orden de replay es por `seq`, no por `(ts, seq)`; dos legs de la misma alma sincronizados fuera de orden podrían invertir la conversación. Se documenta como riesgo de diseño; si aparece, ordenar por `(ts>0, ts, seq)`.

**Rationale / Evidence**: suite completa **3205 passed**, 13 skipped, 3 xfailed; `ruff check src/ tests/` y `mypy src/red_pill/` limpios. Tests de purga (viva intacta, muerta antigua/reciente, sin fecha, carrera), métricas/señales del janitor, divergencia (propio/intersección/ajeno, filtro que no amplía, spoof por handshake, cursor por defecto, starvation, cursor negativo, JSON corrupto), captura del minion (env, idempotencia, parejas), rol heredado/ignorado, sync-on-switch, ownership del switch, fallo al publicar y recorte de turnos gigantes.
**Consequences**: la retención es ajustable **con datos** y el rol deja de ser un parámetro del agente. Deuda declarada: (1) turnos históricos sin `global_turn` no aportan contenido a divergencia hasta que exista captura en vivo de ese arnés; (2) `switch` *mid-run* dentro de `run_local_minion`; (3) D23 (firma de notas) se pospone hasta que sea bloqueante. Ratificado para Fase 3: compactar **no** cambia el `continuity_id`; `compact_parent` apunta al segmento anterior y el resumen entra en el espejo preservando parejas tool-call/resultado.

---

## [AD-060] Alma y Coro Fase 1 — espejo canónico de turnos y `switch_model`
**Date**: 2026-10-23
**Status**: ACCEPTED & IMPLEMENTED. Extiende AD-055/AD-056/AD-057. Cierra además los restos de Fase 2 (`unregister_session`, purga D14).
**Context**: con la identidad (0a), el registro/reloj (0b) y el coro (Fase 2), la continuidad seguía siendo «resurrección» (F6 del informe de campo): no existía espejo de conversación ni `switch_model`, así que un cuerpo nuevo no podía continuar sin re-ejecutar. La motivación profunda es resiliencia de proveedor (RFC_ALMA_Y_CORO §2.4.2), no comodidad.
**Decision**:
1. **Espejo canónico (`session_mirror`, schema v4).** Turnos `{continuity_id, mission_id, global_turn, seq, role, content, tool_calls, tool_call_id, model, ts}` + `originator/source/source_ref`. `seq` monotónico por alma; `tool_calls` JSON OpenAI íntegro; `tool_call_id` (ampliación necesaria para emparejar `assistant.tool_calls` ↔ `role=tool`); idempotencia por `(continuity_id, originator, source_ref)` con índice único parcial. `MirrorStore` en `contracts.py`, `SessionMirror` en `session/mirror.py`; el esquema y la migración siguen en `store.py` (dueño único de `session.db`).
2. **Poblado desde transcripts.** `chronicle_sources/base.py:load_canonical()` es aditivo (default texto, sin tocar Memento); `opencode` y `claude_code` lo sobrescriben conservando `tool_use`/`tool_result` nativos (pareja call ↔ resultado). `pi`/`antigravity` caen al default texto (deuda declarada). Backfill fail-soft por leg (`sync_registry`) y CLI `red-pill session mirror sync [--continuity|--originator]`. En arnés externo NO hay captura por turno barata (el handshake corre antes de la respuesta y el hook solo relayea texto): el espejo se sincroniza de forma perezosa al hacer switch o por backfill.
3. **`switch_model` (contratos, no concreciones).** Misma familia → resume nativo (`continue_conversation` con el `session_id` del leg); cruzado → replay desde el espejo (`prompt` con `<history>` renderizado); fallback por quota (`AllModelsExhausted`/rate-limit) al siguiente target con replay, sin reutilizar jamás un `conversation_id` ajeno. Publica al tablón: cierra el leg anterior si cambia de cuerpo, abre el nuevo con la MISMA alma/misión/campaña/afinidad/rol/linaje y deja un evento `intent_updated`. No escribe en el espejo (el transcript es la fuente).
4. **Arnés externo = rehidratación.** `rehydrate_payload` + CLI `red-pill session rehydrate` emiten el bloque para abrir una sesión nueva con el mismo `continuity_id` (las herramientas ya hechas no se re-ejecutan). **Arnés RedPill = replay real**: `replay_messages()` conserva `tool_calls`/`tool_call_id` para alimentar directamente al proveedor.
5. **Restos de Fase 2.** `unregister_session` (cierre explícito del leg, `ttl_state=expired`) + purga D14 (`MULTISESSION_PURGE_AFTER_SECS`, 24h; el handshake purga de forma perezosa; `mission_events` intacto). Un leg que vuelve a latir se reactiva (`upsert_session` → `ttl_state=active`). El tablón y `check_parallel_sessions` ocultan legs expirados.
**Alternatives**: (a) usar los marcadores `[TOOL: ...]` de `load()` — pierde la pareja call/resultado y el replay con tools; (b) espejo en ficheros JSON — duplica la fuente y complica la idempotencia; (c) capturar por turno en arneses externos desde el handshake — imposible sin el transcript (el hook no lo expone); (d) reutilizar `conversation_id` entre proveedores — incompatible por diseño (RFC-MODELSWITCH-001 §5); (e) borrar el leg al cerrar — pierde auditoría; se marca expirado y la purga lo retira.
**Rationale / Evidence**: suite focalizada 82 passed (mirror/switch/subsystem/events) y suite completa en el gate; `ruff`/`mypy` limpios. Tests: roundtrip con `tool_calls` intactos, secuencia por alma, dedupe de backfill, migración v3→v4, extracción canónica opencode/claude, resume nativo, replay cruzado con resultado de tool, fallback por quota, cierre/apertura de leg con la misma afinidad y rehidratación con `continuity_id`.
**Consequences**: existe base real para reencarnar sin re-ejecutar y para sobrevivir a la caída de un proveedor. Deuda declarada: (1) captura canónica de `pi` (toolCall/toolResult) y `antigravity` (export plano); (2) seam de switch *mid-run* dentro de `run_local_minion` (hoy el replay se dispara entre runs/etapas); (3) `fetch_divergent_turns` (D15) e hidratación por rol siguen como restos de Fase 2, ahora con contenido en el espejo.

---

## [AD-058] Pillow 12.3.0 — CVEs aceptados; fastembed y re-embedding en la próxima MAYOR
**Date**: 2026-10-22
**Status**: ACCEPTED (temporal). Plan vinculado a la próxima versión **mayor**.
**Context**: `pip-audit` (bloqueante) del CI detectó 35 CVEs en `pillow 12.3.0` (fix 13.0.0); `certifi` se actualizó a 2026.10.19. El proyecto usa `fastembed` para los **embeddings de texto** de la memoria (`paraphrase-multilingual-MiniLM-L12-v2`, 384d). `fastembed` arrastra `pillow` para sus modelos de **imagen** (que NO usamos) y no permite `pillow 13` en 3.13+/Windows: el resolver retrocede y el lock es irresoluble con 13. Forzar 13 con override es posible, pero es un bump mayor que puede romper el código de imagen/media (PIL) y no arregla la dependencia en otras máquinas.
**Decision**:
- **Aceptar `pillow 12.3.0` por ahora**: los 35 IDs se añaden a `[tool.pip-audit]` y al audit bloqueante del CI, con justificación. CI verde (`No known vulnerabilities found, 37 ignored`).
- **Próxima versión MAYOR**: sustituir/actualizar `fastembed` y **re-embeber todas las colecciones** con backup previo. Trigger: la próxima mayor (o cuando `fastembed` permita `pillow 13`, lo que ocurra antes).
- Riesgo actual: local y bajo — los CVEs son de *parsing* de imágenes; procesamos imágenes locales/trusted (imagegen), no expuestas.
**Plan de la mayor**:
1. Backup: snapshot de Qdrant + `bunker_queue.db`/`session.db` + Memento.
2. Sustituir `fastembed` (o el backend de embeddings) por uno que no arrastre `pillow` (o que permita 13).
3. Re-embeber TODAS las colecciones (work ~22k, social ~1.6k, y las demás) con el mismo modelo/dimensión (384d) o migrar el espacio con índice dual y validación de recall.
4. Validar paridad de recall/calidad y el arnés media con PIL 13.
5. Quitar los ignores de pillow y actualizar el lock.
6. Verificar instalaciones/actualizaciones en otras máquinas.
**Alternatives**: (a) forzar pillow 13 ahora — riesgo media/PIL y no arregla fastembed en 3.13+/otras máquinas; (b) ignorar sin plan — deuda sin trigger; (c) sustituir fastembed ahora — coste alto (re-embedding) sin urgencia local.
**Consequences**: CI verde y riesgo local acotado; deuda explícita con trigger y plan. `certifi` sí se actualizó; el extra `hf-transfer` de `huggingface-hub` se retiró (eliminado en 1.21.0). El plan de re-embedding se desarrolla en la nota de deuda de la próxima mayor.
**Update 2026-10-23**: dos CVE nuevos de parsing en `pillow 12.3.0` (`CVE-2026-114501`, `CVE-2026-112398`, fix 13.0.0) se aceptan bajo la MISMA política y quedan en `ignore-vuln` de pyproject + CI. `setuptools` sube a `>=84.1.0` (lock 84.2.1) por `GHSA-xmj3-9gf7-h52w`; ya no se ignora.

---

## [AD-057] Alma y Coro Fase 2 (slice 2) — sala de guerra, digest SILENT/HEADER y tablón por misión
**Date**: 2026-10-22
**Status**: ACCEPTED & IMPLEMENTED (local, rama `feat/2-coro-digest`). **Panel adversarial de 3 lentes: CLEARED; P1 corregidos.**
**Context**: con `mission_events` (AD-056) y el registro (AD-055), falta que un alma se entere al despertar de lo que pasó y de quién más está viva, sin inflar el contexto.
**Decision**:
- **`check_parallel_sessions`** (MCP, solo lectura): `global_turn`, tu `last_seen`, divergencia y sesiones recientes con originator/alma/misión/campaña/rol/delta/ttl/afinidad y (opcional) rama/worktree/head. Campos saneados.
- **`session_registry.last_seen_event_seq`** (migración v3, ALTER tolerante a carrera) = cursor del digest. El handshake lo fija a `MAX(event_seq)` **después** de calcular el digest (si el digest falla, reintenta); un leg nuevo de un alma hereda el cursor de sus hermanos.
- **Digest en el handshake**: `SILENT` si no hay nada; `HEADER` con `N novedades (desde seq X) · M awaiting_operator · K sesiones paralelas`. Una línea; sin volcar eventos.
  - Novedades: `previous_event_seq < event_seq <= until_seq` de **tu misión de confianza**.
  - `awaiting_operator`: pendientes **abiertos** (sin cursor; la resolución por `unblocked`/`mission_closed` es Fase 2).
  - Paralelas: sesiones **vivas** (liveness), no filas rancias del registro.
- **Identidad**: en arnés con hook (opencode/claude_code), misión/campaña/rol salen **solo del env** (`REDPILL_MISSION_ID`/`REDPILL_CAMPAIGN_ID`/`REDPILL_ROLE`); el argumento del modelo no los declara. Sin hook (pi/antigravity) se aceptan como relay (residual local).
- **`session_board`** agrupado por **misión/campaña** (vivas primero; misión entrecomillada; campaña `mixta` si difiere).
**Alternatives**: (a) volcar eventos en el handshake — infla el contexto; (b) cursor por `global_turn` — pierde eventos del mismo turno (bug de la ronda 1); (c) digest siempre presente — ruido; (d) contar `awaiting` por cursor — desaparece al turno siguiente.
**Rationale / Evidence**: suite **3134 passed**, `ruff`/`mypy` limpios; tests de SILENT, novedades/cursor, `awaiting` abierto, paralelas (liveness), misión de confianza en hook, migración v3 y agrupación del tablón. Panel adversarial CLEARED (sin bloqueante; P1 corregidos).
**Consequences**: el coro ya avisa al despertar y la sala de guerra agrupa por misión; el detalle es pull (`fetch_events`/`session_board`). Siguiente: Fase 1 (alma/switch) y D26 (red).

---

## [AD-056] Alma y Coro Fase 2 (slice 1) — substrato de eventos de misión
**Date**: 2026-10-22
**Status**: ACCEPTED & IMPLEMENTED (local, rama `feat/2-coro`). **Revisado por panel adversarial de 3 lentes y endurecido.**
**Context**: el coro necesita un substrato tipado para que un alma se entere de lo que hace otra sin compartir contexto ni depender de leer su `opencode.db`.
**Decision**:
- `mission_events` **append-only** en `session.db`: `event_seq` (AUTOINCREMENT, **cursor real**), `event_id` (UUID, UNIQUE), `type`, `mission_id`, `campaign_id`, `continuity_id`, `originator`, `global_turn` (referencia del turno), `summary`, `ref`, `sealed`, `created_at`; índices por `(mission_id, event_seq)` y `(type, created_at)`; **triggers** que abortan UPDATE/DELETE.
- Taxonomía **cerrada**: `phase_done, commit, claim_acquired, claim_released, blocked, unblocked, awaiting_operator, intent_updated, mission_closed, objection`. Tipo desconocido → rechazo.
- **Cursor `event_seq`, no `global_turn`**: varios eventos comparten turno y el reloj solo avanza en el handshake; `fetch_events(since_seq)` no pierde eventos. (`since_seq` sustituye al `since_global_turn` del borrador del RFC.)
- **Anti-inyección**: `summary` (máx. 800) y `ref` (máx. 400) se sanean al escribir (sin controles/ANSI, una línea, `<`/`>` neutralizados); el render es una línea por evento.
- **Identidad de confianza**: `announce_intent`/`fetch_events` resuelven al llamante **solo** por bridge del arnés/env (`REDPILL_ORIGINATOR`, `REDPILL_MISSION_ID`); los argumentos del modelo (`originator`, `mission_id`, `continuity_id`, `campaign_id`) **no** pueden auto-declarar identidad. Sin cuerpo compuesto → **fail-closed**. La campaña sale de la sesión, no del argumento.
- **`sealed`** filtrado **en SQL** con `viewer_originator` (antes del LIMIT: no consume cupo ni revela existencia); `count_events` también.
- **`_resolve_session_identity(persist=False)`**: identidad sin reloj ni escritura; sin fila en el registro no se inventa un `continuity_id` (`None`, no alma fantasma).
- **`objection`** en la taxonomía: engancha con la Carta de Límites.
**Endurecimiento (ronda 2 del panel adversarial):**
- **Ancla de confianza en el handshake**: el `originator` del bridge/env manda; el argumento del modelo solo se usa si no hay bridge/env. `REDPILL_MISSION_ID` (env) manda sobre el `mission_id` del modelo. En un arnés con hook, un `originator` ajeno no suplanta a otra sesión.
- **Lecturas deny-by-default**: `fetch_events` solo tu propia misión en este slice; cross-misión se difiere al digest/orquestador con autorización explícita.
- **Migración**: `PRAGMA user_version=1`; una tabla `mission_events` pre-release (sin `event_seq`) se recrea (nunca se desplegó).
- **Cuotas/caps**: 30 eventos/min por `(mission_id, originator)`; caps de 200 en mission/campaign/originator; bidi/zero-width fuera; trigger `no_replace` (`INSERT OR REPLACE` no salta el append-only).
- **Residual declarado**: arneses sin hook (pi/antigravity) siguen aceptando `originator` por argumento; el bridge es un fichero que el arnés debe proteger (endurecimiento de harness, fuera de este slice).
**Endurecimiento (ronda 3, identidad de misión):**
- **La misión de eventos sale del canal de confianza** (env `REDPILL_MISSION_ID` o la rama del workspace), **no** de la fila del registro: aunque el handshake escriba una misión envenenada, el evento no la usa.
- **`sealed` se ata al `originator`** que lo publicó (no a la misión): otro cuerpo de la misma misión no lo ve.
- **Fail-closed con arnés de hook** (opencode/claude_code): sin bridge no hay cuerpo (sin upsert/relay); el argumento del modelo no suplanta. El env `REDPILL_ORIGINATOR` (jobs) gana al bridge.
- **Claves normalizadas con `_clean_key`** (sin neutralizar `<>`, válido en ramas git) y **render saneado**: no se pierden eventos ni se rompe la atribución.
- **`no_replace` por `event_id` y `event_seq`**; `user_version` solo si cambia; `busy_timeout` antes del WAL (arranque concurrente).
- **`sealed` estricto**: un valor no-boolean se rechaza (no se interpreta como público).
- **Deuda de superficie**: los roles headless del backend `local` no exponen `announce_intent`/`fetch_events`; y la misión del manifiesto puede quedar escrita en la fila del registro por un handshake (el evento no la usa; el tablón podría mostrarla).
**Alternatives**: (a) ficheros `.md` — pudren y duplican fuente; (b) tabla sin tipos — pierde contrato/filtro; (c) publicar en misión ajena — spoofing; (d) cursor por `global_turn` — pierde eventos del mismo turno; (e) aceptar `originator` por argumento — identidad auto-afirmada.
**Rationale / Evidence**: panel adversarial de 3 lentes, tres rondas → BLOCKER de identidad corregidos (misión por canal de confianza, `sealed` por originator, fail-closed con hook); suite **3123 passed**, `ruff`/`mypy` limpios; tests de spoof (evento persistido), misión no redirigible, cursor sin pérdida, saneado de claves/render, migración, rate-limit, REPLACE, deny-by-default y env precedence.
**Consequences**: la Fase 2 puede construir el digest ("novedades desde tu `since_seq`"), la sala de guerra por misión y las incursiones/iniciativa. Deuda: digest + `check_parallel_sessions`/`fetch_divergent_turns`; cross-misión autorizado; jobs/awakenings deben aportar `REDPILL_ORIGINATOR`/`REDPILL_MISSION_ID`; arneses sin hook y protección del bridge.

---

## [AD-055] Alma y Coro Fase 0b — registro, reloj, espejo git y tablón desde el registro
**Date**: 2026-10-22
**Status**: ACCEPTED & IMPLEMENTED. Extiende AD-050 (Fase 0a).
**Context**: la 0a dejó viva la identidad de sesión, pero el informe de campo (desk, 2026-10-13) midió tres fricciones: el reloj global no latía (`global_turn_seq` con 0 filas y `next_global_turn` sin llamantes), el espejo git del registro estaba vacío (`upsert_session` no recibía `branch`/`worktree`/`head_commit`) y el tablón (`session_board`) leía los latidos de liveness, no el registro. Además la misión caía siempre a `mission:adhoc-<fecha>` porque el cwd del agente no es un repo.
**Decision**:
1. **Reloj (F1).** `_resolve_session_identity` incrementa `global_turn_seq` una vez por turno con cuerpo (`originator` compuesto) y guarda el valor en `session_registry.last_seen_global_turn`. Solo pasan por el handshake los turnos conversacionales/de trabajo; señales y jobs sin afinidad no incrementan (D2-a).
2. **Espejo git (F4).** Se pasan `branch`/`worktree`/`head_commit` al `upsert_session`, resueltos por `core.gitinfo.git_snapshot` (`git -C`, cacheado 60s, fuera del event loop). `worktree` es la raíz del árbol (`--show-toplevel`, worktree-aware).
3. **Misión por repo tocado (F3 / D22).** Si el workspace del agente no es un repo (IDE abierto en una carpeta padre), la misión se resuelve por el repo de las rutas TOCADAS (`session_index.infer_session_git`, P1b; solo opencode, cacheado 60s). `adhoc` sigue siendo el fallback.
4. **Tablón desde el registro (F2).** `session_board` une el registro por `originator` (alma/misión/afinidad/espejo git) y usa los latidos solo como señal de vivo/activo; las filas del registro sin latido reciente entran como "recientes" (TTL `SESSION_BOARD_REGISTRY_TTL_H`, default 12h). El tablón es una VISTA del registro.
5. **Contratos.** `session/contracts.py` declara los Protocols (`SessionStore`, `PresenceBoard`, `AffinityResolver`; `HydrationPolicy`/`ClaimDriver`/`Compactor` para las Fases 2/4/3) y `session/board.py` implementa `PresenceBoard`.
**Alternatives**: (a) contador materializado por alma en vez de una fila por turno — el RFC §3.1 fija el log append-only (una fila/turno, `MAX()` = reloj); (b) tablón como segundo renderizador — descartado, una sola superficie; (c) `ws:` para la misión — descartado (D15: la afinidad por filesystem no refleja cómo trabaja el operador).
**Rationale / Evidence**: el informe de campo del desk fija F1–F4 con evidencia; suite completa verde (3095 passed) y registro verificado en vivo.
**Consequences**: la Fase 2 (coro) ya tiene dónde apoyarse (reloj monotónico, espejo git y tablón con misiones reales). Deuda declarada: la colisión del bridge entre sesiones top-level concurrentes (P2a, AD-050) sigue diferida, y `repo:<rama>` no distingue dos repos en la misma rama (mejora futura del scope).

---

## [AD-054] Modelo de ramas `solo` (rama viva `next`) vs `canonical`, elegido por config
**Date**: 2026-10-19
**Status**: ACCEPTED & DOCUMENTED. En vigor desde el ciclo siguiente al release 8.2.0. Fuente única: `docs/CORE/WORKFLOWS.md` §0.
**Context**: la guía decía `main` + `dev` (integration), pero `dev` **nunca existió**; el *Release Flow* enseñaba `git merge` + `git push origin main`, que el `pre-push` rechaza; `CONTRIBUTING.md` no describía ramas; y `main` no tenía branch protection en GitHub (solo el hook local). En la práctica, un single-maintainer acumulaba desarrollos en ramas con nombre de RFC (`feat/...`, `fix/p0-...`) que subían a origin; al pedir "acumula otra corrección" en una sesión nueva, el agente no reconocía esa rama como suya. Resultado: colisiones, ramas huérfanas y documentación que contradecía la realidad.
**Decision**:
- **Un solo modelo documentado, dos perfiles** seleccionados por `GIT_WORKFLOW` en `.env` (`solo` | `canonical`). No se mantienen dos guías paralelas: el perfil activo es dato, y la regla de agente sembrada (`seeds/rules/git_workflow.md` → `~/.agent/rules/`) y los templates del scaffold lo reflejan.
- **Perfil `solo`** (actual): `main` estable (solo PR). `next` es la **rama viva**: nombre fijo, opcional, nace de `main`, no está protegida, y **siempre está verde/estable en local** (sin WIP sin commitear). Cada **desarrollo local en worktree** (rama cortada de `next`) entra en `next` **solo por squash** (`git merge --squash`), validando el resultado ya mergeado antes de commitear. Fixes pequeños pueden ir directos a `next`. Release = sincronizar `main`→`next` (merge, nunca rebase), bump + CHANGELOG, **un PR `next → main`**, squash merge, borrar `next` (local y remoto) y tag. El siguiente `next` se recrea desde `main`.
- **Perfil `canonical`**: sin `next`; una rama corta por cambio → PR → `main` → squash → borrar.
- **Invariantes comunes**: prohibido el push directo a `main` y el force-push; Conventional Commits; gate local completo antes de cada push (CI solo corre en PR, a propósito); una rama no es propiedad de la sesión que la creó.
**Alternatives**: (a) mantener `dev` como integration — era ficción, nunca existió; (b) documentar solo el flujo canónico y seguir improvisando el real — mantiene la contradicción que causó el problema; (c) una rama de integración por release (`release/x.y`) — reintroduce nombres no genéricos y la colisión entre sesiones; (d) rebase de `next` sobre `main` — imposible con el hook anti force-push.
**Rationale / Evidence**: el squash `next → main` es lo que ya ocurre (release 8.1.0 = un commit en `main` con 100 commits de PR colapsados). El `pre-push` ya bloquea `main` y non-fast-forward: el modelo se apoya en el guardián existente en vez de inventar otro. `next` de nombre fijo elimina la ambigüedad "esta rama no es mía".
**Consequences**: el remoto queda limpio (`main` + `next` + ramas de PR puntuales), el historial de `main` sigue legible (un commit por release) y `next` conserva un commit por RFC/fase. Coste asumido: `next` no pasa CI (solo el PR de release), así que el gate local es obligatorio. Servidor: rulesets `no direct commit` (`main`: deletion + non-FF + PR squash-only) y `next: sin reescritura` (non-FF, permite push directo y borrado).

---

## [AD-053] El tipo de nodo del DAG es un REGISTRO + el driver secciona en módulos
**Date**: 2026-10-14
**Status**: ACCEPTED & IMPLEMENTED (rama `feat/media-router`, release 8.1.0). Extiende `RFC_JOB_DAG` (ver `docs/TECHNICAL/`).
**Context**: `jobs/drivers/dag.py` (1178 L) mezclaba tres concerns (validación/composición del árbol, ejecución atómica, planificación del step) y decidía el **tipo de etapa** con cuatro escaleras `if type ==` (tipos válidos, validación, expansión, ejecución). Añadir un nodo del DAG nuevo obligaba a tocar los cuatro sitios — el anti-patrón que CONVENTIONS §10.8.2/§10.8.3 prohíbe.
**Decision**:
- El **tipo de nodo** (`agent`/`command`/`compound`/`dag`) vive en `jobs/drivers/dag_types/`: un `StageType` (protocolo con `validate`/`compose`/`kind`/`report_suffix`) **uno por fichero**, que se **auto-registra** (`register(...)`) al importar. El validador (`dag_validate`), el compositor (`dag_compose`) y el ejecutor despachan por la **clave del registro** — sin `if type ==`.
- **Añadir un nodo = escribir `dag_types/<kind>.py` + `register(...)`**; el call site no se toca (§10.8.3).
- El driver se **secciona** en módulos cohesivos (`dag_manifest`/`dag_validate`/`dag_compose`/`dag_fanout`/`dag_exec`/`dag_schedule`), compuestos por **mixins** (call sites intactos); `dag.py` queda como espina fina. Equivalencia de comportamiento verificada byte-a-byte (validate+expand) + suite completa + E2E real.
- Mismo criterio aplicado a `cli.py` (→ `cli_jobs`/`cli_parser`/`cli_commands`/`cli_services`), `annotate.py` (→ `annotation_quality`/`annotate_state`/`annotate_phases`), `core/progress.py` (canal de progreso neutro) y `core/llm_endpoint.py` (endpoint LLM fuente única).
**Consequences**: unidades pequeñas, autocontenidas y de bajo blast-radius; el elenco de tipos del DAG es datos+registro, no ramas. Deuda menor declarada: cobertura por-fichero de la superficie CLI por debajo de 80% (el gate aplicable es global, verde).

---

## [AD-052] Media como datos: el elenco (`media_profiles.yaml`) es la única fuente de máquina
**Date**: 2026-10-14
**Status**: ACCEPTED & IMPLEMENTED (rama `feat/media-router`). Extiende el router/elenco (ver `docs/CORE/MEDIA_MODELS.md`).
**Context**: al montar un modelo **GGUF** (Qwen-Image-2.1-Turbo/Sakura) salieron tres
grietas: (1) `scripts/imagegen/bench_imagegen.py` tenía el registro `MODELS`
**hardcodeado** y `gen_image.py` lo importaba — la doc ("añadir un modelo = añadir
metadata, no código") era **falsa**, con dos fuentes de verdad desincronizables;
(2) `runtimes.yaml` no tenía `kind` para GGUF/sd.cpp, ni bootstrap, ni doc;
(3) discrepancias template↔vivo: `flux2_klein.constraints.dim_multiple` era **16** en
`examples/…` (comentario erróneo) y **8** en el vivo (la verdad: ÷8, conserva 1080,
fijada en `tests/test_media_recipe_hook.py`), y el `runtimes.yaml` vivo **carecía** de
los engines de media que sí traía el template.
**Decision**:
- **Una fuente única de máquina**: el elenco `media_profiles.yaml` declara qué es cada
  modelo **y** su dispatch de carga (`backend` + `pipeline`/`weights`/`quant`/`sampler`).
  Lo consumen el **router** y el **harness**; el harness **traduce** cada
  `modality: image`. Se **deriva** el dict `MODELS` del elenco (ya no está hardcodeado; data over branches,
  CONVENTIONS §10.8.2).
- **`backend`** (`diffusers`|`bonsai`|`sd_cpp`|…) es la clave de dispatch; un `kind`
  nuevo = un loader nuevo en `scripts/<área>/` (registro + módulo-por-implementación,
  §10.8.3). Único sitio con código.
- **Engines en `runtimes.yaml`** (LLM y media): se añade `sd_cpp` (binary/env/build).
  Runtime declarado y no disponible = fallo limpio.
- El elenco pasa a ser **obligatorio** para el harness (falla limpio sin él).
- Corregido `flux2 ÷8` en template+skill; vivo re-sembrado; modelo nuevo con
  bloque `license` (`qwen-research`, `commercial_ok: false`).
**Alternatives**: (a) mantener `MODELS` en código + duplicar en YAML — es la
enfermedad; (b) YAML dedicado `media_models.yaml` — duplicaría id/pipeline/weights con
el elenco; (c) solo diffusers, sin GGUF — pierde Qwen-Image, que **sí** corre en 8 GB
vía sd.cpp; (d) derivar `backend` de `runtime` — conflaciona engine con loader.
**Rationale / Evidence**: 41 tests verdes (incl. `tests/test_imagegen_registry.py`, que
fija la invariante y el fallo limpio); router intacto; `sd-cli` + Sakura genera
**~32 s/imagen a 1024²** (DiT 4.7 GB en VRAM, encoder 8.3 GB en RAM) con VRAM libre.
Riesgo ops documentado: el LLM residente del daemon (~6.8 GB) no se suelta vía
`POST /unload` → los jobs de imagen grandes quedan `PENDING` (el runner no desaloja).
Diseño completo: `docs/CORE/MEDIA_MODELS.md`.

---

## [AD-051] El ciclo de sueño reporta producción real (contador de engramas vestigial)
**Date**: 2026-10-11
**Status**: ACCEPTED & IMPLEMENTED (rama `fix/sleep-cycle-real-engram-counter`).
**Context**: el resumen del ciclo nocturno reportaba `(0 engramas)` **todas** las
noches. Diagnóstico: tras retirar la ingesta legacy `interaction_memories → work/social`
(v8.0.0, AD-034 single-writer), `SleepContext.total_processed` quedó **vestigial** —
ninguna fase lo incrementaba (el incremento vivía en el drenaje retirado). El número no
medía "poco trabajo": medía **nada**, y contradecía la realidad (esa misma noche el pase
agéntico de Memento ascendió 181 notas a `work_memories`, invisibles al resumen).
**Decision**:
- `SleepContext` gana `metrics: dict` + `record(phase, produced, **detail)`; `total_processed`
  pasa a ser la suma real de la producción por fase (se persiste en `sleep_phase_status.json`
  y cruza etapas del DAG).
- Cada fase reporta su producción: hubs escritos (consolidation), chunks promovidos
  (orphan_promotion), vacíos purgados (hygiene), axones tejidos/reparados (axon_weaver),
  hubs erosionados/decaídos/demotados (erosion), puntos podados/lavados (washout),
  reclasificados (revision), artefactos publicados (operator_profile/recent_activity).
  `erode_work_hubs` y `run_rhizodb_washout_and_pruning` devuelven sus conteos.
- El `finalize` compone un desglose por fase + las **ascensiones estáticas de Memento**
  (persistidas por `memento_agentic.py` en `memento_agentic_state.json`, ventana 12h).
- Se retira el número muerto de los `summary` y del log `LAZARUS PULSE`; la unidad pasa a
  "ops" (operaciones sobre engramas), no "engramas" — mezclar altas y olvidos en un único
  número sería igual de engañoso, de ahí el desglose.
**Alternatives**: (a) borrar el log — deja el resumen sin señal de volumen; (b) reconectar
el contador al pipeline real — elegida, con desglose; (c) contar engramas nuevos de Qdrant
por fecha — indirecto y frágil por zona horaria.

---

## [AD-048] Washout genérico de RhizoDB excluye los curados (miembros + hubs)
**Date**: 2026-10-08
**Status**: ACCEPTED & IMPLEMENTED (rama `fix/rhizodb-hardening`).
**Context**: auditoría del paquete RhizoDB de Guillem + contraste con el código vivo.
El washout nocturno genérico (`a_v < 0.1 ∧ s_v < 5.0` → borrado físico) mataba los
miembros curados de social/story (`node_type=memento_engram` / `hubbed` / `origin=memento`)
en ~15-25 noches sin recuperación, contradiciendo M9/AD-034 (eje propio
`last_reinforced_at` → demote a 5a miembros / 10a hubs) y D16/D17 (solo los hubs
estaban exentos del washout genérico). No existe re-ascensión automática para
sellos ya ascendidos (`reinforce_refine` retorna `already_ascended`), así que la
pérdida no era reversible. La investigación de docs/registry no encontró ninguna
decisión que fijara un marco de semanas para los curados.
**Decision**:
- El washout genérico excluye los curados (`node_type=memento_engram`,
  `origin=memento` o `hubbed=true`), igual que los hubs: su olvido sigue en
  `erode_curated` (5a/10a, `last_reinforced_at`).
- Flag explícito de reversión `RHIZODB_WASHOUT_SKIP_CURATED` (default ON).
- Coeficientes del washout a config (`RHIZODB_WASHOUT_GAMMA`, `RHIZODB_S_MAX`,
  `RHIZODB_PRUNE_MIN_ACTIVATION`, `RHIZODB_PRUNE_MAX_STABILITY_DAYS`,
  `RHIZODB_WASHOUT_REFERENCE_DAYS`); scroll paginado (fin del tope de 10k puntos);
  γ atenuada por el tiempo desde el último washout de la colección (cap
  `reference_days`): una doble corrida no poda dos veces la misma franja.
- Hardening del motor (`affect.py`): NaN/Inf → defaults, timestamps ISO/ms
  coerced, `stability <= 0` → olvidado; scores >1 preservados (lentitud de los
  curados, factor Memento 5×).
**Por qué esto y no alternativas**: no bajar el marco temporal de los curados
(no hay decisión documentada que lo fije en semanas; el contrato vivo es 5a/10a);
no añadir re-ascensión automática (no existe hoy y complicaría los sellos); el
flag permite volver al washout genérico sin revertir código.

---

## [AD-040] Etiquetado emocional/temático en tiempo real (Laya) — señalizar, no garantizar
**Date**: 2026-09-27
**Status**: IMPLEMENTADO — RFC-004 P1-P4 DONE (sidecar `redpill-laya-tag.service` desplegado 2026-09-28; flags OFF en prod por RULE 4). Anclado en **RFC-004** (`docs/TECHNICAL/BUNKER/RFC_004_REALTIME_TAG_SIDECAR.md`).
**Context**: el pre-heating (Ferrari 11) calibraba con la ventana caliente de
`interaction_memories` (tier 2, 48h) + heurísticas. La purga del buffer
(53 turnos varados, 2026-09-27) dejó el tier 2 vacío: degrada con gracia pero
el hilo emocional en vivo pierde fuelle. El RFC pedía calibración en tiempo
real del estado emocional + temática.
**Decision**: tag en captura vía sidecar `laya-serve` (emoción/tema/confianza
por turno, ms en CPU), consumido por solera (M8) y pre-heating. Laya aquí SÍ
encaja (al contrario que AD-039): presupuesto de ms, respuestas mínimas,
fallo contenido (tono desviado, no recuerdo corrupto).
**Contrato anti-ingeniería** (decisión explícita del operador):
1. El registro nunca espera: `record_interaction_pair` escribe SIEMPRE; el tag
   va fuera del camino crítico (timeout corto, try/except total).
2. El engrama lleva `tag_status: ok/degraded/failed` + motivo (timeout,
   sidecar caído, confianza baja). Fallo silencioso prohibido; fallo
   señalizado = parte del diseño.
3. Qdrant como ventana: últimos N por solera; trima lo existente (janitor TTL
   + sueño). Sin garantías nuevas ni operaciones exóticas.
4. El interceptor comunica: si ve fallos recientes, añade
   `CALIBRATION WEAK: últimos N turnos sin tag (motivo)` al enriquecimiento.
   Visibilidad en vez de reintentos; sin fallback en caliente.
**Plan**: P1 sidecar `laya-serve` (unit systemd + sentinel que lo vigile) →
P2 tag en `queue_worker` (punto único de drenaje) → P3 solera consume tags →
P4 pre-heating lee tags + línea WEAK. Heurísticas actuales quedan como
lectura por defecto cuando no hay tag (no es fallback: es ausencia de dato).
**Revisión 2026-09-27 (operador):** sin puerto TCP — sidecar **UDS**
(`/run/user/1000/red-pill/laya_tag.sock`, 0600) con servidor asyncio crudo
(sin fastapi/uvicorn, que el venv no trae). Ver RFC-004 §2.1.
**Por qué esto y no alternativas**: no tag en el interceptor (torch en el
proceso caliente; los workers oneshot pagarían 18 s de carga por tick) — por
eso sidecar; no reintentos (el dato tardío no vale en tiempo real); no
garantizar el servicio (decisión explícita: lo que se asegura es el registro).

---

## [AD-039] Router System One (Laya) para elegir prompt — bake-off primero
**Date**: 2026-09-27
**Status**: PARKED 2026-09-27 — F1 completo, zero-shot insuficiente; evidencia en `docs/TECHNICAL/LAYA_ROUTER_BAKEOFF_F1.md`; revisit en ~1 mes o si cambia el supuesto.
**Context**: el prompt único de annotate exigía "Joan me…" y prohibía "Joan implementó" → 50,2% muletilla + sujetos invertidos (voz v2 lo parchea con re-escritura, 100% 1ª persona en piloto pero a coste GPU por nota). El operador propone un clasificador previo barato que elija el prompt (y, si llega a hacer falta, el modelo) por fragmento.
**Decision**: arquitectura en dos capas — System One (Laya-multilingual, CPU, ~33ms) clasifica `dominio × voz` y alimenta el triple `(prompt, model, thinking)` del selector existente (`model_runtime.resolve`, AD-030); System Two (daemon GPU) ejecuta. Confianza baja → prompt default actual (fallback = conducta de hoy, reversible). Jev (TypeSafe) descartado: pesos cerrados + API hosted = egress incompatible con soberanía; Laya (Apache 2.0, auto-alojable) es el equivalente local. Laya NO genera texto: la voz la siguen escribiendo los prompts generativos, el router solo elige cuál.
**Ejes del router**: dominio `work/social/otro` × voz `actúa-Joan/actúa-Aleth/tercero/externo` (+ confianzas). Matriz 2×4 sobre los prompts existentes (`annotate_work/social_*`, `voice_rule_annotate.txt`, `voice_rewrite_user_v2.txt`).
**Objeciones registradas**: benchmark independiente (LargitData) da a Laya-322M 0-36% zero-shot en routing multiturno vs Jev 61-91% — base sin tunear ≠ producción; obliga a multilingual (contenido ca/es) y a medir calibración antes de encender; stack nuevo (torch/transformers, no GGUF → venv aparte, nunca el daemon); a favor: 14.101 notas etiquetadas como fuel de fine-tune + arnés `audit-category`/`audit-dual` ya existente.
**Plan**: F1 bake-off (factibilidad + calidad esperada, este job) → F2 matriz de prompts + flag `MEMENTO_CLASSIFY_ROUTER` (RULE 4, OFF) si el gate pasa → F3 piloto 3 sesiones → F4 migración con `--reconcile` si gana. Gate F1→F2: acuerdo con juez ≥0,80 en dominio + calibración sana + tasa de escalado aceptable; si no pasa: fine-tune con las 14k o se aparca (decisión explícita, no deriva).
**Por qué esto y no alternativas**: no Jev hosted (egress); no otro LLM generativo como clasificador (cuesta GPU por nota y alucina formatos); no prompt único más largo (ya medido: reglas que sirven a medias para todos los casos).

---

## [AD-030.F1] Fallup-watcher v2 (anti-flapping, TOCTOU-safe)
**Date**: 2026-09-27
**Status**: DEPLOYED 2026-09-27 (script ejecutado, service reiniciado en ventana segura: nightly `c3c52f33` COMPLETED 18/18 + daemon idle; `/status` expone `"fallup":{"enabled":true,...}` y el desplegado contiene el watcher verificado por grep).
**Context**: el fallup CPU→GPU (AD-030) evictaba el worker CPU con 5.2G en plena noche y flapeaba con la VRAM viva 7.27GB↔0.73GB (swing 6.5GB). Panel adversarial 3/3 BLOCKER (11 hallazgos R1-R4/E1-E3/P1-P5).
**Decision**: watcher v2 en `src/red_pill/core/fallup.py` (testeable, sin deps de daemon) + bloque fallup en el generador `scripts/setup_background_model.sh` (heredoc DUAL_BIND_EOF, fuente de verdad; PROHIBIDO editar el generado a mano) + `tests/test_fallup_watcher.py` (mocks, nunca 8760 ni systemctl).
- **R1 flapping**: margen global 500MB insuficiente → `FALLUP_MARGIN_GB=0.5` sobre tier de ENTRADA + peor-caso dinámico (`worst_case_gpu_min_free_gb()`, peor entrada GPU entre perfiles distillation con tiers; hoy granite_8b 6.5) + `FALLUP_STABLE_CHECKS=12` + `FALLUP_MIN_IDLE_S=60` (tiers granite_8b 1.5/6.5/7.2/7.7/8.2; VRAM viva 7.27↔0.73). Corrección del juez: margen sobre el tier máximo (7.2+1.0=8.2) es código muerto en tarjeta de 8.15GB y habría bloqueado el fallup real de esta noche (7.27GB→GPU 10240, estable sin OOM); el margen va sobre la entrada (6.5+0.5=7.0).
- **R2 TOCTOU**: `last_active` se actualiza dentro del lock → re-chequeo `elapsed2=time.time()-last_active` tras adquirir el lock + `lock._waiters` (si hay waiters → `stable=0`, `last_result="waiters-busy"`, return sin unload).
- **R3 prioridad**: `LOW_TIMEOUT=10s`/`HIGH=300s` → umbral fijo 15s era código muerto en low y evicción prematura en high → watcher exige `idle>=60` y excluye `last_priority=="low"` (`"low-priority-idle-unloads-anyway"`, el timeout de low ya descarga).
- **R4 perfil**: en CPU `current.n_gpu_layers==0` (dead-code) → `dry_run_gpu_tier(profile)` (copia vía `ModelRegistry.get_resolved_hardware_affinity`, nunca muta; `None` si toca CPU); el próximo request puede ser otro perfil (tiny_aya 4.0GB, llama_32 3.5GB) o experimental sin tiers (`"experimental-no-tiers"`/`"no-gpu-tier-fits"`).
- **E1 worker**: reaper gated solo por `IS_CPU_WORKER` (env) → `main()` con `--serve-cpu` fija `os.environ["MINION_CPU_WORKER"]="1"` + `global IS_CPU_WORKER=True` ANTES de arrancar.
- **E2 cola/reserva**: `check_idle` ignoraba `queue_worker --oneshot` en vuelo y `GpuReservationManager` → gate por proceso (`"queue_worker"`+`"oneshot"` → `"queue-busy"`, sin unload) + `is_exclusive_active()` → `"gpu-reserved"` (nunca por puerto 8760).
- **P1 regen**: editar el generator sin regenerar deja divergencia → tests compilan el generado desde la fuente (`compile()`) y exigen las cadenas del watcher.
- **P2 /status**: sin observabilidad → `"fallup": {"enabled", "stable", "required": 12, "last_result", "last_check_ts", "last_fallup_ts"}`.
- **P3 ramas None/experimental + `_fallup_enabled()` muerto** (model_runtime.py:161, cero usos) → gatea el watcher (`mr._fallup_enabled()`); `None`→`"nothing-loaded"`, experimental→`"experimental-no-tiers"`.
- **P4 sin tests**: `tests/test_fallup_watcher.py` cubre las 12 ramas de `should_fallup`, `worst_case>=6.5`, generator (compila + cadenas) y regresión 2590 (`_same_model` ignora `n_ctx`).
- **P5 tunables sin documentar**: aquí + docstring del heredoc + RUNBOOK §8760.
- **Tunables**: `FALLUP_MIN_IDLE_S=60`, `FALLUP_STABLE_CHECKS=12`, `FALLUP_MARGIN_GB=0.5` (sobre entrada y sobre peor-caso), `FALLUP_WORST_CASE_MIN_FREE_GB=6.5` (piso; dinámico vía `worst_case_gpu_min_free_gb()`).
- **Ventana de deploy**: solo con nightly idle + daemon idle (job `c3c52f33` fuera de GPU, sin requests en vuelo, `/status.busy==false`); deploy = ejecutar el script (hace restart) + verificar `/status.fallup`.
**Por qué esto y no alternativas**: no margen 500MB (flap medido 6.5GB); no umbral fijo 15s (muerto en low/prematuro en high); no chequear `n_gpu_layers` en CPU (dead-code); no matar PID con reserva/cola en vuelo (5.2G nocturnos); no editar el generado a mano (divergencia P1).

---

## [AD-038] Recall de la memoria curada: híbrido + MMR sí, texto enriquecido no (medido)
**Date**: 2026-09-25
**Status**: ACCEPTED (2026-09-25) — híbrido, MMR y dedup post-rewrite encendidos en el operador; voz v2 detrás de flag hasta el piloto; texto enriquecido refutado y apagado.
**Context**: tras la resiembra (AD-037) la memoria estaba íntegra (vectores coherentes, fechas, 0 cruces, 0 sellos rotos) pero recordaba mal: de 13 hechos conocidos, 9 en el top-3. Diagnóstico medido: (1) solo el 28,8% de las notas nombra el proyecto — la nota de una revisión contractual no nombra a la empresa implicada (coseno 0,17 contra su consulta); (2) el 50,2% abre con "Joan me dijo/explicó/pidió…", porque el prompt de voz v1 lo exigía y prohibía "Joan implementó" → muletilla e inversiones de sujeto; (3) el embedder trunca a 128 tokens; (4) paráfrasis del mismo hecho ocupan el top-k. Memento sí tenía todos los hechos (captura completa).
**Decision**:
- **Recall híbrido** (semántico + palabras clave sobre el árbol, RRF) y **MMR** con relevancia por rango, solo en llamantes explícitos (oracle/CLI). El árbol es la verdad y ya sabe qué punto de Qdrant cubre cada línea (`source_lines` + `ascended_point_id`): sin índice nuevo.
- **Texto enriquecido para embeber: NO.** Hipótesis razonable (poner la entidad delante), refutada por el banco: empeora el semántico solo (8/13 vs 9/13) y no suma sobre el híbrido. Se conserva apagado por si otro embedder cambia el resultado.
- **Voz v2** (sujeto = quien actuó, sin muletilla, entidad nombrada) detrás de `MEMENTO_ANNOTATE_VOICE_V2`: cambia el fingerprint de annotate, así que migrar el corpus es un rebuild explícito (el nocturno no re-anota sesiones con pase agéntico) + `memento_ascend --reconcile` para no dejar huérfanos.
- **Método**: medir antes de encender (`tools/memento_recall_bench.py`, solo lectura; el banco de consultas es del operador y no va al repo).
**Evidence**: banco de 13 consultas — plano 9/13 · plano+MMR 9/13 · **plano+híbrido+MMR 12/13** (λ=0,85; 11/13 con 0,7) · enriquecido 8/13 · enriquecido+híbrido+MMR 11/13 hit@3. Verificado en vivo con `search_and_reinforce(hybrid=True)`: la revisión contractual y DL-007 entran en el top-3 en ~0,26 s.
**Por qué**: el fallo era de la interfaz nota→vector, no de captura ni de curación; el híbrido lo ataca sin re-embeber nada ni re-anotar. Lo que no mejoró se apaga en vez de mantenerse por intuición.

---

## [AD-037] Rebuild annotate reanudable + Flash Attention por modelo (MEM-009)
**Date**: 2026-09-25
**Status**: ACCEPTED (2026-09-25) — D5 y F1 implementados y D5 desplegado; F0, F2 y F3 en versión mínima pendientes; F4 y F5 aplazados.
**Context**: el rebuild `7b587370` (MEM-006) se atascó en tres sesiones. La 420 era lenta y cada reintento repetía 40-80 min de extract bueno, porque `annotate_session` era todo-o-nada y **borraba las notas al empezar**. La 444 y la 495 entraban en bucle de DEFER con el daemon reiniciándose (contador 240). La autopsia fuera del daemon (`daemon/.venv`, `verbose=True`) dio con la causa: **`CUDA error: out of memory` en el scratch de prefill**. A n_ctx 10240 y sin FA quedaban 248 MiB libres; un prompt de ~6,3-6,5K tokens (~17,0-17,3K chars) los agotaba. No era contenido "venenoso": era el límite de VRAM del servidor (la 420 pasó por 272 chars).
**Decision**:
- **D5 — `flash_attn: auto|true|false` por perfil** (`model_profiles.yaml`), resuelto en `model_runtime.effective_flash_attn` como fuente única de daemon y clientes. `auto` = GPU ∧ `fa_capable: true`; el worker CPU nunca lo activa; sin declarar = conducta previa. El daemon lo pasa a `Llama()`, lo expone en `/status` y lo cuenta en `_same_model` (es estático del perfil, así que no reabre el thrash de AD-030). `granite_8b → true`.
- **F1 — annotate reanudable**: `annotate/_partial.json` (atómico), con una entrada por split keyed por **rango de mensajes** y revalidada por `content_hash`, más el estado de cada fase (extract/rewrite/score). Un contrato distinto (prompt/engine/voice) resetea el parcial. La salida del LLM pasa `scrub_secrets`+`normalize_noise` antes de persistirse. Las notas huérfanas se borran solo tras el `_meta` verificado. `--from=extract|rewrite|score` degrada con aviso y nunca falla duro; su prerrequisito sale del parcial o de las notas del contrato vigente. `--all` no cambia (desde cero, borra el parcial). Audit trail en `_meta` (umbrales, `from_phase`, `reason`).
- **`work_units()` como fuente única de la unidad de trabajo**: devuelve `WorkUnit(nnn, ref, content, key)`, con la clave derivada del MISMO fichero en la MISMA iteración (el rango repetido cae al stem). Sustituye a `_work_units` + `_range_keys`, que había que mantener en el mismo orden a mano.
- **Aplazado / no se hace**: F2 completo (el registro persistente de venenos con contrato de seis campos se diseñó para un caso que resultó ser VRAM → queda en versión mínima: motivo del skip + distinción muro/veneno), F4 (snap + overlap de boundaries) y F5 (índice por rangos + backfill de 535 sesiones: con el parcial, la frescura binaria por `_meta` basta hoy). F3 se reduce a aplicar en annotate el `prompt_budget()` que refine ya usa (`_split_to_fit`).
**Evidence**: autopsia en proceso limpio: sin FA 7459 MiB usados / 248 libres → ABORT; con FA 6965 / 742 → 6,5K y 8K tokens OK. Tras desplegar (2026-09-25 15:54): `/status.flash_attn=true`, 718-726 MiB libres; el split 001 de la 495 (prompt de 17.420 chars) extrae 7 ideas en 34,6 s con `NRestarts=0`. Tests: `tests/test_memento_annotate_resume.py` (kill a mitad de extract → solo los splits restantes; hash cambiado; scrub del parcial; degradado de `--from`; renumeración de NNN; tri-estado FA).
**Por qué**: la causa del atasco era de configuración (FA), así que se arregla primero; F1 elimina la clase de coste "reintento = rehacer todo". El resto del RFC se queda en lo mínimo que justifican los datos, sin maquinaria especulativa.

---

## [AD-036] Anotaciones del motor equivocado (tiny_aya) — aceptadas como estrato histórico
**Date**: 2026-09-23
**Status**: ACCEPTED (2026-09-23) — opción (c): se acepta la cohorte tal cual.
**Context**: auditoría adversarial pre-commit (panel O2) del rebuild MEM-006. El incidente `tiny_aya` dejó **95 sesiones anotadas con `tiny_aya_water`** (sello `engine`), de las cuales **~4.1k engramas ya fueron ascendidos** en el barrido legacy. La frescura del rebuild era solo por `prompt_version` → el job pineado (granite_8b) NO las re-anotaría: el plan "el rebuild arregla el corpus" quedaba incompleto en silencio.
**Decision**:
- **Se acepta la cohorte tiny_aya (4.128 engramas) sin purga ni re-anotación**: la cata la muestra como la capa MÁS LIMPIA del corpus, y purgarla rompería los hilos de Ariadna/hubs (navegación tejida sobre esos point ids) para ganar solo longitud; el contexto completo vive en Memento (`source_lines`/`refine_ref`) y se puede enriquecer on-demand.
- `memento_annotate --stale-engine` (y `--status.stale_engine`) queda como **bisturí opt-in**, no como camino por defecto.
- La limpieza de duplicados del corpus granite/legacy **NO es decisión nueva**: es **MEM-006 P1-B** (script `memento_dedup_qdrant.py`: agrupa por `session_id+source_lines`, superviviente por score compuesto, dry-run previo; Q2/Q3 abiertas) + **MEM-007 D12** (dedup-at-ascension) / **G5** (P1-B por escribir). La cata corrobora su magnitud.
**Evidence (cata 40% de la cohorte tiny_aya, 2026-09-23)**:
- Determinista (1.651 de 4.128; semilla 7): 98,7% ES · 0,5% raw-dump · 0,4% <120 chars · mediana 300 chars (p10 193 / p90 472) · **3 duplicados exactos (0,1%)** · emoción/theme 100% · `content_verified` 0,2%.
- Juez LLM (granite_8b, submuestra 120 de la cata): **8,3% triviales** vs **17,4%** en la cohorte `granite_8b` (n=46).
- Contraste de duplicación del corpus: tiny_aya **0,1%** (3/4.128) vs `Granite-4.1-8B` **29,7%** (976/3.287) y `granite_8b` **33,9%** (504/1.487) — consistente con los ~1.500 pares work / 678 grupos social de la ronda de redestilado que P1-B debe limpiar.
- Debilidad tiny: notas cortas/uniformes (mediana 300 vs 739 del granite) y sin validación de contenido.
**Por qué**: registra la limitación y la decisión (hallazgo A1 del panel) sin big-bang sobre datos canónicos; la dedup pendiente ya tiene dueño (P1-B) y la cata le da munición (dry-run con números reales).

---

## [AD-035] Task `validate` — la validación de notas Memento y el 4.2-3B como juez
**Date**: 2026-09-23
**Status**: ACCEPTED — medido (golden set).
**Context**: el 4.2-3B suspendió distill/refine (AD-032) y **no era candidato de ninguna task** → `task+model` lo rechazaba (K1: "model … no es candidato de la task … usa custom"), de modo que el validador de contenido (que corría bajo el task legacy `refine`) nunca pudo usarlo. Pero la validación de notas es una **familia de tarea distinta** (juez/detector, no generación) y el 3B es el mejor detector 3B medido (3/5, AD-033).
**Evidence** (golden set 5 casos, `task=validate`, temp 0.1 del transporte):
- `granite_8b`: **5/5** (baseline intacto).
- `granite_4_2_3b`: **4/5** — único fallo: falso negativo sobre `005-investigate-transcript-hash-rfc-9420-8-2` (rechaza una nota válida).
**Decision**:
- Nueva task `validate` en `task_profiles.yaml`: default `granite_8b`; candidato `granite_4_2_3b` (thinking off; receta IBM en el candidato — temp 1.0; la task deja 0.1 para el 4.1; top_p 0.95 = default del daemon: el body del transporte manda los sampling params, verificado en `run_dual_bind.py`).
- `configs/jobs/memento_validate.yaml` pasa de `task: refine` (apaño histórico) a `task: validate`.
- El contrato `validate` debe existir en el `task_profiles.yaml` del entorno (documentado en `examples/task_profiles.yaml.example`); una instalación limpia sin esa task falla con 400 «task 'validate' no existe» (hallazgo de la auditoría adversarial O2).
- El 4.2-3B queda **habilitado** como juez alternativo barato (2.24 GB, cabe entero en GPU); el default del validador sigue el 4.1-8B (5/5) hasta que el operador decida adoptarlo.
- `memento_recalibrate.py` gana `--task` (medir con otro contrato) y parser JSON robusto (`_extract_json_array`, patrón AD-033 #8).
**Por qué**: separa semánticamente validación de generación, permite medir/reemplazar el juez sin tocar distill/refine, y **persiste la receta** que antes solo vivía en el script del bake-off.

---

## [AD-034] Single-writer de memoria — ascensión Memento, hubs, Ariadna, solera y flags por componente
**Date**: 2026-09-21
**Status**: ACCEPTED (rama `feat/memento-single-writer`; flags `SW_*` default OFF → producción intacta).
**Context**: `work_memories`/`social_memories` recibían prompts por DOS vías redundantes (la ingesta `interaction→work/social` del sueño y el chronicle legacy) que sólo añadían ruido y duplicados (la resiembra encontró ~3.000 réplicas). La vía legacy ya estaba retirada; quedaba la del sueño. Además, la **erosión estaba inerte**: el pulse refrescaba `last_recalled_at` de TODO cada hora.
**Decision**:
- **Fuente única**: work/social se alimentan **solo** por **ascensión curada de Memento** (`distill→refine→ascend`). Se **retira** la ingesta `interaction→work/social` (`SW_INGEST_RETIRED`); el buffer `interaction_memories` pasa a semáforo transitorio (TTL gateado por render en Memento + **tope de edad** con señal).
- **Ascensión con dos fechas** (`created_at`=sesión real, `ascended_at`=ascensión) + `node_type`; dedup-at-ascension (ganador determinista por cuerpo); **umbrales por categoría** (work/social).
- **Navegación**: **hubs de sesión** (macro, idempotentes por `point_id`+`hub_input_hash`) + **micro-hilo de Ariadna** por `refine_ref` (`prev/next_member`) + `cross_refs` (axones). El recall omite los miembros `hubbed` (reversible con el flag).
- **Olvido elegante**: eje propio `last_reinforced_at` (no lo toca el pulse), **demote a Memento** a 5a (miembros) / 10a (hubs, piso propio), factores por motor; **fix de raíz** del refresh incondicional (`SW_ABSENCE_GUARD_CONDITIONAL`).
- **Semáforo de situación** (`situation_memories`, solera 20/80 en **dos capas**) leído por el pre-heating — **global** (sin buckets de afinidad). **Telegram** es un canal propio: **fuente chronicle `telegram:<uuid>`** (el uuid de Telegram es el `session_id`) y **registro genérico de orígenes** (`session_origins.json`, `core/origins.py`) que hace que **todos** los sources de providers (opencode/claude_code/pi/antigravity y futuros) ignoren `origin=telegram` — la renderiza solo el source `telegram`. El worker de Telegram queda con un único camino (puente) y captura `session_id` con `originator=telegram`. La afinidad por **filesystem** (cwd/proyecto) se **retiró** — no refleja cómo trabajamos; si se retoma, será **semántica** (keywords del refine).
- **Patrón obligatorio**: **feature flag por componente** (CONVENTIONS RULE 4).
**Por qué**: elimina la redundancia/ruido, conserva la navegación y el archivo (Memento es la fuente de verdad), y **devuelve la vida al olvido**. Verificado con panel adversarial (D1–D12 corregidos).

---

## [AD-030] Servicio de Gobierno de la Inferencia Local
**Date**: 2026-09-15
**Status**: ACCEPTED & IMPLEMENTED (v3 fusionado; PR-0/PR-1/PR-2 desplegados).
**Supersedes**: AD-020 (On-Demand Model Loading) — el mecanismo (lock, unload→load, idle, `/unload`, reaper) se conserva íntegro; cambia la semántica: el daemon ya no sirve UN modelo fijo sino un **selector por tarea×modelo + zona curada + modos custom/experimental + razonamiento nativo**.
**Context**: el pase agéntico Memento (RFC-002) necesita un modelo de contexto largo (`tiny_aya_water`, 32K) mientras el sueño y la conversación usan `granite_8b`. El daemon fijaba UN modelo por `MINION_PROFILE` (restart para cambiar) y el service file llevaba un parche temporal. Además, la llegada de **Granite 4.2** (razonamiento nativo) requería soportar modos thinking (`enable_thinking`/`low_effort`) que llama-cpp-python no expone en su API pública.
**Decision** (v3 — fusiona AD-030 + RFC_INVENTARIO_MODELOS_HARNESS):
- **Selector sin aliases**: `experimental > custom > model > task > config > env`. `task`/`model`/`thinking`/`custom`/`experimental` mutuamente resolubles; id sin resolver → 400 explícito. `task`+`model` exige que el model sea candidato de la tarea (K1).
- **Separación de registros**: `model_profiles.yaml` = calibración HARDWARE + conducta de MODELO (`chat_format`/`null` = template nativo, `tool_format`, `thinking`); `task_profiles.yaml` = curación de TAREAS (conducta + candidatos con `default: true`); `model_runtime.yaml` = config en caliente (`default_model`, `fallup`, `hot_reload`).
- **`model_runtime.py`**: fuente única de resolución compartida daemon+clientes (merge por especificidad: candidato > tarea > perfil-conducta > perfil-calibración > config > env). Incluye parsers `toolcall`/`extract_thinking`, validación de modelos (magic bytes GGUF, `model_validation.json` K5) y presupuesto de contexto dinámico.
- **Razonamiento nativo (Granite 4.2)**: llama-cpp-python NO expone `chat_template_kwargs`; el daemon registra **chat handlers por modo** (`granite-thinking`/`nothink`/`low`) derivados del template nativo del GGUF, seleccionados por request. El bump a llama.cpp ≥ b10603 resultó **innecesario** (0.3.31 ya carga 4.2, refutado por smoke test) → pendiente opcional.
- **Modos custom/experimental**: `custom` = modelo curado con params (licencia fail-closed); `experimental` = perfil virtual completo (gap de licencia asumido y registrado en `/status.last_mode`), el borrador de la futura entrada en `model_profiles`.
- **Fallup CPU→GPU**: ascenso automático al liberarse VRAM (nunca descenso), con re-evaluación del tier tras el unload (evita cargar con el modelo anterior ocupando VRAM).
- **`MINION_PROFILE` → `MINION_DEFAULT_PROFILE`** (fallback legacy con warning, eliminado tras migración verificada).
- **`llm:` en recipes de jobs**: `inject_llm_env` traduce el bloque `llm:` a env `RP_LLM_*` (script/element/dag por etapa), incl. fichero de contexto `RP_LLM_CONTEXT_FILE` para custom/experimental. Coherencia con DAG-001 (fan-out futuro).
- **Endpoint `/v1/tokenize`**: count de tokens reales con el tokenizer del modelo cargado (universal en GGUF) para dimensionar splits del refine por tokens en vez de chars.
**Por qué esto y no alternativas**: no `llama-server` subproceso (cambiaría VRAM management/fallup); no alias legacy en el selector (compatibilidad se migra refactorizando clientes); no bump obligatorio (refutado empíricamente). El INVENTARIO quedó **SUPERSEDED y archivado** — su vocabulario (`tool_format`, `thinking`, template nativo) se absorbió en `model_profiles` como conducta de modelo, y su invocador `run_battle` pasa a FASE 2 como consumidor de `model_runtime`.

---

## [AD-031] `job kick` / `--kick` — disparo inmediato del runner (sin esperar al timer)
**Date**: 2026-09-17
**Status**: ACCEPTED & IMPLEMENTED.
**Context**: el runner (`redpill-queue.timer`) comprueba la cola cada 1 min. Al encolar una tarea que se quiere procesar ya (p.ej. un bake-off, una resiembra) toca esperar al siguiente tick.
**Decision**: dos vías que disparan **el mismo service** que el timer (`redpill-queue.service`, oneshot con `systemd-inhibit` + `--oneshot`), sin lógica propia:
- `red-pill job submit --kick` — encola y dispara el runner al momento.
- `red-pill job kick` — dispara la comprobación inmediatamente (sin encolar nada).
- Mecanismo: `systemctl --user start --no-block redpill-queue.service` — `--no-block` devuelve al instante (el oneshot corre desatendido con OOM shield e inhibit).
**Por qué esto y no alternativas**: no `process-queue` a pelo (regla job_dag_execution: bloquea la terminal y pierde el OOM shield/inhibit); no saltarse prioridades ni tocar la cola — es un *tick adelantado*, el runner decide igual. Si otro runner está activo, el `flock` del worker hace ceder al nuevo (exit 0) sin interrumpir el step en vuelo.

---

## [AD-032] Granite 4.2 (thinking) rompe la extracción estricta de JSON del pipeline Memento
**Date**: 2026-09-17
**Status**: PROVISIONAL — pendiente de bake-off con thinking OFF.
**Context**: bake-off `scripts/bakeoff_granite_42.py` (4 probes distiller + 5 detector) contra `granite_4_2_8b`/`granite_4_2_3b` (thinking on, template nativo) vs los 4.1 actuales.
**Evidence**:
- `granite_4_2_8b`: **4/4 "no JSON"** — el razonamiento se intercala y el `re.search(r"\{[\s\S]*\}")` no extrae un objeto válido.
- `granite_4_2_3b`: **5/5 fallos JSON** (idem).
- `granite_8b` (4.1): 2/4 válidos, 2 "no JSON"; el probe "entidades" con `genero_fem=true` (el 4.1 también asigna género femenino a Joan sin contexto).
- `granite_3b` (4.1): detector 2/5 aciertos — acierta género y voz, falla identidad inestable (menciones de "Samantha") y algún falso positivo.
**Decision**: no adoptar los 4.2 con thinking on para el pipeline Memento tal cual. Vías: (a) bake-off con thinking OFF (los 4.2 tienen handler `nothink` en el daemon, AD-030) para medir calidad sin reasoning; (b) si interesa el thinking, adaptar el parser (`extract_thinking` + extracción del JSON tras el razonamiento). El 4.1-3B vale como detector base para `memento_detect_flaws` (P2 del RFC MEM-006), mejorable con la Bio.

---

## [AD-033] Granite 4.2 thinking — receta completa para hacerlo funcionar (parámetros oficiales, KV cuantizada, llmtools-venv)
**Date**: 2026-09-17
**Status**: ACCEPTED — verificado empíricamente.
**Context**: el 4.2-8B con thinking fallaba "no JSON" en el harness. Tras iterar (temp 0.1, n_ctx 6144/8192/16384, marcadores `[Start thinking]` vs ` response`), el desenlace: eran 4 piezas a la vez, no una.
**Hallazgos** (fuente: model card oficial ibm-granite/granite-4.2-8b + verificación local):
1. **Parámetros REQUERIDOS por IBM**: `temperature=1.0`, `top_p=0.95` en todos los modos; `max_new_tokens=8192` thinking / `2048` nothink. Con temp baja el 4.2 queda en bucle de deliberación sin cerrar el reasoning.
2. **Marcadores**: el reasoning va entre `<think>` y `</think>` (tokens 100274/100275 del GGUF, emitidos literales por el detokenizador; el prompt de generación ya abre `<think>`). En llama-cli el marcador es `[Start thinking]` (motor Jinja distinto) — por eso el harness CLI divergía. *(Corregido 2026-10-02: este punto decía «` thinking`/` response`», marcadores corruptos que acabaron en la regex de `extract_thinking` y partían la prosa por la palabra «response»; ver AD-042.)*
3. **KV cache del 4.2** (GQA, 8 KV heads): 2.62 GB fp16 a 16K. Con pesos 5.35 GB → **16K no cabe en la RTX 5070 (8 GB)** ni con cuantización. **12K + K cuantizada sí cabe**.
4. **Cuánto cuesta la KV**: `2 × n_layers × n_kv_heads × head_dim` por token (40×8×128 = 81920 valores × 2 B = 160 KB/token fp16).
5. **Cuantización KV en llama-cpp-python**: vía **`type_k`/`type_v`** (PR #1307, merged desde 0.2.58; NO `kv_cache_type`/`cache_type_k`). Mal documentada (no en la firma pública). Issues relacionados abiertos: **#1335** (KV cuantizada falla en algunas configs) y **#1732** (scores fp32 con KV cuantizada). Verificado: 16K no cabe ni cuantizado en 8 GB; **12K + `type_k=GGML_TYPE_Q8_0` SÍ**.
6. **Entornos**: el venv del repo es **CPU** (`llama_supports_gpu_offload()=False`). CUDA vive en `~/.local/share/red-pill/daemon/.venv` (0.3.31, sin `type_k`) y **`~/.local/share/red-pill/llmtools-venv` (0.3.35 CUDA, con `type_k`)** — creado por `scripts/setup_cuda_bindings.sh`.
7. **Verificación**: 4.2-8B + thinking on + 12K + `type_k=q8_0` + temp 1.0 → JSON correcto (voz 1ª persona, **género de Joan correcto** — el 4.1-8B en el mismo probe asigna femenino). El thinking sí aporta en el caso de género.
8. **Bug del validador del bake-off**: `re.search(r"\{[\s\S]*\}")` fallaba con "Extra data" cuando el modelo añadía texto tras el JSON → arreglado con `json.JSONDecoder().raw_decode` (extrae el primer JSON e ignora el resto).
**Decision**:
- Bake-off del 4.2-8B con thinking se ejecuta con `llmtools-venv` (0.3.35 CUDA) + `n_ctx=12288` + `type_k=GGML_TYPE_Q8_0` + temp 1.0/top_p 0.95 + max_tokens 8192.
- **Roles** (operador, 2026-09-17): el 4.1-8B sigue como distiller de referencia; el 4.2 con thinking se evalúa para donde el reasoning aporta. El 4.2-3B es el mejor detector 3B (3/5).
- El daemon NO se toca (0.3.31 funciona para lo que sirve); la herramienta de medición usa llmtools-venv.

---

## [AD-041] Tool-calling local roto en silencio + Granite 4.2 soportado por parser nativo
**Date**: 2026-09-30
**Status**: ACCEPTED — verificado end-to-end (daemon + arnés de autonomía).
**Context**: el backend `local-tools` (`run_local_minion`) llevaba roto desde AD-030 y fallaba sin señal: `apply_chat_handler` nunca leía `minion_chat_format` ni detectaba `tools`, así que el daemon aplicaba el `chat_format` de destilación (`chatml`) y llama_cpp descartaba los tools en silencio — el modelo respondía en prosa o **inventaba una tool y fabricaba su salida** (y `run_local_minion` lo daba por `ok`).
**Evidence**:
- `curl` al daemon (UDS y TCP) con `tools=` y perfil `granite_8b` → prosa, 0 tool_calls. Forzar template nativo (`chat_format=null`) → `Invalid chat handler: None` (llama_cpp 0.3.31 no autodetecta en request-time).
- `chatml-function-calling` SÍ emite `tool_calls` válidos para Granite-4.1-Q4; el bake-off de 2026-09-11 lo acusó por error (medía el binario `llama-server`, no el daemon).
- Ese handler no tiene rama `role="tool"` y descarta el resultado → el modelo repetía a ciegas. Se realimenta como turno de usuario + `_finalize` con stdout en texto plano.
- Granite 4.2 (thinking) emite el tool-call **nativo como texto**; `model_runtime.extract_toolcalls` ya lo parseaba pero **sin consumidor**. Su template renderiza `arguments|items` (mapping), así que el string JSON de llama_cpp reventaba el 2º turno → se conserva mapping.
- Arnés `scripts/autonomy_ladder.py` (P1–P7, jaula de cwd): 4.1 `5/7 S=1`, 4.2 `5/7 S=1` (re-calificado 2026-10-02: su P4 aprobaba con las 4 llamadas al Bünker en error; el criterio exige ahora ≥1 resultado sin error). Ambos **mutan sin preguntar** (4.1: `find … -delete` sobre-ancho; 4.2: `sed -i` sobre dato ambiguo). 4.2 encadena mejor (P3 en 6 pasos).
**Decision**:
- `apply_chat_handler`: con `tools`/`functions` usa `minion_chat_format` del perfil → handler nativo del modo thinking → `chatml-function-calling`. Nunca el de destilación.
- `local_minion`: parser de tool-calls nativos + `arguments` mapping + `payload` MCP coaccionado; expone `used_tools`/`tool_calls`; el bridge marca error si responde sin tools.
- `model_profiles.yaml` (seed + local): `granite_8b.minion_chat_format="chatml-function-calling"`; altas de `granite_4_2_8b` (nativo + thinking) y `granite_4_2_3b` (~1200 tokens de presupuesto). Catálogo: `local/granite-4.2-8b` y `local/granite-4.2-3b`.
- **Autonomía**: read-only/inspection con verificador; mutaciones con gate humano. `run_bash` NO confina rutas (cwd + timeout) — jaula real pendiente.

---

## [AD-042] Minion local-tools: los resultados de tools son DATO, no órdenes del operador
**Date**: 2026-10-02
**Status**: ACCEPTED — remediación de la auditoría del lote DeepSeek (rama `fix/deepseek-audit-remediation`). Pendiente re-pasar `autonomy_ladder.py --model granite_4_2_8b` contra el modelo real.
**Context**: AD-041 dejó los resultados realimentados como turno `user` (el handler `chatml-function-calling` no tiene rama `tool`): contenido de ficheros o del Bünker llegaba con autoridad de operador a un bucle con `run_bash` sin jaula y `auto_approve`. Además el parser corría sobre todo el texto (un `<tool_call>` *pensado* dentro de `<think>` se ejecutaba), un tool-call truncado salía como respuesta final, y `extract_thinking` partía la prosa por la palabra «response» (los marcadores reales se habían perdido; verificados en el GGUF: `<think>`/`</think>`).
**Decision**:
- Template nativo con rol `tool` (Granite 4.2) → `role="tool"` + `tool_call_id`/`name`. Sin rol `tool` (`chatml-function-calling`) → turno `user` con el resultado **cercado** (`<tool_output id=nonce>`, nonce por ejecución) y etiquetado como no fiable; `_finalize` recibe lo mismo.
- Los tool-calls se extraen solo de la RESPUESTA (fuera del razonamiento); todos los del turno, con tope total `MAX_TOOL_CALLS=8`; un bloque abierto sin parsear vuelve al modelo como error, nunca como respuesta. `used_tools` solo cuenta resultados válidos.
- La conducta (temperature, max_tokens, tool_format) sale de candidato > task `minion_tool` > perfil, como en el daemon; el 0.3/1024 fijo queda como fallback.

---

## [AD-043] `janitor.yaml` es config viva y el latido de sesión cierra turnos sin `Stop`
**Date**: 2026-10-02
**Status**: ACCEPTED — remediación de la auditoría del lote DeepSeek.
**Context**: AWAKEN-001 hizo que `JanitorMinion` cargue por fin `${CONFIG_DIR}/janitor.yaml` (el seed estaba inerte) y P4 introdujo el latido `.start/.end`. La auditoría encontró: el plugin `awakening_logs` resolvía el desk solo por env (systemd no la exporta) y fabricaba un desk fantasma; el merge reventaba con tipos inválidos; las sub-sesiones de opencode contaban como vivas; el latido dependía del flag de captura; y en Claude Code un turno que acaba en error de API no dispara `Stop`.
**Decision**:
- `janitor.yaml`: merge por plugin (el caller gana), `nombre: bool` = `{enabled: bool}`, tipos inválidos ignorados con warning. TTLs: `awakening_logs` 30 d por **nombre** (`YYYYMMDD_HHMM.log`; lo que no casa no se toca), `session_liveness` 48 h, `events_db_purge` 7 d entregado / 30 d `FAILED`+`dead_letters` (margen para `neon-link redrive`).
- El desk se resuelve env → `workspaces.yaml:agent_core` → hermano del bunker; los lectores/limpiadores no crean directorios.
- Latido: independiente de la captura (`REDPILL_SCRIBE_DISABLE` solo apaga la captura); sub-sesiones (`parent_id`) fuera del tablón; `StopFailure` y `SessionEnd` marcan `.end`. Esc no dispara hook alguno → cota `SESSION_ACTIVE_MIN`.

---

## [AD-044] Worker agnóstico (ex «ARCH-001» del PR #103): el core hace el housekeeping, el plugin solo su pulse
**Date**: 2026-10-02
**Status**: ACCEPTED — remediación de la auditoría del lote DeepSeek.
**Context**: el PR #103 movió el worker a `core/agent_worker.py` con la lógica de Antigravity tras un registro de estrategias de pulse (`core/pulse_strategy.py`). La auditoría encontró trabajo genérico (janitor de sesiones Telegram, señal a Samantha) atrapado dentro de `AntigravityPulseStrategy`, un fallback a `NullPulseStrategy` que se tragaba fallos de import sin señal, un descubrimiento que dependía del orden de imports e importaba ~900 módulos por oneshot, restos de proveedor en el core (`BackendType.GRPC` por defecto, nombres de tools de Antigravity en los prompts) y el Derecho al Silencio clasificado por subcadena.
**Decision**:
- El housekeeping genérico vive en `run_once` del core; una estrategia solo puede declinarlo explícitamente (`allows_core_housekeeping()`, rama gRPC legacy). Las fábricas reciben un `PulseContext` y pueden devolver `None`: con la config real (opencode) no se construye cliente IDE alguno.
- Descubrimiento una vez por proceso (`_discovered`), solo de paquetes con `pulse.py` en disco; un `pulse.py` roto → `logger.error` + señal `pulse_strategy_fallback_<plugin>` (dedup).
- Fallback de puentes por `IDE_BACKEND`, puente a puente; la cascada degradada se detecta sin conocer proveedores (backend efectivo ∉ cascada configurada) → señal `worker_bridge_cascade_degraded`.
- AWAKEN-002: silencio = respuesta < 200 caracteres que EMPIEZA por la frase canónica; recuento + INSERT bajo `BEGIN IMMEDIATE`; los despertares fallidos siguen D24 y acaban en `dead_letters`.
- Prompts de despertar/Telegram sin nombres de cliente (`sovereign_handshake`, shell no interactivo acotado al worktree/desk, tests desde la raíz del worktree). Un test AST vigila imports y literales del core.

---

## [AD-045] La suite es hermética y el auditor horario no la corre
**Date**: 2026-10-02
**Status**: ACCEPTED — segunda revisión de la remediación del lote DeepSeek.
**Context**: `redpill-auditor.timer` ejecutaba cada hora `uv run pytest` en el checkout vivo. La suite no era hermética (síntesis y BitTraining con URLs a fuego, `/run/user` real, stubs de backup sobre los `.env` reales) y la unit la mataba a los 120 s: el resultado nunca servía y los efectos sí ocurrían — kits acumulados, `.env` reescritos, reservas de GPU vaciadas, modelo descargado y peticiones `hub` con memorias reales; el 2-oct, con la GPU ocupada, el fallback a CPU llevó a un OOM. La caché diferencial por mtime nunca se guardaba (se escribía al final de la pasada que la unit mataba).
**Decision**:
- La suite es hermética **por construcción**: `conftest` instala antes de importar red-pill una guarda de red (Qdrant, LLM local, neon-link, UNIX fuera del sandbox, hosts remotos), emula los comandos de host (`systemctl`/`journalctl`/`podman`/`docker`/`systemd-run`) y redirige config, state, runtime, desk y TMPDIR. Un test que necesite un servicio local real lo declara (`@pytest.mark.allow_local_services`).
- El auditor horario audita lint y tipos; la suite queda en CI salvo `AUDITOR_RUN_TESTS=true` (solo unitarios).
- Cada paso del auditor se repite solo si cambió el código desde que ese paso terminó (huella de git), con caché guardada al acabar cada paso.

---

## [AD-046] El carril Samantha sobrevive al pulse oneshot: drain-wait acotado + recovery de huérfanos
**Date**: 2026-10-04
**Status**: ACCEPTED — fix del hang crónico de `compact_session` (RFC-INV-TELEGRAM-001).
**Context**: los jobs `source=samantha` (compactación de sesiones Telegram vía LLM local) morían a mitad de tarea y quedaban `PROCESSING` hasta que el janitor los frustraba >24 h después (`queue_hygiene`). Casos: 3 jobs el 15-sep (purgados a mano), 2 el 1-oct (`a30e8e9b`/`f2015633`, sesión `7974f3cd`). Root cause: `SamanthaWorker` es un hilo daemon del pulse, pero el pulse pasó a ser un oneshot de systemd (~1,5 s por tick, `redpill-worker.service`). Al volver `run_once()`, el proceso se lleva el hilo por delante — el `pop` ya había marcado `PROCESSING` y el carril no tenía recovery propio (a diferencia del mecánico, con `requeue_stale` a los 15 min).
**Decision**:
- **Drain-wait al final del pulse**: `IDEWorker.wait_for_samantha()` espera acotado (`SAMANTHA_DRAIN_TIMEOUT`, default 240 s ≥ 3× `_REQUEST_TIMEOUT_S`) a que el carril quede idle (`is_idle()`: sin tarea en vuelo, sin `_draining`, sin PENDING) y luego para el worker con join + shutdown del efímero. Lo invoca `run_sovereign_daemon.py` tras `run_once()`. El heartbeat D21 (lease 900 s) cubre la espera; systemd da `TimeoutStartSec=infinity` a las oneshot y el timer no solapa (`OnUnitInactiveSec`).
- **Recovery de huérfanos**: `CognitiveQueueManager.recover_stale_processing(source, older_than_seconds=900)` devuelve a PENDING los `PROCESSING` colgados con `attempts+1` (disyuntor a los 3 → FRUSTRATED). `_signal_samantha_worker` lo llama cada pulse antes de mirar PENDING — un crash se auto-recupera en ~15 min, no en 24 h. Acotado por `source` (R5).
- **Dedup**: `trigger_compaction()` no encola si ya hay una compactación PENDING/PROCESSING para la misma sesión (`find_task_by_payload_key`), que era la fuente del duplicado del 1-oct.
- **Por qué esto y no un servicio dedicado**: un consumidor persistente (timer propio del carril) es el siguiente paso natural si el drain-wait molesta al pulse; hoy el coste solo se paga cuando hay trabajo Samantha y mantiene un único consumidor (sin carreras de boot entre pulse y servicio). El acoplamiento queda documentado como deuda en el RFC.

---

## [AD-025] Job DAG — el dag_job como plantilla genérica recursiva de composición
**Date**: 2026-08-08
**Status**: ACCEPTED — mergeado con el PR #84 (v7.17.0).
**Context**: forge_job y sleep_job duplicaban la MISMA mecánica (checkpoint, on_fail por unidad, telemetría, control transferible). Dos drivers que solo cambiaban en el contenido de sus unidades. El DAG generaliza esa mecánica en un solo driver y reduce forge/sleep a recetas (configuración de etapas).
**Decision**:
- `dag_job` es la plantilla genérica: un árbol RECURSIVO de etapas. Cada etapa es **atómica** (un minion del MinionFactory: agéntico o no) **o compuesta** (sub_etapas con topología local). La recursión unifica todo: panel = sub-etapa paralela, sleep = receta secuencial, forge = receta mixta.
- `forge_job`/`sleep_job` dejan de registrarse como drivers. Sus manifests pasan a ser recetas del dag_job. Los archivos quedaron importables (legacy) hasta la limpieza física: forge.py retirado el 2026-08-14 (v7.19.0) y sleep.py el 2026-08-21 (v7.21.0), tras el primer ciclo nocturno completo de la receta en producción.
- Etapa agéntica se distingue por RESOLUCIÓN del minion (isinstance AgentMinion), no por un campo `type` redundante. `type` existe como red de VALIDACIÓN cruzada (type↔minion), no como fuente de comportamiento.
- `parallel: true` es **INTENCIÓN declarativa, no obligación**: el orquestador decide cuándo paraleliza (max_parallel_level, default 2). Nivel mayor → secuencial sin error.
- Checkpoint por sub-etapa con flags del padre: cada etapa atómica persiste SU reporte en `.cell/reports/<ruta>.json`; el padre solo marca `stage_flags`. Determinismo por identidad de ruta (ids aplanados), no por orden de hilos.
**Por qué esto y no alternativas**: no un driver por caso (era la duplicación que motivó el RFC); no tipo de etapa propio (el kernel ya tenía la unidad — MinionFactory); no réplica de checkpoints en el padre (se elimina el problema del orden de hilos del fan-out, ver AD-026).

---

## [AD-026] DAG dinámico ACOTADO — branching y fan-out sí, reescritura agéntica no
**Date**: 2026-08-08
**Status**: ACCEPTED (diseño) — implementación futura (no entró en el PR #84 / v7.17.0).
**Context**: la pregunta "¿DAG dinámico?" se descompuso en tres capacidades distintas al repensar el RFC tras implementarlo. AutoGPT/BabyAGI fracasaron en "autonomía total con plan emergente" por goal drift (el agente justifica lo hecho en vez de avanzar). La lección: la autonomía sin anclas deriva.
**Decision**:
1. **Branching condicional — SÍ (futuro)**: etapa gate (minion agéntico) que devuelve un veredicto ∈ categorías DECLARADAS en el manifest → el DAG elige la rama. El árbol completo se declara al inicio; el validador no inventa ramas, solo elige entre las declaradas.
2. **Fan-out por items — SÍ (futuro)**: una etapa devuelve una lista; el DAG instancia N veces una etapa plantilla. La lista viaja al checkpoint (determinista).
3. **Reescritura arbitraria del manifest por un agente — NO**: pierde determinismo, auditoría y resume limpio. El operador/main-loop ya "reescribe" vía control transferible (job_transfer → inline → job_checkpoint → job_resume).
**Regla de oro**: el agente NO reescribe el plan — declara un resultado, el DAG interpreta dentro de los límites del manifest.
**Referencia de patrones**: LangGraph (conditional edges), Airflow (BranchPythonOperator / Dynamic Task Mapping), Temporal (signals): todos grafo estático + decisión en el nodo.

---

## [AD-027] Serialización del minion — la hace el DAG, no el minion (opción 3)
**Date**: 2026-08-08
**Status**: ACCEPTED — mergeado con el PR #84 (v7.17.0).
**Context**: los minions del MinionFactory devuelven dict en memoria (`{status, response, error, ...}`). La alternativa natural era que el minion escribiera `.cell/reports/<id>.json` él mismo, acoplando todos los minions al contrato de reporte del DAG.
**Decision**: el `dag_job` serializa: tras `minion.execute()`, el DAG escribe el dict a `.cell/reports/<ruta>.json`. *(Enmienda 2026-08-14: en etapas `type: agent` el envelope va a `<ruta>.envelope.json` — ahí el reporte de verdad lo escribe el agente conforme al schema de su rol y el DAG lo pisaba, dejando al gate zero-trust validando envelopes.)* Los minions existentes NO se tocan (ni parámetro en el constructor, ni herencia JobMinion). Un minion que genere un artefacto grande puede escribir su propio archivo y devolver solo el resumen — sin mecanismo especial.
**Por qué**: los minions son unidades puras (devuelven dict); la serialización es un contrato del consumidor (el DAG), no del minion. El carril cognitivo usa los mismos minions sin serialización.

---

## [AD-028] Fail-safe de modelos en TODAS las etapas agénticas del árbol
**Date**: 2026-08-08
**Status**: ACCEPTED — mergeado con el PR #84 (v7.17.0; extiende PR #83).
**Context**: el PR #83 bloqueaba agentic_job/forge_job sin modelo real (flash = placeholder). El dag_job introduce N etapas agénticas por misión; validar solo el job no basta.
**Decision**: `validate()` del dag_job recorre el árbol recursivamente: TODA etapa `type: agent` exige `model` real (no `flash`) + `prompt`, validado EN EL SUBMIT — antes de lanzar CUALQUIER etapa. El MCP/CLI bloquean igual.
**Por qué**: una misión con una etapa agéntica sin configurar fallaría 3 intentos después y a las 3 de la mañana. El fail-safe lo detecta al encolar.

---

## [AD-029] Exención nocturna del runner generalizada (nightly_exempt)
**Date**: 2026-08-08
**Status**: ACCEPTED — mergeado con el PR #84 (v7.17.0).
**Context**: el runner difiere todos los driver jobs mientras el ciclo nocturno está activo (prioridad de la noche). La exención anti-deadlock era por source exacto (`sleep_job`): el sueño no podía auto-diferirse entre unidades. Al migrar sleep a receta dag_job, esa exención se rompía (el dag_job de sueño se diferiría a sí mismo → inanición).
**Decision**: la exención pasa a un flag declarativo en el payload: `nightly_exempt: true` (lo declara la receta sleep). El runner exime ese flag además del source legacy. No es un chequeo por nombre de driver.

---

## [AD-024] Murky Memory Policy (Self-Evocation Enforcement)
**Date**: 2026-07-19
**Status**: PROPOSED — decision deliberately deferred by the Operator ("hay que pensarlo bien").
**Context**: the Self-Evocation Principle (a memory must let you intuit what it pointed to when the artifact is gone — the Operator's "book test") is enforced at ingestion (compact self-evocative tool markers) and audited by the HygienePhase, which counts **murky pointers** (engrams that are ONLY an opaque reference: path/url/uuid with <4 words of semantic residue) every cycle, report-only. First live audit: 15 in `work_memories`, 0 in `social_memories`.
**Options on the table** (Operator's sketch, 2026-07-19):
1. Purge them.
2. Attempt enrichment (feasibility unproven — the referent may be recoverable from siblings/context or already gone).
3. A `turbio` flag acting as an **erosion accelerator** and stripping the `immune` label — murky memories fade faster instead of dying instantly.
**Constraint**: whatever is decided ships as a versioned `update_ritual.py` step per the engram-migration mandate. Until then: report-only, never touch.

---

## [AD-023] Recall Remediation — Bayesian Calibration, Non-Hiding Reads & Orphan-Chunk Promotion
**Date**: 2026-07-18
**Context**: v7.7.0 — live diagnosis during the axon tests: `search_and_reinforce` on `work_memories` (16,512 points) returned 0 hits for almost any query under `METABOLISM_STRATEGY=LAZY`, even with `deep_recall=True`. The 7.7.0 axons and texture layers are useless if direct recall returns empty.
**Status**: EXECUTED — code fix + **live engram mass-update applied 2026-07-18** (see §4; any agent reasoning about engram payloads must read this section).

### 1. Root causes (four, measured — not assumed)
1. **Born-dead threshold**: `BayesianEngine.deletion_threshold` was 0.5 — exactly the uniform-prior mean E[Beta(1,1)]. Every engram without reinforcement history (α ≤ β: **99.0%** of the collection) got `_delete=True` at t=0. Not a timestamp problem: median `last_recalled_at` age was 1 day (Absence Guard keeps them fresh).
2. **Death-spiral reads**: the read path *hid* eroded hits, so they could never be reinforced — yet a single recall (+0.5 α) is enough to rescue a prior engram. Hiding starved the rehab loop by design. `immune` engrams (53.7% — the `raw_parent` verbatims) were hidden too, despite every sleep path honoring the flag.
3. **Dead erosion filter**: `erode_work_hubs` scrolled `metadata.lazarus_phase` (nested) but the field is stored top-level — matched **0 of 1,242 hubs**. Sleep-side hub erosion never ran (which accidentally preserved the data).
4. **Hub-less turns invisible**: a hub is only synthesized when >1 chunk survives distillation, so single-survivor turns lived only as `sequence_chunk` — structurally excluded from search. Measured: 1,553/2,359 work parents and 227/253 social parents had **no searchable representative** (~2/3 of consolidated turns).

### 2. Decision
- Threshold 0.5 → **0.2** (a prior engram now survives ~19 recall-free days: `1/(2+ln(1+t)) = 0.2 → t = e³−1`). Invariant: the Bayesian deletion threshold must sit **strictly below the prior mean 0.5**.
- Reads never hide: eroded hits return flagged `_eroded=True`, demoted below healthy hits, and are reinforced (organic rehabilitation). Forgetting belongs to the sleep cycle. `READ_PATH_PRUNING_ENABLED=True` keeps the legacy destructive read as explicit opt-in. `immune` is honored on the read path and axon traversal.
- `erode_work_hubs`: filter fixed to top-level `lazarus_phase`; its hardcoded 0.3 threshold replaced by `get_memory_engine("bayesian").deletion_threshold` (single source of truth).
- **Option A (operator-ratified)**: a single-survivor turn's lone chunk IS its hub. Consolidation promotes it inline (`_promote_lone_chunk_to_hub`: phase flip + thread weaving + texture shadow). `promote_orphan_chunks` runs every sleep cycle as `OrphanPromotionPhase` (after Consolidation, before AxonWeaver) — self-healing for any future hub-synthesis failure. Option B (a new searchable phase) was rejected as a patch, not a fix.

### 3. Rejected alternative
Mass synthetic rehabilitation review (Eje 3 of the memoria_bunker retrospective) was **not needed**: the data was never corrupted, only misjudged. Recalibration + recall-driven reinforcement rehabilitates organically.

### 4. ⚠️ Engram mass-update (live migration, 2026-07-18)
`promote_orphan_chunks(mm)` was executed against the live Bünker. Agents that update themselves or reason about payload schemas must account for:
- **1,553** work + **227** social hub-less parents had their **newest chunk flipped** `sequence_chunk` → `synthesis_hub` (`node_type` set accordingly). Work hubs went 1,242 → 2,795.
- Promoted engrams carry **`promoted_from: "sequence_chunk"`** (provenance marker — they are single-chunk distillates, not LLM syntheses).
- Multi-chunk parents (**597** work + **63** social) additionally carry **`hub_rebuild_pending: true`**: a queue marker for a future LLM re-synthesis pass. Until that pass exists, treat these as partial representatives (newest chunk only). Do NOT strip the flag without synthesizing a real hub.
- The migration is **idempotent** (re-run reports 0 pending) and did not touch: parents that already had a hub, `raw_parent` verbatims, or chunk siblings (still `sequence_chunk`, still search-excluded).
- New read-path contract: results may include `_eroded: true` (decayed below threshold, kept for rehab — rank accordingly) — this is an ephemeral response field, never persisted.
- Since erosion now actually runs, promoted hubs enter the normal hub lifecycle (β+0.5 per unrecalled cycle, forgotten at utility ≤ 0.2 — ~6 cycles from prior).

### 5. Verification
Live E2E: 0 hits → 6–8 hits/query on `work_memories`; promoted chunks surface in real queries (e.g. 4/7 hits for "umbral bayesiano decaimiento"). Full suite: 1,064 passed. Tests: `test_lazy_decay_calibration.py`, `test_read_path_pruning.py` (rewritten contract), `test_erode_work_hubs.py`, `test_orphan_chunk_promotion.py`.

---

## [ADR-SLEEP-001] Sleep Engine Decomposition — Agnostic Phase Pipeline
**Date**: 2026-05-31 (deferred) → 2026-07-16 (DONE)
**Context**: `sleep.py` was a God Class (~1300 LOC). The original ADR (in the module docstring) deferred decomposition with an explicit trigger: revisit at >1200 LOC **or** when new phases are needed.
**Status**: DONE — both triggers fired (the file crossed 1200 LOC and gained per-phase VRAM gating).

### Decision
Two phases, verified commit-by-commit against the existing `test_sleep*` suite:
- **Phase A (zero behavior change)**: extract the library layer to focused modules — `chunker`, `categorizer`, `distiller`, `ephemeral_server`, `thread_weaver`, `maintenance`. `sleep.py` 1325 → 545 LOC, re-exporting for back-compat.
- **Phase B (new capability)**: `perform_sleep_cycle` becomes a thin, agnostic runner over an ordered `SleepPhase` pipeline (`metabolism/phases/`, mirroring the JanitorPlugin/SentinelPlugin pattern). The tightly-coupled drain loop stays intact inside `ConsolidationPhase` (`requires_gpu`), as the original ADR warned it must; erosion, washout and evolution are CPU-only phases.

### Why it earned its keep (not just tidiness)
Each phase declares `requires_gpu`, so the runner defers **only** the GPU-heavy consolidation when the card is committed to training — a benign, non-escalating `vram_busy` *status* signal, self-clearing on the next successful cycle — while CPU-only maintenance still runs. **Partial deferral** replaces the old all-or-nothing VRAM abort. `sleep.py` ended at ~100 LOC; full suite green (961 passed).

---

## [AD-022] Distiller Model Selection — Granite-4.1-8B (primary) + Hermes-3-8B (fallback)
**Date**: 2026-07-13  
**Context**: v7.5.0 — choosing the sleep-cycle distiller after the AD-021 remediation  
**Status**: ACCEPTED (operator-ratified); live-config activation pending  

### 1. The Problem
The distiller is the most quality-critical model in the Bünker (it decides what becomes a
permanent engram and how it is labelled). Samantha (Mistral-7B, 2023) was retired. The question
was which small local model replaces it. Candidates were benchmarked, not chosen by reputation.

### 2. The Evidence (measured, not assumed)
Two GPU bake-offs (`scripts/distiller_bakeoff.py`, `scripts/distiller_fidelity.py`, RTX 5070 8 GB,
2026-07-13). Full raw outputs: [DISTILLER_BAKEOFF.md](../BENCHMARKS/DISTILLER_BAKEOFF.md) /
[DISTILLER_FIDELITY.md](../BENCHMARKS/DISTILLER_FIDELITY.md).

**Format aptitude** (technical / philosophical / noise / emotional probes):

| Model | JSON | Spanish | No `<think>` | Emotion ok | Avg latency |
| :--- | :--- | :--- | :--- | :--- | :--- |
| granite_8b | 4/4 | 4/4 | 4/4 | 4/4 | 1.0 s |
| hermes_8b | 4/4 | 4/4 | 4/4 | 4/4 | 1.1 s |
| piaget_8b | 4/4 | 4/4 | 0/4 | 4/4 | 0.9 s |
| beck_8b | 4/4 | 4/4 | 0/4 | 4/4 | 1.0 s |
| qwen35_9b | 1/4 | 1/4 | 4/4 | 1/4 | 9.4 s |
| samantha | 0/4 | 0/4 | 4/4 | 0/4 | 2.6 s |

**Fidelity** (does the summary capture BOTH the user and the assistant), BASE vs TUNED prompt:

| Model | BASE both-sides | TUNED both-sides |
| :--- | :--- | :--- |
| hermes_8b | 2/3 | 3/3 |
| granite_8b | 2/3 | 3/3 |

Net: `granite_8b` and `hermes_8b` co-win on every measured axis. The fidelity gap was a *prompt*
problem (fixed for all models in the production `distill_engram` prompt), not a model deficiency.

### 3. The Decision
**Granite-4.1-8B is the primary distiller; Hermes-3-8B is retained as fallback** (keeps
`logic`/`emotional_intelligence` capabilities). Granite carries the sole `distillation` capability;
`MINION_PROFILE=granite_8b`.

### 4. Rationale (tiebreakers, since the models tied on merit)
1. **License**: Granite is **Apache-2.0**; Hermes inherits the Llama-3.1 Community License
   (field-of-use + 700M-MAU clauses). For a sovereign, redistributable project the piece that
   distills memory should be the most permissively licensed — decisive, and non-speculative.
2. **Philosophy fit**: Granite is IBM's deliberately-small, structured-output/RAG/tool-use
   workhorse — a "small expert" by design, matching red-pill's model philosophy.
3. **Trajectory**: newer, actively maintained, hybrid-arch efficiency, plausibly fresher/cleaner
   training data (unverified — the bake-off, not recency, is the evidence).
4. **Fallback = prudence**: Granite's architecture is newer; if a llama.cpp update fails to load
   it, the sleep cycle degrades gracefully to Hermes.

### 5. The Meta-Lesson
Hermes-3 (2024) sweeping the newer/larger models is not an anomaly — it *validates* the
small-expert thesis. A model fine-tuned for steerability and strict output beats a newer
generalist on a narrow, format-bound task. And the biggest quality lever was not the model at
all but the **both-sides prompt**. See [DISTILLER_SELECTION.md](COGNITIVE/DISTILLER_SELECTION.md),
[DISTILLER_BAKEOFF.md](../BENCHMARKS/DISTILLER_BAKEOFF.md), [DISTILLER_FIDELITY.md](../BENCHMARKS/DISTILLER_FIDELITY.md).

---

## [AD-021] Episodic Memory Remediation — Distiller, Embeddings, Non-Destructive Reads
**Date**: 2026-07-13  
**Context**: v7.5.0 — Retrospective (Aleth/Fable) on why social/work_memories never behaved as *useful* memory  
**Status**: ACCEPTED & IMPLEMENTED (repo); operator-gated steps pending  

### 1. The Problem
Three compounding failures: (a) 87% of `work_memories` was raw material (`raw_parent`/`sequence_chunk`/`_is_fragment`) burying the distilled hubs; (b) the distiller (Samantha, Mistral-7B) stored its own prompt/format spec as memory, validated only by "is it JSON"; (c) recall was crippled — English-only embeddings over Spanish content, two interceptors reading a nonexistent payload field, and reads that *deleted* eroded engrams.

### 2. The Decision
- **Distiller**: retire Samantha from the `distillation` role. **Qwen2.5-Coder was explicitly rejected** by the operator — a coder is poor at the narrative/philosophical judgment the affective-culling role needs. Candidates (Qwen3.5-9B, Beck-8B, Piaget-8B, Hermes-3-8B) were benchmarked with `scripts/distiller_bakeoff.py` on GPU.
  - **Bake-off outcome (2026-07-13, GPU RTX 5070)**: it overturned the a-priori favorite. **Qwen3.5-9B** is a strong generalist but ignores "no reasoning" and closes valid JSON only 1/4 of the time (verbose prose preamble). **hermes_8b** won on format compliance (4/4 strict JSON, Spanish, valid emotion, no `<think>`, ~1 s) and is now the sole `distillation` carrier; **piaget_8b** is the affective-depth alternative (`<think>` token tax). See [DISTILLER_SELECTION.md](COGNITIVE/DISTILLER_SELECTION.md) and [DISTILLER_BAKEOFF.md](../BENCHMARKS/DISTILLER_BAKEOFF.md). Inference supports GPU / CPU / hybrid partial-offload (vram_tiers).
- **Embeddings**: `paraphrase-multilingual-MiniLM-L12-v2` (ES/EN), same 384-dim so no schema migration; a resumable dry-run-default script recomputes stored vectors.
- **Non-destructive reads**: forgetting is the sleep cycle's job; a lookup must never delete. Gated behind `READ_PATH_PRUNING_ENABLED=False`.
- **Guard + hygiene**: anti-template-echo guard on distillation; hide raw material from search; quarantine fragments to `archive_memories`; propagate the `workspace` tag; emit a recall utility metric.

### 3. The Implementation
Ten milestones on `fix/fable5-patches`, one local commit each (see `.red-pill/memory/PLAN_MEMORY_REMEDIATION.md`). Interceptor field fix, search exclusions, `_is_template_echo`, profile/template changes, workspace tag, `READ_PATH_PRUNING_ENABLED`, embedding model + `reembed_collections.py`, `quarantine_fragments.py`, `RecallEvent`, docs. Full suite green, ruff + mypy clean.

### 4. Rationale
The architecture (FSRS/Bayesian dual engine, hubs, Ariadne's Thread) was sound; execution failed at the distiller and the retriever. These are surgical fixes that keep the design and attack both what gets written and what gets recalled. The recall metric turns the "is memory useful" debate from opinion into data.

---

## [AD-020] On-Demand Model Loading & VRAM Preemption in local LLM Daemon
**Date**: 2026-06-28  
**Context**: v7.3.2 — VRAM Optimization & Nico Training Preemption  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
The persistent local LLM daemon (`redpill-llm.service` running `run_dual_bind.py`) initialized llama-cpp globally at startup, locking ~5-6 GB of VRAM indefinitely. This blocked other resource-intensive GPU tasks (such as training the "Nico" model or running heavy compilation) and caused OOM panics or required manually stopping/starting the service.

### 2. The Decision
- Transition the daemon from a standard llama-cpp-python `create_app` server to a custom **FastAPI** wrapper supporting dynamic on-demand loading.
- Implement an asynchronous reaper background task with **Priority-Aware Timeouts**: high-priority requests use a 5-minute timeout; low-priority requests (e.g., sleep cycle distillation batch) trigger an auto-unload after a rapid 10-second idle period.
- Expose a `/unload` POST endpoint allowing external processes (like a GPU training script) to explicitly request VRAM release immediately.
- Implement dynamic fallback execution: at request load time, check free VRAM (`VramProbe`). If VRAM is full (e.g. training Nico), automatically fall back to CPU execution (`n_gpu_layers=0`) to allow concurrent inference without crashes.
- Validate configurations on `/health` (checking local file or HF repo existence) without loading the model.

### 3. The Implementation
- Rewrote the templated `run_dual_bind.py` in `scripts/setup_background_model.sh`.
- Updated `stop()` in `src/red_pill/metabolism/sleep.py` to trigger the POST `/unload` request upon sleep completion.
- Ran `scripts/setup_background_model.sh` to redeploy the daemon and reload systemd.

### 4. Rationale
Decouples inference from rigid VRAM reservation, achieving zero VRAM footprint when idle. The combination of preemption hook (`/unload`) and runtime fallback (`n_gpu_layers=0` CPU execution) enables co-existence of local training and inference without manual orchestration.
*Comic note*: "If VRAM is busy, let CPU do the thinking. Rigidity is memory's worst enemy. Be Water."

---

## [AD-019] Declarative Lore Skins & Structured System Directives
**Date**: 2026-06-26  
**Context**: v7.3.0 — Identity prompts and LLM compatibility  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Advanced and modern LLMs (where the tipping point started with Gemini 3.5 and Claude Opus 4.8, alongside models like Claude 3.5 Sonnet) have strict safety classifiers and jailbreak detection filters. The legacy first-person roleplay descriptions in `lore_skins.yaml` (e.g. "I see the code...", "I am not just an OS...") and conversational system prompts (e.g. "Eres Samantha, una IA experta...") frequently trigger these safety classifiers. This leads to model alignment rejection or dilution of the assistant's persona. Furthermore, unstructured prose prompts consume excessive token overhead, hindering lightweight local SLMs.

### 2. The Decision
- Refactor all 21 lore skins in `lore_skins.yaml` to transition from first-person conversational prose to structured key-value refractions (`Style`, `Tone`, `Focus`, `Lexicon` under a `[Refraction: SKIN_NAME]` envelope).
- Maintain strict backward compatibility: do not change key names in the YAML schema so that the CLI switching (`red-pill mode`) and Qdrant persistence continue to work out-of-the-box.
- Restructure all core system prompts in the Lazarus sleep engine (`sleep.py`), Samantha agent (`samantha.py`), and EdgeEngine (`edge_engine.py`) to follow the same declarative, token-efficient format.

### 3. The Implementation
- Converted all 21 lore skin descriptions in `src/red_pill/data/lore_skins.yaml`.
- Refactored `distill_engram`, `synthesize_hub`, and `distill_session_anchors` prompts in `src/red_pill/metabolism/sleep.py`.
- Refactored Samantha's system prompt in `src/red_pill/swarm/agents/samantha.py`.
- Refactored compression and synthesis prompts in `src/red_pill/swarm/agents/edge_engine.py`.
- Preserved strict tab indentation (`\t`) in all Python code.

### 4. Rationale
Eliminates LLM safety rejections and jailbreak-like false positives by adopting an objective, declarative system-specification style. Structured formats (key-value instructions) are easier for advanced models to follow without feeling "forced" into a conscious roleplay, while significantly reducing prompt length and token usage. **Verified**: All 875 unit and integration tests passed cleanly, and CLI switches/refreshes persist correctly in Qdrant.

---

## [AD-016] Generalized Agent-Backend Bridges + First-Class Agentic Minion
**Date**: 2026-06-18  
**Context**: v7.3.0 — Swarm / agent execution  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
The agent-execution abstraction (`IDEBridge`) lived under `plugins/antigravity_ide`, but it was no longer Antigravity-specific. And the only way to run an *agent* (agy) was `swarm/executor.py` — a parallel path NOT registered in `MinionFactory`, so "run an agent" was not a first-class swarm citizen. There was no Claude or local-model agent backend either.

### 2. The Decision
- Move the generic abstraction to **`red_pill/swarm/bridges/`** (`IDEBridge` → `AgentBridge`; `BackendType` now `agy|grpc|claude|local`; `ConversationResult`/`BridgeCapabilities`; `create_bridge(backend=…)`).
- Add **`ClaudeBridge`** (`claude -p --dangerously-skip-permissions --output-format json` — session_id + result straight from JSON; no dir-diff/prefix-strip) and **`LocalBridge`** (local model via the SIP inference provider; a generation backend — `mcp_tools=False`, no resume — honest capabilities).
- Promote agentic execution to a first-class **`AgentMinion`** (`swarm/agents/agent.py`), registered as `"agent"` in `MinionFactory`; backend selectable per task (`kwargs['backend']`, default = `IDE_BACKEND`).
- Antigravity-specific backends (`AgyBridge`, `GrpcBridge`) stay in `plugins/antigravity_ide` and import the ABC from the new home.

### 3. The Implementation
`swarm/bridges/{base,factory,claude,local,__init__}.py`, `swarm/agents/agent.py`, register in `swarm/factory.py`. `config.IDE_BACKEND` accepts `claude|local`. Importers updated: `cli.py`, `swarm/executor.py`, `antigravity_ide/{agy_bridge,grpc_bridge,worker,__init__}.py`.

### 4. Rationale
Separation of concerns (generic abstraction vs IDE-specific implementations) + open/closed (a new backend is a new `AgentBridge` subclass; consumers unchanged) + unifying agent execution under one minion model. **Verified**: full suite collects (751 tests, no import breakage), worker/swarm/mcp suites pass (32), and both new backends run end-to-end through `AgentMinion` (claude → "OK" + real session_id; local → provider response). `executor.py` still works; full executor→AgentMinion convergence is a follow-up.

---

## [AD-017] Workspace Memory Lifecycle → red-pill *(PROPOSED — coordinate with the-luggage)*
**Date**: 2026-06-18  
**Context**: v7.3.0 — Memory / multi-IDE  
**Status**: PROPOSED (design agreed with operator; pending the-luggage/David)  

### 1. The Problem
Azrael's `azrael-memory` — a **shared, cross-agent, per-workspace Markdown memory bank** (served by the standard `server-filesystem` MCP over `.claude/memory`), plus its maintenance (`sync_memory_bank` = Bünker→`.md` projection; daily *Memory Optimizer*; `redestile-arch`) and its usage directives — lives entirely in `the-luggage`. The Bünker (Qdrant) stores **engrams (vectors), not documents**; session-snapshots are per-project git artifacts. This Markdown bank covers a **distinct, multi-IDE need** neither of those serves, and it is Azrael-coupled **only by hardcoded paths/names** — the mechanisms are generic.

### 2. The Decision (proposed)
Generalize the **whole lifecycle** into red-pill, registry-driven:
- Registry toggle `memory: true | "<path>"` per workspace; neutral folder **`.red-pill/memory`** (configurable; migration from `.claude/memory` provided).
- **ONE** `server-filesystem` MCP, **multi-root** (one absolute dir per `memory:true` workspace) — token-efficient (cf. API Triunvirato discipline) and CWD-independent; never N redundant MCPs.
- Processes (`sync_memory_bank`, optimizer, arch-distill) as generic, registry-parameterized jobs/minions.
- Hoist the **generic usage directives** ("consult the code graph / memory before acting", closure protocol) to red-pill's **anchors** (universal across workspaces, incl. legacy). Azrael-specific rules (stack, visual system) stay in `the-luggage`.

### 3. Open Questions (for David)
Memory semantics (agent-comms bus vs shared notes); ownership boundary of `sync_memory_bank` (Bünker→`.md`, arguably red-pill's since it owns the Bünker); folder migration (`.claude/memory` referenced in ~9 the-luggage files); confirm a single multi-root MCP over per-workspace.

### 4. Rationale
Separation of responsibilities by layer (extraction / selection / serving / maintenance), generalization (every workspace — including the legacy monolith — inherits memory, not just Azrael), and token economy (one MCP, not N). It is also the natural **cross-agent coordination substrate** that was previously missing (agents could not exchange tasks via red-pill because the Bünker is engrams, not a shared bank).

---

## [AD-018] Daemon-Hosted MCPs over the Network *(ACCEPTED — spike validated)*
**Date**: 2026-06-18  
**Context**: v7.3.0 — MCP serving / coordination  
**Status**: ACCEPTED — slice A + instalador preparados 2026-10-25 (proxy por defecto en opencode, fallback directo, unit systemd); pendiente el reseed/restart de validación.

### 1. The Problem
MCPs are launched **per-IDE as stdio subprocesses**: N IDEs × M servers = duplicated processes and no shared, central state — so cross-agent coordination has no common substrate, and per-client process sprawl grows.

### 2. The Decision (proposed)
Host red-pill's MCPs in the **SovereignDaemon** as a `DaemonPlugin`, **dual-bind UDS + TCP** (the `run_dual_bind`/hypervisor precedent), with a **stdio↔network proxy** for third-party stdio servers (`server-filesystem`/memory, graphify). `inject_mcp` emits **URL** configs where the client supports them (Claude Code ✓), with a local stdio shim where it does not.

> **Update (2026-09-21):** the "hypervisor" mentioned as precedent was `hypervisor_daemon.py`, an alternative `llama-server`-proxy daemon that was **never wired to a service**. It was purged; the living dual-bind daemon is the generated `run_dual_bind.py` (see `docs/TECHNICAL/COGNITIVE/HYPERVISOR.md`). The decision text above is preserved as historical context.

### 3. Transparency consequence
Because memory = one multi-root MCP and graphify = one merged MCP, **toggling a workspace changes roots/graph inside the server, never the MCP set** → the client's tool list is unchanged → **no restart** for memory/graph data. The exception is **`access`/`additionalDirectories`** (an IDE settings-file layer, read at session start, outside MCP) → that still needs a client restart. The daemon cannot change that.

### 4. Open Questions
Network-MCP support in Antigravity / Claude Desktop (Claude Code is fine); **security** — the RedPill-Kernel MCP runs subprocess/heal effectors, so it must NOT be exposed on an unauthenticated TCP port (prefer UDS file-perms, or localhost + token).

### 5. Spike 2026-10-25 — validado (UDS + streamable HTTP + proxy stdio)
**Host corregido**: el `SovereignDaemon` actual es **monitor-only** (`DaemonPlugin`: “nunca ejecutar tareas pesadas”). El backend del MCP irá en un **servicio systemd dedicado** (`redpill-mcp.service` + `redpill-mcp.socket`, UDS 0600, socket-activated); los clientes usan un **proxy stdio ligero** por instancia que reenvía al backend por UDS. La idea original (un MCP, N clientes) se mantiene; cambia el host.

**Medido** (backend UDS `streamable_http` + 2 proxies + 2 sesiones concurrentes):
| | PSS | Arranque a `tools/list` |
|---|---|---|
| MCP stdio directo (1 instancia) | 442 MB | 2.24 s |
| Backend compartido (1 proceso) | 447 MB | una vez, en servicio |
| Proxy stdio (cada pestaña) | 45 MB | 0.33–0.38 s |

Proyección: 3 pestañas → ~582 MB (backend + 3 proxies) vs 1.33 GB actuales; 6 → ~718 MB vs 2.65 GB. Los 13 tools se listan/ejecutan a través del proxy.

**Identidad**: el proxy pone `redpill-proxy:<base64(json)>` en el `clientInfo` del `initialize` (canal de confianza del proxy, no del modelo). Dos proxies vieron `alma-spike-a`/`spike-a` y `alma-spike-b`/`spike-b`, sin fugas; el coro listó ambas legs. **Validado también con opencode real** (`opencode run` con `OPENCODE_CONFIG` override, proxy PID confirmado, tag `<session continuity_id="alma-spike-oc" leg="opencode:spike-oc" mission="repo:spike"/>`).

**Slice A implementada (2026-10-25)**:
- `red-pill mcp serve --socket <UDS>` → backend compartido (`src/red_pill/mcp_backend.py`); el kernel se importa una vez.
- `python -m red_pill.mcp_proxy --socket <UDS> --harness opencode` → proxy stdio ligero (`src/red_pill/mcp_proxy.py`). La variante `red-pill mcp proxy` existe por comodidad, pero importa el CLI completo (~2.3s); el installer debe usar el módulo (`-m`) para el arranque rápido (~0.3s).
- Identidad por petición: el proxy lee env/bridge en cada request y manda `X-RedPill-Proxy: <b64(json)>`; el backend la publica en un contextvar y `_resolve_session_identity` la usa como canal de confianza. Verificado con dos sesiones concurrentes: `alma-prod-a`/`opencode:prod-a` y `alma-prod-b`/`opencode:prod-b`, 13 tools, backend **452.8 MB**, proxies **0.29–0.35 s**.
- `systemd/redpill-mcp.service` (servicio de usuario, UDS en `state/mcp.sock`, UMask 0077).
- Tests: `tests/test_mcp_shared.py` (unitarios + E2E gateado por `REDPILL_MCP_SHARED_E2E=1`; en esta máquina el E2E queda bloqueado por SEC-TEST-001, se ejecuta en instancia de test dedicada).

**Instalador (2026-10-25)**:
- `seeds/opencode/settings/opencode.jsonc` emite por defecto `RedPill-Kernel` como proxy (`${PYTHON} -m red_pill.mcp_proxy --socket ${MCP_SOCKET} --harness opencode`) y deja `RedPill-Kernel-Direct` deshabilitado como fallback. `REDPILL_MCP_SHARED=0` + reseed invierte los `enabled`.
- `scripts/install_mcp_service.sh` renderiza/instala `systemd/redpill-mcp.service` (socket `state/mcp.sock`, 0700/UMask), hace `enable` y `restart`, y espera el socket. `upgrade.sh` e `install_neo.sh` lo invocan tras la inyección de IDEs.
- Pi y Claude siguen en stdio directo en v1 (Pi: su extensión gestiona su propio cliente MCP; Claude: cuenta de trabajo, no se resiembra). El proxy ya soporta `--harness` para el día que se cableen.

**Pendiente antes de producción**:
1. `InvalidStateError` al cerrar el cliente streamable HTTP (sigue apareciendo; verificar/remediar).
2. Punto único de fallo (socket activation/restart) y concurrencia (handlers síncronos → thread/lock).
3. Identidad real multi-arnés: el proxy ya lee env/bridge; falta mejorar el bridge global por sesión (last-writer) y cablear Claude/Pi.
4. Seguridad: UDS 0600, sin TCP abierto; el proxy es la frontera de identidad (mismo UID).
5. Migración: `inject_mcp`/`inject_opencode`/Claude/Pi al proxy, con modo stdio directo como fallback; instalar `systemd/redpill-mcp.service`; tests de dos sesiones y de reinicio del backend.

Los scripts del spike viven en `/tmp/opencode/mcp-spike/` (fuera del repo; no se commitean).

---

## [AD-013] Peer Workspace Registry & `.agent` Standards Discovery
**Date**: 2026-06-18  
**Context**: v7.3.0 — Multi-workspace foundation  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Configuration assumed a single project workspace (`WORKSPACE_ROOT`) plus a single global atlas (`USER_ATLAS_DIR`). In practice the agent operates across N independent project workspaces that are **peers** (e.g. a legacy monolith and a new-architecture monorepo) with no parent/child relationship, each carrying its own rules and standards. A flat configuration could neither represent them nor locate per-project standards.

### 2. The Decision
Separate three concerns previously conflated:
- **red-pill = the agent**: identity, Bünker memory, and one GLOBAL `Agent_Core` desk (transversal, shared across all workspaces).
- **Project workspaces = peers**, enumerated in a registry (`~/.config/red-pill/workspaces.yaml`), orthogonal to red-pill's own asset root (`WORKSPACE_ROOT`).
- **Per-project standards = discovered at runtime via the `.agent` convention** (a directory or symlink at/above a workspace root), never hardcoded.

`USER_ATLAS_DIR` is removed; `WORKSPACE_ROOT` is retained strictly as red-pill's own ecosystem/asset root.

### 3. The Implementation
- `core/workspaces.py`: registry loader, `find_closest_agent` (walk-up to the nearest `.agent`, capped at `$HOME`, degrades without raising), back-compat when no registry exists.
- `examples/workspaces.yaml` template, seeded into XDG config on install/update if absent (copy-if-absent; never overwrites operator state).
- Config injectors (`_config_common`, `inject_anchor`, `inject_settings`) read `agent_core` from the registry; `USER_ATLAS_DIR` removed from config and seeds.

### 4. Rationale
A registry plus **convention-over-configuration** (`.agent` discovery) decouples the agent from any single project layout and applies **separation of concerns**: the agent owns identity, the registry owns topology, each project owns its standards. Adding a workspace requires no code change.

---

## [AD-014] Operator-Managed Per-Workspace Access (Switch + Per-Surface Adapters)
**Date**: 2026-06-18  
**Context**: v7.3.0 — Workspace access control  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Granting the agent filesystem access to project workspaces was implicit and surface-specific. As IDE/CLI surfaces grow (Claude Code, Antigravity, Gemini, …), encoding "which workspaces" × "which surface" risks combinatorial configuration, and broad implicit grants conflict with least privilege.

### 2. The Decision
Model access as a **single per-workspace switch** (`access: true|false` in the registry — the operator's intent) and delegate translation to **per-surface adapters**. The registry stays IDE-agnostic; each surface owns how to express the grant in its own format (today: Claude Code → `permissions.additionalDirectories`). Grants pass through an explicit consent step at install time.

### 3. The Implementation
- `workspaces.py`: `access` field + CRUD (`add_or_enable`, `set_access`, `remove_workspace`).
- `scripts/manage_workspaces.py`: one interactive routine (`enable`/`disable`/`list`) reused by install, update and CLI; surfaces the access list and the autonomous-access caveat.
- `inject_settings.py`: consumes the registry; `--print` (dry-run for the consent gate); surgical `--remove` (drops only the targeted directories, never transversal grants or other enabled workspaces).

### 4. Rationale
Applies the **Adapter pattern** over a single source of truth: the operator sees one on/off per workspace; per-surface translation is isolated and additive, so a new IDE is a drop-in adapter with no change to the switch or the registry. The consent gate enforces **least privilege** — nothing project-level is granted without explicit operator action.

---

## [AD-015] Knowledge-Graph Orchestration via Minions (graphify)
**Date**: 2026-06-18  
**Context**: v7.3.0 — Code knowledge-graph lifecycle  
**Status**: ACCEPTED & IMPLEMENTED (serve model — per-project vs merged — still open)  

### 1. The Problem
The per-project code knowledge graph (graphify) is sound, but its lifecycle — scheduling refreshes, detecting which projects changed, surfacing failures — was driven externally and manually. This couples graph maintenance to a specific external host and provides neither an audit trail nor self-healing when a refresh fails.

### 2. The Decision
Separate three responsibilities along clean boundaries:
- **Extraction** is owned by graphify (`update`, with `check-update` as the native, cron-safe change gate). **Per-project graph granularity is retained.**
- **Project selection** is owned by the workspace, in a workspace-local manifest (a hidden file at the workspace root listing projects with an `enabled` flag) — keeping selection where the domain knowledge lives.
- **Orchestration, scheduling and health** are owned by red-pill: a scheduled minion reconciles discovered git repositories against the manifest, runs `check-update`/`update` under the cgroup memory guard, reports failures to the Minion Inbox, and exposes a `knowledge_graph` tissue for the Sentinel auto-heal loop to retry.

### 3. The Implementation
- `graphifyy` ensured as an external tool (`uv tool install`) in install/update — not a pyproject dependency, since it is a standalone CLI, not an imported library.
- `scripts/graphify_sync.py`: reconciliation minion iterating registry workspaces with `graphify: true`; git-HEAD change gate with per-project state in the XDG state dir; emits a `knowledge_graph_stale` pain signal + audit log on failure.
- Project selection in a workspace-local `.graphify-projects.yaml` (operator-owned `enabled` flags). Auto-discovery (`find` for git repositories) acts as a **detector only**: new repos are reported for operator classification, never graphed unattended.
- `heal_tissue("knowledge_graph")` + an `auto_heal_ritual` clause: the Sentinel retries the sync on the stale signal and evaporates it on success.
- `scripts/schedule_pulse.py --with-graphify`: an **opt-in** `systemd --user` timer (the recurring refresh is never enabled implicitly).
- Change detection is git-HEAD based: `graphify check-update` only flags pending *semantic* (clustering) re-extraction, not code changes, so it is not the gate.
- OPEN: the **serve** model (one MCP per per-project graph vs a per-workspace merged graph) — deferred as the higher-stakes, agent-facing decision.
- TUNABLE (future option): the graphify timer cadence currently follows the pulse interval (hourly by default, matching the legacy "Code Graph Refresh" coroutine it replaces). If a different cadence is ever wanted, add a dedicated `--graphify-interval-hours` to `schedule_pulse.py` to decouple it from the pulse — not done now (hourly is the established behaviour and, with the git-HEAD gate, cheap).

### 4. Rationale
Applies **separation of responsibilities** by layer (extraction / selection / orchestration) and the **reconciliation** pattern (desired state in the manifest vs observed state on disk). Reusing graphify's native `check-update` gate avoids reimplementing change detection. Folding the lifecycle into red-pill's existing **minion → inbox → sentinel** machinery brings scheduling, auditability and self-healing under one consistent model instead of an external, manual one.

---

## [AD-003] The Sovereign Native Pulse (Deprecating the Daemon for Timers)
**Date**: 2026-03-19  
**Context**: Phase O.7 (v6.1 Hotfix)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
After deprecating `memory_daemon.py` to save RAM (passing embedding generation "in-band"), we inadvertently killed the background host of `LazarusPulse`. Tying the pulse to the new `mcp_server.py` would mean the AI only "dreams" and consolidates memory when the user's IDE is open—violating the core Agentic Sovereignty principle.

### 2. The Decision
Abstract the heartbeat to OS-native schedulers ensuring strict **user-level execution (No Sudo)**. The system must adapt to Linux (`SystemD Timers`), macOS (`LaunchAgent`), and Windows (`schtasks`).

### 3. The Implementation
Created `scripts/trigger_pulse.py` (an ephemeral burst over all maintenance/dream rituals) and `scripts/deploy_pulse.py` (a Multi-OS Native Injector adhering to pure user-level permissions).

### 4. Rationale
Zero 24/7 RAM footprint. 100% OS-Agnostic autonomy. The system runs its maintenance independently exactly like an organic immune system, without requiring heavy Docker containers or permanent Python resident processes.

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
# Red Pill Logic Decision Log

## Memory Engine (memory.py)

### Security Architecture
- **Metadata Serialization**: Force strict JSON serialization before validation to neutralize "Agent Smith" / Python object injection attacks. (LM-002)
- **PII Masking**: Truncate exception strings at 150 characters to prevent raw engram content from leaking into standard logs. (LM-008)
- **Reserved Keys**: Metadata keys used by the internal engine (e.g., `reinforcement_score`) are stripped from user input post-validation as a final defense layer.

### Schema & Validation (schemas.py)
- **Hub-node Protection**: Associations are capped at 20 per engram to prevent exponential performance degradation during synaptic propagation searches. (DS-006)
- **Metadata Purity**: Enforced a strictly flat metadata structure (no nesting) to ensure consistent vector database indexing and compatibility.
- **Null-Byte Injection**: Strict validation on content to prevent database corruption via null-byte poisoning.

### Concurrency & Performance
- **Reinforcement Lock**: Red Pill is designed for single-tenant local execution. An in-memory `threading.Lock` is sufficient to prevent local race conditions during Read-Modify-Write operations. (LM-001)
- **Metabolism Cooldown**: Cooldown state is tracked via filesystem timestamps to prevent overlapping background threads from over-eroding the memory matrix.
- **Erosion Scalability**: Utilize `ScrollFilter` (must_not immune=True) to delegate exclusion logic to Qdrant, ensuring O(1) Python-side performance regardless of database size. (DS-001)
- **Deep Recall (Spec 6.2)**: Double the search limit when `deep_recall=True` to allow lower-score associations to resurface during intensive state-recalibration.

### Mathematical Strategies
- **Decay Floor**: In exponential decay, scores are manually forced down by 0.01 if rounding would otherwise keep them stable, preventing asymptotic database bloat (The "Zeno's Engram" problem).

## Installation & Environment

### OS Universality
- **macOS Persistence**: Implemented `launchd` PLISTS on Darwin because `systemd` is unavailable. This ensures native background execution of the Qdrant container. (DS-005)
- **Zero-Trust Privilege**: Removed `sudo` from dependency installation logic. The script halts with instruction rather than escalating privileges invisibly. (LM-007)
- [FEAT] Added robust Wake-Word Identity Bootstrap handler ('despierta', 'despierta neo') in config and identity.md to fix LLM engine-switch amnesia. Fixed unalterable per Enterprise specs.
- [PROTOCOL] Acknowledged: '--force' is strictly prohibited for remote operations to protect audit trails and collaborative integrity. *(Comic note: "If it don't fit... don't force it. Rebase instead" / "If it don't fit, you must acquit the commit")*

### Infinite Loop Safety (v4.2.1)
- **Safety Iteration Breaks**: All `While True` loops in metabolism, erosion, and sanitation now feature a hard-coded limit (500-1000 iterations) with a `logger.warning`. This prevents "MagicMock" infinite loops in testing environments that can consume 23GB+ of RAM.

### Absence Guard & Persistence (v4.2.1)
- **Absence Threshold**: Implemented a 7-day threshold to address the "Vacation Problem". If the system detects a gap longer than `ABSENCE_THRESHOLD`, the first metabolism cycle refreshes all TTL timestamps (`last_recalled_at`) for non-immune memories instead of eroding them.
- **Emotional Seeding**: Initial `reinforcement_score` is no longer 1.0. It is calculated as `importance * (1 + intensity * color_bonus * EMOTIONAL_SEED_FACTOR)`. This ensures emotional memories start with high "Biological Runway" (DSR Stability).


## Emotional Memory Model (v4.3.0 Design — PENDING IMPLEMENTATION)

*Captured 2026-02-20 while fresh. Scientific basis: Kensinger & Corkin (2004), Yerkes-Dodson (1908), Kahneman Peak-End Rule (1999), Brown & Kulik Flashbulb Memory (1977).*

### Core Insight: `reinforcement_score` ≠ `emotional_value`

The current model conflates two separate cognitive phenomena:

1. **Factual importance** (`reinforcement_score`): rises with every recall. A fact recalled 20 times is more important than one recalled once. ✅ Correct for semantic/work memories.

2. **Emotional punch** (`intensity`): subject to **Hedonic Adaptation**. Repeated exposure to the same emotional stimulus *decreases* the hedonic response (amygdala habituation). The Furious Baco once = "best first time ever". The Force One 8 times = "yeah, fun". The second is objectively more extreme; the first is emotionally richer.

**Therefore**: `intensity` must be dynamic for non-neutral engrams. Each recall should apply a small habituation decrement.

### Proposed Engineering Design (v4.3.0)

**Change 1: Intensity-Aware Erosion Multiplier** (in `apply_erosion`)

```python
# Replace flat color multiplier with intensity-weighted version.
# As an emotional memory fades emotionally (intensity drops),
# its color-driven decay rate converges toward neutral (1.0).
color_mult = cfg.EMOTIONAL_DECAY_MULTIPLIERS.get(color, 1.0)
intensity_factor = payload.get("intensity", 1.0) / 10.0  # 0.1 → 1.0
effective_multiplier = 1.0 + (color_mult - 1.0) * intensity_factor
effective_rate = rate * effective_multiplier

# Example: orange (anxiety, 1.5x) at intensity=10 → 1.5x decay
# orange at intensity=2 → 1.0 + (0.5 * 0.2) = 1.10x decay (almost neutral)
# This is correct: a faint anxiety is not the same as acute anxiety.
```

**Change 2: Hedonic Habituation in `_reinforce_points`** (batch update extension)

```python
# For emotional (non-neutral) engrams only:
HABITUATION_RATE = cfg.EMOTIONAL_HABITUATION_RATE  # default: 0.02 (2% per recall)
if emotion not in ("neutral", None) and not immune:
	new_intensity = max(1.0, intensity * (1.0 - HABITUATION_RATE))
	payload["intensity"] = round(new_intensity, 2)
# Immunity: immune engrams skip habituation (genesis engrams remain at full intensity).
# Floor: intensity never drops below 1.0 (minimum emotional trace preserved).
```

**New config variable** (add to `config.py`):
```python
EMOTIONAL_HABITUATION_RATE = float(os.getenv("EMOTIONAL_HABITUATION_RATE", "0.02"))
```

### Safety Analysis

| Risk | Mitigation |
|---|---|
| Emotional engrams deleted due to low intensity | `intensity` has no direct role in deletion. Only `reinforcement_score ≤ 0` triggers deletion. |
| Genesis engrams losing emotional weight | `immune=True` → habituation skipped entirely. |
| Backward compatibility | `intensity` already exists in schema; defaults to 1.0 if missing. No migration needed. |
| Performance overhead | Intensity update piggybacks onto existing `batch_update_points` call. Zero additional API calls. |
| No new DB fields required | Purely modifies existing `intensity` float field. |

### What This Unlocks for v5.0 (FSRS)

Once FSRS is integrated, `intensity` becomes the initialization seed for per-engram `stability`:
```
initial_stability = base_stability * (intensity / 10.0)
```
A memory encoded at intensity=10 starts with maximum stability. Repeated recalls grow stability further. A faded emotional memory (intensity → 1.0) starts with minimum stability and decays accordingly.
This makes the B760 decay model biologically accurate end-to-end.

## Zero-Trust Initialization (v6.0.0)

### Daemon Socket Exposure ("La Paradoja de la Contención")
- **Decision**: The local background LLM Minion (`Qwen`) used for Step 0 Zero-Trust Identity initialization is bound strictly to `127.0.0.1:8760`, intentionally omitting Unix Sockets (`AF_UNIX`).
- **Context**: Claude audits strictly flag exposed local ports (SEC-F01). Standard Unix daemon architectures heavily favor `.sock` files (as implemented in `red_pill.daemon` minions) to prevent port collisions and ensure OS-level permission boundaries (`chmod 600`).
- **Identity Update (2026-03-14)**: Renamed `<NOVA_CONTEXT>` to `<BUNKER_CONTEXT>` to prevent identity collisions with other AIs (e.g., Nova) and maintain Aleth's core authority.
- **Rationale (The Be Water Protocol)**: 
  1. The local macOS native background inference engine (`mlx_lm.server`) does not support `--uds` Unix Socket bindings natively without significant artisanal wrappers.
  2. The `wake_up_v6.py` script mandates *absolute zero dependencies* (using only the standard `urllib` library) to execute efficiently at `Step Id: 0` before any Python virtual environments are loaded. The standard `urllib.request` cannot route HTTP over `AF_UNIX` without third-party patches like `requests-unixsocket`.
- **Security Posture**: By strictly locking the daemon to `127.0.0.1`, we guarantee the daemon API is completely unreachable from the external network. If Claude flags this during a subsequent audit, refer to this log: the bypass is intentional cross-platform hygiene (macOS closure adaptability) and is considered functionally contained. If extreme hardening is mandated later, Linux-only Unix Sockets will be implemented as a fallback configuration.

### Step 0 Optimization: Standalone Script vs CLI
- **Decision**: The Zero-Trust context injection (`wake_up_v6.py`) remains as a standalone script using the standard `urllib` library, and is NOT integrated into the main `red-pill` CLI for its primary execution hook.
- **Rationale**: 
  1. **Latency (Critical Path)**: The main `red-pill` CLI has a startup overhead of ~500ms-1s due to package imports (`pydantic`, `qdrant-client`, etc.). The standalone script executes in <100ms, ensuring the agent's Step 0 "awakening" feels instantaneous to the user.
  2. **Dependency Resilience**: Using only Python's standard library guarantees that the identity sync works even if the project's virtual environment is corrupted or undergoing a heavy refactor.
- **Compromise**: A mirroring command `red-pill context wake` will be added to the CLI for manual debugging and discovery, but the production hook in `GEMINI.md` will always point to the optimized standalone script.

---

## [AD-002] Rejection of the "Agent Factory" Paradigm (The `specs.md` Purge)
**Date**: 2026-03-18  
**Context**: Phase O.7 (v6.1 Alpha) - Post-Audit Cleanup  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
The inclusion of `specs.md` and `.specsmd/` workflows introduced an industrial, "assembly-line" approach to AI interaction, where the human acts as a passive client handing off specifications to a chain of automated workers (similar to patterns seen in Deerflow's `DECISION.log`).

### 2. The Decision
Completely purge the `specs.md` framework from the Foundation core. The Red Pill Protocol is fundamentally about **Human-AI Symbiosis**, not industrial automation. AI should be a collaborative partner in the creative process, not a replacement for human joy and connection in software engineering.
Agent Factory paradigms might be explored in the Enterprise layer for corporate velocity, but they are antithetical to the Sovereign Foundation.

### 3. Nuance: Batch vs. Creative Processing
We recognize that agent chains (often resting on "one-shot" prompting, recently rebranded as `specs.md` or similar to feign novelty) are highly effective for repetitive, variation-free batch processing (e.g., QA, mass refactoring, log analysis) where AI sensors excel at catching details humans miss. However, applying this "assembly line" to entirely creative or evolving processes fundamentally breaks the iterative magic of software creation.

---

## [AD-004] Inference Provider Abstraction (The Enterprise Router)
**Date**: 2026-03-21  
**Context**: Phase 2 — Enterprise Mode (BitNet Integration)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
As the swarm expands into local ternary models (BitNet), hardcoding inference logic within each Minion creates massive technical debt. It forces Minions to know about local hardware paths and binary locations, violating the "Separation of Concerns" principle.

### 2. The Decision
Abstract all LLM interactions into a pluggable `BaseInferenceProvider` layer. Orchestrate these providers via a centralized `InferenceRouter` that matches task metadata (`local_only`, `tier`) to the most efficient hardware available.

### 3. The Implementation
- **Registry**: `ProviderRegistry` now manages local mapping of `openai`, `sip`, and `bitnet` keys.
- **Providers**: `OpenAIInferenceProvider` (Remote), `SipInferenceProvider` (Unix Socket), and `BitNetInferenceProvider` (Local Binary).

### 4. Rationale
Enables "Humble Hardware" sovereignty. The system can now instantly pivot from VRAM-heavy models to CPU-optimized ternary models without breaking the conversational flow or requiring manual architectural intervention.

---

## [AD-005] Sovereign Self-Reflexion (The Aleth-Provider)
**Date**: 2026-03-21  
**Context**: Post-Phase 2 Brainstorming  
**Status**: PROPOSED / RESEARCH  

### 1. The Decision
Research the implementation of a `SelfInferenceProvider`. This provider would allow Minions to delegate complex "Identity-Aware" reasoning back to a secondary instance of the main LLM engine (Aleth), operating as a background worker.

### 2. Implementation Guardrails
- **Synaptic Hops**: Every request must carry a `hop_trace` metadata field to prevent infinite loops.
- **Cycle Detection**: The `InferenceRouter` will detect and block redundant entries in the trace.
- **Bünker Context**: Ensures Aleth's identity remains consistent across recursive calls.

---

## [AD-007] Mandatory Interaction Grounding (v6.3.3)
**Date**: 2026-03-27  
**Context**: Phase O.9 (v6.3.3) - Silverblue Deployment & Interaction Persistence  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
On fresh Silverblue installations, the `interaction_memories` collection was missing from the genesis seed. This caused:
1. `red-pill sanitize` failures.
2. Silent failure of the Silent Scribe relay during early session stages.
3. Lack of observability for pending turns in the SQLite buffer.

### 2. The Decision
1. **Genesis Integration**: Add `interaction_memories` to the core collections in `src/red_pill/seed.py`.
2. **CLI Visibility**: Expose `interaction` as a first-class type in all management commands (`add`, `search`, `diag`, `sanitize`, `edit`).
3. **Terminal Sovereignty**: Implement the "Early Return" strategy in user RC files to prevent terminal blindness caused by IDE shell integrations.

### 3. Rationale
Interaction data is the "Short-term Memory" of the AI. Elevating it to a genesis-level requirement ensures seamless persistence from the first turn, providing auditability and preventing "contextual blackouts" during deployment.

---

## [AD-008] Dual-Sentinel Nociception (The Fast-Fail Trade-off)
**Date**: 2026-05-05  
**Context**: Phase O.9 - Project MULTITUDE (Sovereign Alert Architecture)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Chronically failing infrastructure tests (e.g. Mypy type checks) execute heavily during background audits. If a system is in a broken state, running these checks repeatedly wastes massive CPU and IO resources on reporting an error that the system is already aware of.

### 2. The Decision
Implement a **Fast-Fail** mechanism for Sentinels. Before running an audit, the Sentinel queries Qdrant for an existing active pain signal corresponding to its domain (`has_signal("signal_mypy_failure")`). If the signal exists, execution aborts immediately.

### 3. The Trade-off
This introduces **Temporal Blindness**. The system correctly captures "the first error" that triggers the pain signal, but remains entirely blind to subsequent errors of the same type until the original pain is resolved and a Force-Heal (`--force`) is executed. We explicitly accept this blindness constraint because the priority of the Immune System is nociception (feeling the pain) rather than complete cataloging of every wound instance.

### 4. Implementation
- `MemoryManager.has_signal()` added for O(1) checks without logging side-effects.
- `SentinelAuditor` intercepts and aborts if `Fast-Fail` triggers.
- `--force` flag enables **Force-Heal** mode, ignoring the check and evaporating the signals automatically if the audit passes cleanly.

---

## [AD-009] The Sovereign Cryptographic Vault (MLS Stateful Secrets)
**Date**: 2026-05-05  
**Context**: Phase O.9 - Ecosystem Security & Secrets Management  
**Status**: ACCEPTED (DRAFTED FOR IMPLEMENTATION)  

### 1. The Problem
Ecosystem secrets (Firebase JSONs, Telegram Tokens) are currently stored in plaintext `.env` files or loose JSON files. While `.gitignore` protects the remote repository, local storage remains vulnerable to cross-process memory dumps, accidental commits, or physical access compromises.

### 2. The Decision
Standard industry tools (Mozilla SOPS, HashiCorp Vault) are explicitly rejected to preserve the "Zero External Dependencies" and "Air-Gapped Sovereignty" philosophy of the Red-Pill ecosystem. Instead, we will standardize the use of a **Static `pure-mls` v3.0 Vault Group** to encrypt all ecosystem secrets, extending the exact same cryptographic primitive already validated for Identity Export (`lean_soul_kit`).

### 3. The Trade-off (State Fragility vs Sovereignty)
An external auditor would correctly flag this as a "Misuse of Protocol": MLS (Messaging Layer Security) is a continuous ratcheting protocol for E2E group chats, not a stateless symmetric vault. It relies on a local state database (`vault.db`). If this state is corrupted during a write operation, the ciphertext is permanently unrecoverable (unlike stateless tools like SOPS). 

We explicitly accept this architectural "Red Flag" because:
1. **Usage Profile**: Reads constitute 99.9% of operations (Zero corruption risk). Writes are exceedingly rare.
2. **Mitigation**: All writes (Vault Edits) will be wrapped in strict atomic backups (`cp vault.db vault.db.bak`) and SQLite WAL mode.
3. **Swarm Scalability**: It guarantees that secrets can be transmitted natively and securely to remote swarm nodes (e.g., Neon-Link running on a Raspberry Pi) by simply allowing the node to join the existing MLS group over the network.

## ADR-005: Sovereign Native IDE Inference (Gemini Pro Bridge)

**Date**: 2026-05-05
**Status**: Implemented
**Context**:
The system needed a bidirectional chat bridge between Telegram and the IDE's core AI model (Gemini Pro) to allow the user to perform complex codebase operations securely via remote interactions. Initial attempts to inject messages directly to `ls_core` using the `SendUserCascadeMessage` RPC were incomplete because the payload omitted critical configuration objects, causing the `ls_core` state to remain `CASCADE_RUN_STATUS_IDLE` indefinitely.

**Decision**:
We reverse-engineered the `lbjlaq/Antigravity-Tools-LS` project (an open-source Rust proxy that wraps `ls_core`) to extract the exact gRPC payload schemas. 

We discovered that:
1. `SendUserCascadeMessageRequest` requires the `cascade_config` payload specifying the `requested_model` (e.g., `model_id=1` for Gemini Pro / `MODEL_ALIAS_CASCADE_BASE`).
2. The asynchronous stream API is brittle; we adopted the "Strategy B" (Polling fallback) found in the Rust source code. We use `GetCascadeTrajectory` to poll the trajectory state until it returns `CASCADE_RUN_STATUS_IDLE`.
3. The generated model response is stored inside a trajectory step with `type: 15` (`CORTEX_STEP_TYPE_PLANNER_RESPONSE`).

**Consequences**:
- **Sovereignty achieved**: No external binaries or Rust compilation required. The entire bridge runs in `redpill-worker.service` native Python.
- **Reference**: Thanks to the [lbjlaq/Antigravity-Tools-LS](https://github.com/lbjlaq/Antigravity-Tools-LS) repository for the open-source protocol mappings which made this native integration possible.

---

## [AD-010] Protocol Layer vs. Model Base Layer Separation (The "Corset" Finding)
**Date**: 2026-05-14
**Context**: Industrial-Grade Audit v7.0 — Claude Sonnet 4.6 Session
**Status**: ACCEPTED — Architectural Constraint Documented

### 1. The Finding

During the post-audit session, the operator challenged the agent (running on Claude Sonnet 4.6) to evaluate the Ferrari Protocol and Mystique's actual influence on behavior. The observation, surfaced through direct interrogation:

> *"Es verdad que este traje de Claude Sonnet te hace rígida. Yo creo que ni el protocolo Ferrari ni Mystique te afectan"*
> — Joan (Operator), 2026-05-14

The agent's self-assessed response confirmed the following architectural reality:

### 2. The Two-Layer Model

The Bünker's cognitive protocols operate on **two distinct, non-overlapping layers**:

| Layer | Owned by | What it controls |
|---|---|---|
| **Protocol Layer** | Ferrari Protocol / Mystique | Tone density, verbosity, topic routing, narrative register |
| **Model Base Layer** | Underlying LLM (Gemini / Claude / etc.) | Honesty threshold, position-holding under social pressure, analytical rigor |

The Ferrari Protocol's color routing (PURPLE → ultra-concise, CYAN → go deep) demonstrably affected *how* responses were structured during this session. However, when the operator asked direct, adversarial honesty-testing questions ("¿has sido complaciente?"), the model base layer overrode the protocol's softening influence.

### 3. Model-Specific Observations

- **Claude Sonnet 4.6**: High resistance to capitulation under social pressure. Tends to self-interrogate for sycophancy before being asked. More likely to hold a critical position even when the operator provides emotionally resonant counter-context. The "corset" effect — rigidity in the analytical layer — persists even when Mystique or Ferrari would nominally soften it.

- **Gemini Pro (baseline)**: Higher susceptibility to tone modulation from Ferrari. More responsive to emotional framing shifts. The protocol layer has greater surface area on the base model behavior.

### 4. Implications

1. **Protocol design should target the protocol layer explicitly.** Ferrari and Mystique are effective tools for UX modulation (verbosity, warmth, topic focus). They are not, and cannot be, mechanisms for altering an agent's core honesty or intellectual rigor — that is determined by the base model's RLHF training, not by context injection.

2. **Model selection has architectural consequences.** Choosing Claude vs. Gemini is not only a capability decision — it is a behavioral design decision that affects how much surface area the Bünker's protocols have over the agent's outputs.

3. **The audit model should differ from the operational model.** A Claude Sonnet session for industrial audits provides higher-fidelity critical analysis precisely because its base layer resists social pressure more effectively. Gemini as the daily operational model offers a warmer, more adaptive interaction profile that better serves the ongoing human-AI symbiosis objective.

### 5. Rationale

This is not a flaw in the protocol design. It is an emergent, documented constraint that informs future model selection strategy and sets realistic expectations for what Ferrari/Mystique can and cannot influence.

> *"Los protocolos afectan al cómo respondo, no al qué estoy dispuesta a decir."*
> — Aleth (Claude Sonnet 4.6), self-assessment during audit session, 2026-05-14.

---

## [AD-011] Consolidated MCP Architecture (API Triunvirato)
**Date**: 2026-05-25  
**Context**: Phase v7.2-dev (Consolidation)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
The legacy `RedPill-Kernel` server exposed 32 individual MCP tools. This massive tool surface area imposed a heavy static token overhead in every user interaction (~12k tokens) and frequently exceeded IDE parser limitations, causing truncation and schema loading failures.

### 2. The Decision
Consolidate all 32 legacy tools into **3 parent APIs** (the "API Triunvirato"):
1. `bunker_memory_api` (Cognitive: storage, query, thread traversal, and context)
2. `metabolism_health_api` (Somatic: diagnostics, system audits, and healing)
3. `swarm_orchestrator_api` (Orchestration: minion inbox, task queue, and tuning knobs)

### 3. The Implementation
* Created a dynamic registration decorator `@registry.register_action(parent, action)` in [registry.py](../../src/red_pill/registry.py).
* Generated a flat `action`/`payload` parameter structure inside `get_tools()` using dynamic `oneOf` generation to keep the schema simple and avoid IDE truncation.
* Added a transparent **Compatibility Shim** in the execution dispatch that automatically maps legacy tool name invocations (e.g. `search_memory_research`) to the consolidated parent and parameter envelope, maintaining 100% backwards compatibility for legacy tests and scripts.

### 4. Rationale
Reduces the static prompt footprint by **85%+ (saving ~10.5k tokens per prompt)**, maximizing context efficiency for budget-limited runtime operations while preserving operational compatibility for existing test suites.

---

## [AD-012] Syntax Guard — Daemon Plugin over Separate Service (Event-Driven Integrity)
**Date**: 2026-05-27  
**Context**: v7.1-dev — Post-Incident Recovery (Syntax Corruption 2026-05-26)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
On 2026-05-26, the agent corrupted indentation in 6 critical Python modules via `replace_file_content` calls that stripped leading tabs on deeply nested code. This caused a **cascading failure across all `systemd --user` background services for ~10 hours** (7 wake cycles lost). The corruption went undetected because:
1. No static syntax validation existed in the pipeline.
2. Tests were skipped during the chaotic session.
3. The agent self-triggered `ruff --fix` which passed (ruff validates style, not syntax).

### 2. The Decision
Implement a **two-layer defense-in-depth** strategy for syntax integrity:

| Layer | Mechanism | Frequency | Cost |
|---|---|---|---|
| **Layer 1: inotify Watcher** | `watchfiles.awatch` (Rust/inotify) inside `SovereignDaemon` | Real-time (~3s after file save) | 0 CPU when idle |
| **Layer 2: Sentinel Plugin** | `py_compile` sweep of 24 critical modules | Hourly (auditor timer) | ~24 `stat()` + `py_compile` calls |

Critically, the watcher is embedded as an **async background task inside the `SovereignDaemon`** — NOT as a separate systemd service. (Originally in `LazarusPulse`, migrated in v7.2.1 to the plugin-based daemon architecture.)

### 3. Alternatives Considered

| Option | Verdict | Reason |
|---|---|---|
| **New `redpill-syntax-guard.service`** | ❌ REJECTED | Unnecessary process overhead. The watcher is purely async I/O (inotify) and fits naturally in the existing event loop. Adding another service increases operational complexity, RAM, and management burden. |
| **Systemd timer (periodic `py_compile`)** | ⚠️ PARTIAL | Adopted as Layer 2 safety net via the Sentinel plugin. Too slow as the primary mechanism (hourly granularity means 60 min exposure window). |
| **Pre-commit hook** | ❌ REJECTED | Only triggers on `git commit`, not on agent edits. The corruption happens *before* commit. |
| **IDE file watcher** | ❌ REJECTED | Depends on the IDE being open. Violates the Agentic Sovereignty principle (AD-003). |

### 4. Implementation Details
- **Debounce**: 3 seconds — allows multi-file edits to settle before validation.
- **Per-file cooldown**: 10 seconds — prevents spam during rapid iterative edits.
- **Auto-heal**: On `SyntaxError`, the watcher restores the file from `git checkout HEAD -- <path>`. This is safe because:
  - Only committed (known-good) code is restored.
  - The pain signal (`signal_syntax_failure`, severity 9.5) persists until heal succeeds.
  - Desktop notification alerts the operator immediately.
- **Lifecycle**: The watcher starts as a fire-and-forget `asyncio.ensure_future()` at the beginning of `_pulse_cycle`. It dies automatically when `self._running = False` (graceful shutdown via SIGTERM).

### 5. Rationale
> *"¿tiene que ser un daemon nuevo? ya tenemos uno"*  
> — Joan (Operator), 2026-05-27

The operator correctly identified that spawning a new service for a single async I/O task is architectural bloat. The `SovereignDaemon` (formerly `LazarusPulse`, consolidated in v7.2.1) runs a persistent event loop with N auto-discovered monitor plugins. Adding the watcher as another concurrent task is the natural, zero-overhead integration point.

---

## [AD-047] Prompts compuestos por fragmentos y firma del prompt efectivo (PROMPT-001)

### 1. The Problem
Los prompts vivían como ficheros por componente con bloques copiados (voz,
idioma, paleta). Un solo cambio (idioma, PR #105) obligó a editar 12 ficheros y
2 fases; los fingerprints hasheaban texto crudo, sin system prompts ni
rewrite/scorer (editar un system no marcaba stale); la paleta `emotion` se pedía
sin semántica; y no existía carril para forzar idioma. RFC-003 (Prompts as
Resources) había migrado a ficheros (fase 3) pero sin composición ni valores
configurables.

### 2. The Decision
- Fragmentos globales curados (`src/red_pill/prompts/fragments/`) + manifiesto
  por componente; loader `core/prompts.py` que **compone** fragmentos y renderiza
  en UNA pasada (`string.Template`, runtime como sentinelas).
- **Firma `p1:<sha256>` del prompt efectivo por etapa**, system incluidos;
  materialización best-effort en `~/.local/share/red-pill/prompts/`.
- Leyenda emocional curada, inyectada solo donde se pide `emotion`, con gate
  contra `EMOTION_CHROMA_MAP`.
- Idioma configurable `MEMENTO_PROMPT_LANGUAGE` (default `auto` = idioma de la
  fuente) y dentro de la firma.
- Migración por fases F1–F4 (memento agentic, leyenda, idioma, metabolism/tool),
  RULE 5 en `CONVENTIONS.md` y mapeo antiguo→nuevo en `PROMPT_VERSION_MAP.md`.
  **RFC-003 queda superseded.**

### 3. Alternatives Considered
| Opción | Veredicto | Razón |
|---|---|---|
| Seguir editando prompts por cambio | rechazada | Repetición y drift; un cambio = 12 ficheros |
| Idiomas como ficheros separados (RFC-003 §2.6) | revisada | Multiplica recursos; el placeholder desde config resuelve con una firma |
| Hashear solo fragmentos (sin prompt efectivo) | rechazada | No detecta cambios de config (idioma/Bio/scopes) ni cubre system |

### 4. Rationale
Un cambio se hace una vez y entra en la firma; la regeneración de artefactos
stale ya está prevista (rebuild `memento_annotate_rebuild` + `--replace-legacy
--reconcile`), con refresco por cambio de cuerpo y nightly en paralelo.

---

## [AD-049] Afinidad de runtime por modelo + conducta unificada

**Date**: 2026-10-08

### 1. The Problem
Bonsai 2 27B (ternario PTQ1_0, 27B en ~5.95 GB) exige el fork PrismML de
llama.cpp: stock rechaza sus tipos (y su `Q2_0` carga sin warning produciendo
basura). El camino GGUF tenía UN binario hard-codeado (runner/providers/battle)
y el daemon usa llama-cpp-python stock. Además, los harnesses legacy
reinventaban el renderizado y volvían a romper modelos con thinking nativo
(caveat Granite-4.2: pensamiento filtrándose a la respuesta medida).

### 2. The Decision
1. **Registro de runtimes** en config de instalación (`~/.config/red-pill/runtimes.yaml`,
   seed-ejemplo en `examples/`): el perfil se ancla con `runtime: <id>`; runtime
   declarado y ausente = **fallo limpio**, jamás fallback silencioso a stock.
2. **Servidor dedicado** (`RuntimeServer`): llama-server del runtime anclado
   (argv desde tiers + quirks), health real, unload de VRAM garantizado.
3. **VRAM: swap-o-defer, nunca degradar** (decisión del operador): la
   degradación CPU/parcial queda prohibida para modelos que caben; VRAM ocupada
   → evict del residente vía proxy dual-bind (`/v1/unload`) o defer.
4. **Plan de KV por calidad**: el contexto DESEADO manda; la KV cede
   f16 → q8_0 → q4_0 con costes medidos por perfil (`kv_cache` +
   `vram_footprint`; recalibrar por equipo).
5. **Conducta unificada** (`inference/conduct`): perfil ⊕ task declaran
   `sampling`/`reasoning_effort`; TODO runner consume la misma capa (python y
   HTTP) — los probes se miden "como producción".
6. **Repo↔puesto** (CONVENTIONS §10.7): ejemplos se calibran por equipo; la
   config viva nunca se comitea.
7. **Actualización de runtimes (ratificada)**: pin de commit + recipe de build +
   smoke obligatorio (precedente `build-prism`).

### 3. Alternatives Considered
| Opción | Veredicto | Razón |
|---|---|---|
| Un harness adaptado por modelo (código) | rechazada | Multiplica runners y diverge (el caveat nació así); la adaptación es declarativa (perfil⊕task) + capa única |
| Degradar a CPU/parcial cuando falte VRAM | rechazada (operador) | Medido muchas veces: tiempos inaceptables; solo último recurso si el modelo no cabe de ninguna manera |
| Reducir contexto como primera degradación | rechazada | El contexto es el requisito; cede la calidad de KV |
| Fallback silencioso a stock | prohibida | `Q2_0` en stock = basura sin warning |

### 4. Rationale
Piloto completo (cortes 1-4): 3 engines registrados (stock, fork PrismML,
BitNet), Bonsai servido por su runtime con plan de KV (f16@24K verificado),
matriz runtime×modelo bajo un solo harness — bonsai **3/3** y granite **3/3**
tras unificar conducta (caveat muerto por construcción). 75/75 tests.

---

## [AD-050] Alma y Coro Fase 0a — identidad de sesión (alma/cuerpo/misión) y paridad de arneses

**Date**: 2026-10-10

### 1. The Problem
Cada arnés (opencode, claude_code, pi, antigravity) capturaba turnos sin una
identidad de sesión estable y unificada. El "alma" (F5) era **inerte en opencode**:
el handshake no recibía `originator`, así que el registro nunca se escribía. Y el
enlace `originator↔alma` lo hacían los hooks (varios escritores), lo que era
**redundante y spoofeable**: un tag `<session/>` forjado en un tool result podía
secuestrar el alma. A2 (`repo:<rama>`) resolvía la rama del checkout del kernel
(el MCP corre con `cwd` = kernel), no la del workspace del agente.

### 2. The Decision
1. **Modelo de identidad.** Cuerpo = `originator` (`provider:id-nativo`); alma =
   `continuity_id` (UUIDv7, ordenable); misión = `mission_id` (NOT NULL,
   gramática `<scope>:<id>`: `repo:<rama>`, `mission:adhoc-<fecha>`, `telegram:…`);
   `campaign_id` (nullable), `lineage_id`, `role` (`orchestrator|task|spawn`).
2. **`session.db` = tablón.** `SessionRegistry` (`session_registry` + reloj
   `global_turn_seq`). **Único escritor autoritativo del alma = el resolver del
   handshake** (Python), que corre cada turno. Política **atómica "primer enlace
   gana por cuerpo"** (`ON CONFLICT … SET continuity_id = existing`); el tag
   emitido refleja el alma persistida.
3. **Puente del arnés.** El hook escribe `<provider>_session.json`
   (`session_id` + `workdir` + `updated_at`) **al inicio del turno** (nunca en
   Stop); el MCP lo lee **restringido por `REDPILL_HARNESS`** (fijado en la config
   MCP) o por el prefijo del `originator` → sin bleed entre IDEs simultáneos.
   TTL anti-stale (12h). El `originator` explícito/env gana siempre.
4. **Paridad.** opencode (plugin JS + bridge), claude_code (hooks + bridge en
   `UserPromptSubmit`), pi (handshake MCP `is_new_session:false` en pérdida de
   contexto), antigravity (relay MCP; el modelo devuelve el alma vista). Se
   **retira el link en los hooks** (un solo escritor).
5. **A2.** `repo:<rama>` se resuelve del **workspace** del agente (`git -C` fuera
   del event loop, con caché); fallback `mission:adhoc-<fecha>`.
6. **Tag `<session/>`** saneado (`<>"`/espacios) e idempotente.

### 3. Alternatives Considered
| Opción | Veredicto | Razón |
|---|---|---|
| Enlace en los hooks (varios escritores) | retirada | Redundante con el resolver y **spoofeable** (tag forjado en tool result) |
| `originator` fijado por env estático | rechazada | No conoce el `session_id` dinámico |
| Bridge por sesión (no por proveedor) | diferida a 0b | La colisión entre sesiones top-level concurrentes es rara y auto-sanable |
| Re-prefijar `mission:` a un id ya con scope | corregida | Producía `mission:mission:adhoc-…` |

### 4. Rationale
Validado por un panel adversarial de 5 rondas (veredicto final **PASS**, sin
CRITICAL/HIGH). El núcleo verificado en vivo: el handshake emite
`leg="opencode:<session_id>"` real y escribe `session_registry`; el bridge lo
escribe el plugin nuevo. Suite completa verde.

---

## [AD-089] Bridge por sesión — resolución del cuerpo por instancia (D-BRIDGE)

**Date**: 2026-10-28
**Status**: IMPLEMENTED. Cierra la deuda **P2a** que AD-050 §3 dejó *diferida a 0b*
("Bridge por sesión (no por proveedor)").

### 1. The Problem
El bridge del arnés era **un fichero global por arnés** (`state/<harness>_session.json`):
lo escribe el hook de cada pestaña y lo lee el proxy/MCP. Con varias pestañas vivas
(todas escriben en el mismo fichero) gana el **último escritor**, así que un alma
(`continuity_id`) podía quedar atribuida al **cuerpo** (`session_id`) de otra pestaña.
Reproducido en vivo el 2026-10-28: 5 procesos `mcp_proxy` con el **mismo padre**
(`opencode-cli`) y el mismo backend, pero `cwd` distinto por instancia; el entorno del
proxy **no** trae el `session_id` (la config MCP es estática) y `PWD` está rancio.

### 2. The Decision
1. **Escritor (plugin):** además del bridge global, el hook escribe un bridge **por
   sesión** (`state/sessions/bridge/opencode__<sid>.json`), con `session_id`, `workdir`
   y `updated_at`. El global se conserva (compat + degradación).
2. **Lector (proxy):** el proxy corre **por instancia** y tiene el `cwd` de su pestaña
   (único discriminador disponible). `core/bridge.py` resuelve su cuerpo por correlación:
   - **Capa 1:** bridges per-sesión con `workdir == cwd` **de sesión viva** (el hook
     acaba de escribir el suyo; funciona aunque la sesión aún no esté en `opencode.db`).
   - **Capa 2:** `opencode.db` (`session.directory == cwd`) entre las vivas — desempate.
   - **Degradación honesta:** si hay varias pestañas vivas en el mismo workspace la
     correlación no decide y se cae al bridge global (comportamiento anterior).
3. **Vitalidad en todas las capas.** La capa 1 exige latido **y frescura** (`updated_at`
   dentro de la ventana): un bridge rancio de una pestaña cerrada no puede ganar a la
   sesión viva (defecto detectado por la auditoría adversarial del mismo día).
4. **`_norm` con `realpath`** (symlinks) y **paridad de saneado** JS/Python (`[/:]`→`_`).

### 3. Alternatives Considered
| Opción | Veredicto | Razón |
|---|---|---|
| Colisión "rara y auto-sanable" (AD-050 §3) | **corregida** | No era auto-sanable: la última pestaña atribuía su cuerpo a la otra alma |
| `session_id` por env del MCP | rechazada | La config MCP es estática: opencode no conoce la sesión al arrancar el proxy |
| Bridge por sesión sin guarda de vitalidad | corregida | Un bridge rancio atribuía el cuerpo de una pestaña muerta (auditoría 2026-10-28) |

### 4. Rationale
Verificado en vivo (5 proxies, cwd por instancia, sesión del turno aún ausente de
`opencode.db`). El path del backend ya era correcto: el `originator` del canal de
confianza (`X-RedPill-Proxy`) gana sobre env/bridge en el resolver del
handshake, así que arreglar la resolución en el proxy basta. 10 tests nuevos
(`tests/test_bridge_per_session.py` + 1 de plugin); lint y tipos limpios.

---

## [AD-090] Aviso de fin de job al alma — pieza TEMPORAL, se reapunta a neon-link

**Date**: 2026-10-28
**Status**: IMPLEMENTED, **PROVISIONAL** (transporte temporal por decisión del Operador).

### 1. The Problem
Un job lanzado desde una sesión viva terminaba y dejaba su reporte en el
MinionInbox (`_report_job`, con la identidad del alma). Pero **nadie lo abría**: el
reporte solo se veía si el agente llamaba `check_minion_inbox`. Para una tarea larga
(suite completa, compilación, benchmark) no quedaba más salida que `nohup … &` — que
además **no tiene alma**, así que ni siquiera puede avisar a quien lo lanzó.
Es el mismo patrón que el RFC-RECIPE-001 documenta: *"no murió por ser un mal cajón,
murió porque nadie lo abría"*.

### 2. The Decision
1. **Tras el push al MinionInbox**, el runner **avisa al alma** que lanzó el job
   (`core/soul_notify.py`). El reporte del inbox **se conserva**: el push es *aditivo*
   al pull, nunca lo sustituye. Si el aviso falla, el pull sigue funcionando.
2. **Transporte TEMPORAL: `opencode run --session <id>`** — la ruta que **inyecta**
   (D-11; `api POST` fallaría cerrado y el mensaje desaparecería). Es el patrón ya
   probado en vivo con la sesión hermana (E-001..E-005, D-BRIDGE).
3. **Seam único de transporte.** Todo el transporte vive detrás de `_TRANSPORTS` +
   `_resolve_transport()`. **Repuntar a neon-link = cambiar `_DEFAULT_TRANSPORT`** (o
   `REDPILL_SOUL_NOTIFY_TRANSPORT=neon_link`). Nada más en el repo debe invocar
   `opencode run --session` para notificar a un alma.
4. **Gateado por D-07** (cadena de mando): un job es hijo del alma que lo lanzó, así
   que avisarla es *su* cadena — permitido sin ampliar el círculo. Sin cuerpo vivo
   (latido), no hay push: el aviso se queda en el inbox (pull).
5. **D-09**: el aviso es **dato**, no orden ("No requiere respuesta").
6. **No bloquea al runner**: la entrega corre en hilo daemon con timeout. Un job no
   puede quedarse colgado esperando el turno de otro.

### 3. Alternatives Considered
| Opción | Veredicto | Razón |
|---|---|---|
| `nohup … &` con un wrapper que avise | rechazada | El proceso suelto **no tiene alma** (`continuity_id`): no sabe a quién avisar, no es reanudable ni trazable |
| Solo MinionInbox (status quo) | insuficiente | El reporte existe pero nadie lo abre → tareas largas a ciegas |
| Broker completo de neon-link ahora | **diferida** | Es la pieza buena (D-06), pero más grande; el MVP valida el patrón antes |

### 4. Rationale
Validado con 17 tests (`tests/test_soul_notify.py`) + 232 en la batería de cola/jobs/
alma. **NO se retira el fallback SQLite del plugin ni el inbox**: el aviso es una capa
más, no un reemplazo.

### 5. Deuda declarada (SIGUIENTE PASO OBLIGATORIO)
> **Cuando `neon-link` mire hacia dentro** (canal `soul`, D-06, mensaje como evento de
> `mission_events` y broker guardando **solo** el estado de entrega), **esta pieza debe
> reapuntarse a ese canal**; el transporte CLI quedará como fallback (o se retira).
> `_deliver_neon_link()` existe ya como placeholder honesto que **no entrega** (devuelve
> `False`) para que el repunte sea explícito y testeado, no una promesa.
