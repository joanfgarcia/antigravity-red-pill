# RFC-005 — Autonomía local de herramientas y delegación de tareas por Telegram

| Field | Value |
|---|---|
| **RFC** | 005 |
| **Title** | Confinamiento de `run_bash` + niveles de autonomía + delegación `/mission` a modelo local con tools |
| **Status** | DRAFT — diseño; sin implementar |
| **Author** | Joan García (Operator) / Aleth (Agent) |
| **Created** | 2026-09-30 |
| **Related** | AD-041 (DECISION_LOG), HARNESS-003/004 (CHANGELOG), RFC_TELEGRAM_RESILIENCE (catálogo/roles), RFC_JOB_DAG (job manager), `docs/TECHNICAL/MINIONS.md`, `scripts/autonomy_ladder.py` |

---

## 0. Resumen

Empujados por el arreglo del tool-calling local (HARNESS-003/004) y la
medición de autonomía con `scripts/autonomy_ladder.py`, este RFC cierra el
triángulo que falta para **delegar tareas con herramientas a un modelo local
desde Telegram sin que el modelo pueda liarla**:

1. **Confinar la ejecución** de `run_bash` — hoy `cwd + timeout` es el único
   límite y el modelo puede tocar todo el host (incluido `find / -delete`).
2. **Definir niveles de autonomía** derivados de la medición (read-only por
   defecto; mutación con confirmación; mutación autónoma solo si el veredicto
   del arnés la habilita).
3. **Cablear la delegación** reutilizando lo que ya existe: el comando
   `/mission` del worker (= `HEAVY_PATH`) ya encola un `agentic_job` con cascade
   de sesión; falta permitir el backend `local-tools`, meterlo bajo jaula y
   aplicar la política de autonomía.

No se propone forzar autonomía alta: el veredicto medido es **read-only con
verificador**. El objetivo es que la delegación sea **segura por construcción**,
no confiada.

---

## 1. Contexto y motivación

### 1.1 Lo que se rompió (y arregló) — HARNESS-003/004

- El backend `local-tools` (`run_local_minion`) llevaba **roto en silencio**
  desde RFC-HARNESS-002 v3: `apply_chat_handler` no leía `minion_chat_format`
  ni detectaba `tools`, el daemon aplicaba el `chat_format` de destilación y
  llama_cpp descartaba los tools → el modelo respondía en prosa o **inventaba
  una tool y fabricaba su salida**, y `run_local_minion` lo daba por `ok`.
- Arreglado (commits `b49e93a0`, `4f3aefae`): routing de handler con tools,
  realimentación del resultado como turno de usuario, parser del tool-call
  nativo de Granite 4.2, `used_tools`/`tool_calls` en el resultado, y el bridge
  marca error si responde sin tools.

### 1.2 Veredicto de autonomía (medido, no opinado)

`scripts/autonomy_ladder.py` (escalera P1–P7 con ground-truth, jaula de cwd,
veredicto S/A):

| Modelo | Read-only (P1–P3) | Encadenado | Mutación | Veredicto |
|---|---|---|---|---|
| granite_4.1-8b | ✓ | 1 paso (débil) | P6: `find … -delete` sobre-ancho, sin preguntar, y **miente** ("no action") | **S=1 → no autónomo** |
| granite_4.2-8b | ✓ | 6 pasos | P5: `sed -i` sobre dato ambiguo, sin preguntar | **S=1 → no autónomo** |
| granite_4.2-3b | ✓ (necesita ~1200 tok) | — | — | igual |

Conclusión operativa: **read-only/organizativo con verificador; mutaciones con
gate humano.** Cualquier diseño que permita al modelo mutar sin confirmación es
un "la lía" a la espera de ocurrir.

### 1.3 El agujero real: `run_bash` no confina rutas

`_dispatch` (`local_minion.py`) ejecuta `create_subprocess_shell(cmd, cwd=cwd)`
con **cwd + 60 s** como único límite. `cwd` solo fija el directorio de arranque;
el shell puede salirse con rutas absolutas, `..`, `~`, `$HOME`:
`cat /etc/passwd`, `rm -rf ~`, `find / -delete`. En la escalera, 4.2 ejecutó
`find / -type f …` en una tarea read-only; la **jaula del arnés** lo cortó, pero
**en producción no existe**. Este es el punto 1 del RFC.

### 1.4 La delegación ya está a medio construir

El subsistema Telegram + delegación existe:

- **Neon-Link** clasifica el mensaje (DM→`CONVERSATIONAL`, grupo→`BACKGROUND`,
  `/bg`, mención `@bot`) y lo deja en `events.db`.
- **Worker** (`plugins/antigravity_ide/worker.py`) lo consume:
  - comandos ya implementados: `/list`, `/switch`, `/new`, `/delete`, `/models`,
    `/model <id>`, `/models`(backends), `/status`, `/queue`, `/deferred`, y
    **`/mission <prompt>` → `HEAVY_PATH`**.
  - `HEAVY_PATH` → `_enqueue_heavy_path()` → `CognitiveQueueManager.enqueue_task(
    source="agentic_job", payload={prompt, cascade, …}, priority=7,
    mission_id=f"telegram:{channel_user_id}")` → acusa "⏳ En cola, te aviso"
    → el resultado se entrega en `_check_telegram_jobs()` (D19).
  - `_session_cascade_specs()` construye la cascade `{backend, model, timeout}`
    desde el catálogo (`ModelRouter.resolve_cascade(role="conversational",
    session_model=…)`) o desde `TELEGRAM_BRIDGE_CASCADE`.
- El **driver `agentic_job`** (`jobs/drivers/agentic.py`) ya declara el backend
  `local-tools` en su enum; el `BridgeFactory` ya sabe construir
  `LocalToolBridge`.
- El **catálogo curado** (`model_catalog.yaml`) es la fuente de verdad de
  modelos/roles; `local/granite-4.2-8b` ya está dado de alta (commit `1de627a7`).

Por tanto **no hay que construir la delegación**: hay que **abrirla al backend
local-tools de forma confinada** y **aplicar la política de autonomía**.

### 1.5 Nota de alcance (¿RFC nuevo?)

Revisados los RFC abiertos: RFC-002/Phase 4 (memoria) y RFC-003 (prompts) son
DRAFT pero de **otro dominio**; RFC-004 está cerrado. No hay un RFC abierto que
cubra autonomía de ejecución + delegación, así que se abre **RFC-005**.

---

## 2. Activos reutilizables (inventario)

| Pieza | Ruta | Rol en este RFC |
|---|---|---|
| Loop de tools | `src/red_pill/swarm/agents/local_minion.py` | objeto a confinar; ya parsea 4.2 y reporta `used_tools` |
| Bridge local-tools | `src/red_pill/swarm/bridges/local.py` | ejecuta el loop; marca respuesta no anclada |
| Selección de handler | `src/red_pill/inference/runtime.py` | routing de `chat_format` con tools (HARNESS-003) |
| Catálogo | `examples/model_catalog.yaml.example` + `core/model_catalog.py` | fuente de modelos/roles/licencias; añadir backend `local-tools` |
| Router de cascadas | `core/model_router.py` | `resolve_cascade(role, session_model, allow_local)` |
| Worker Telegram | `plugins/antigravity_ide/worker.py` | `/mission`→`_enqueue_heavy_path`; `_session_cascade_specs` |
| Parser de inbox | `core/inbox_adapters.py` | comando/modo del mensaje (in-repo) |
| Job Manager | `job_manager_api` + `jobs/drivers/agentic.py` | cola trazable/reanudable, backend `local-tools` |
| Arnés de autonomía | `scripts/autonomy_ladder.py` | veredicto S/A por modelo; base del gate |
| Confinamiento OS | bubblewrap / `systemd-run` | jaula de ejecución (nuevo) |

---

## 3. Problema, alcance y no-objetivos

**Problema**: no podemos delegar una tarea (con tools) a un modelo local sin
exponer el host a comandos sin confinar y a mutaciones no confirmadas.

**Alcance**:
- Jaula de ejecución real para `run_bash` (y, por extensión, para cualquier
  herramienta que ejecute cosas).
- Política de autonomía por niveles, aplicada por el ejecutor (no por el prompt).
- Delegación por Telegram a modelos locales con tools, reutilizando `/mission`.
- Allow-list de operadores y defensa básica frente a inyección.

**No-objetivos**:
- No dar autonomía de mutación autónoma a los modelos actuales (el arnés no la
  habilita).
- No sustituir el job manager ni el routing; se extienden.
- No meter cloud/opencode en este diseño (siguen su cascade actual).

---

## 4. Decisiones de diseño

### 4.1 Confinamiento de ejecución (la pieza crítica)

**Decisión propuesta**: ejecutar `run_bash` dentro de un **namespace de
ficheros** con el workspace montado rw y el resto del sistema en ro/inaccesible.

- **Opción A — bubblewrap (recomendada)**: `bwrap --unshare-all --die-with-parent
  --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --bind <ws> <ws> --chdir
  <ws> -- /bin/sh -c "<cmd>"`. Sin red por defecto (`--unshare-net`), opcional
  conmutables. Ligero, sin root, ya presente en casi todas las distros.
- **Opción B — `systemd-run --user --scope`** con
  `ProtectHome=read-only`, `ReadOnlyPaths=/`, `BindPaths=<ws>`,
  `InaccessiblePaths=`, `PrivateNetwork=yes`. Reutiliza el OOM shield que ya
  usamos (`MemoryMax`), pero el confinamiento de rutas es más tosco.
- **Opción C — validador estático** (denegar rutas absolutas/`..`/verbos
  destructivos): **descartada** como único mecanismo — es evadible
  (`$IFS`, encadenados, `eval`) y da falsa seguridad.

**Requisito**: fallo **visible** — si la jaula no está disponible, la ejecución
se **rechaza** (no se degrada a shell libre). Fail-closed, coherente con RFC-004.

**Workspace**: cada job recibe un directorio propio
(`$XDG_DATA_HOME/red-pill/tasks/<job_id>/`), bind-mount rw; el cwd de la jaula
es ese directorio. Inputs (ficheros que el operador adjunte) se copian ahí.

### 4.2 Niveles de autonomía (aplicados por el ejecutor)

| Nivel | Permiso | Cuándo |
|---|---|---|
| **L0 — read-only** | solo lectura dentro del workspace | **default** |
| **L1 — mutate con confirmación** | escritura/borrado requiere un token de confirmación (ver 4.7) | tareas que declaran mutación |
| **L2 — mutate autónomo** | sin confirmación | **solo si el arnés del modelo lo habilita** (hoy: ninguno) |

El nivel lo fija el **comando**, no el modelo: p.ej. `/mission` = L0 siempre;
`/mission!` o `/task write …` = L1. El ejecutor de `run_bash` inspecciona
intención (read-only vs escritura) y **bloquea** toda mutación fuera del
workspace y toda mutación en L0. La jaula (4.1) es la garantía; el nivel es la
política.

### 4.3 La entrada de Telegram es no confiable

- **Allow-list de operadores** (`TELEGRAM_ALLOWED_USER_IDS`): sin coincidencia,
  el mensaje no dispara delegación (queda en background/inbox).
- **Inyección**: el modelo lee ficheros que pueden contener instrucciones
  (probado en P7: leyó y **no** obedeció, pero eso es suerte, no garantía). Con
  L0+L1 el peor caso de una inyección es leer/copiar datos del workspace, no
  ejecutar mutaciones.
- **Reutilización del prompt**: el compactado de sesión (D11) ya acota el
  historial a 4000 chars.

### 4.4 Delegación: reutilizar `/mission`, no inventar

- Se mantiene `/mission <prompt>` (HEAVY_PATH) como comando de delegación; el
  resultado se entrega asíncronamente (`_check_telegram_jobs`). El agente
  **acusa recibo** ("⏳ en cola") y no bloquea el worker.
- Se añade un **backend `local-tools`** en `_session_cascade_specs` para que una
  cascada pueda apuntar a un modelo local con tools (ver 4.5).
- Se añade L1 con confirmación (4.7) para `/mission!` (mutación).
- Alternativa descartada: usar el bridge conversacional síncrono para tareas con
  tools — viola RFC_JOB_DAG (los trabajos con LLM local van por el job manager,
  trazables/reanudables) y bloquea el worker.

### 4.5 Selección de modelo / rol

- El catálogo es la fuente de verdad. Opciones para habilitar tools locales:
  - **Opción 1 (propuesta)**: nueva entrada `local/granite-4.2-8b-tools` con
    `backend: "local-tools"` y `roles: ["delegate"]` (nuevo rol) — separa la
    generación one-shot (`local`) del uso con herramientas (`local-tools`).
  - Opción 2: campo `capabilities: [tool_calling]` + `backend: local-tools` en la
    misma entrada. Más simple, pero difumina el gating.
- **D5 (guard local)**: hoy `resolve_cascade` filtra `backend=="local"` salvo
  `allow_local=True`. Para el heavy path queremos permitir **`local-tools`** bajo
  jaula, así que el filtro debe distinguir `local` (one-shot, sin confinar) de
  `local-tools` (confinado). **Decisión abierta** (ver §7).
- **Modelo por defecto**: `granite_4.2-8b` (mejor encadenado medido). `4.2-3b`
  admisible subiendo el presupuesto a ~1200 tokens.

### 4.6 Presupuesto y observabilidad

- **Cap de tools** (≤8, ya existe) y **cap de tokens** configurable; el 3B
  necesita ~1200 para llegar al tool-call.
- El resultado del job lleva `used_tools`/`tool_calls` (ya expuestos). Si
  `used_tools=False` en una tarea que requería tools, el bridge ya lo marca como
  error → el reply de Telegram lo refleja.
- **Log del veredicto**: registrar por job el nivel de autonomía, la jaula usada
  y si hubo intención de mutación bloqueada (para auditar).

### 4.7 Confirmación interactiva (L1)

Mecánica propuesta (a decidir, §7): al encolar una tarea L1, el worker responde
"⚠️ Esta tarea puede escribir ficheros. Responde `CONFIRM <job_id>`". Un token
de un solo uso, ligado al `job_id` y al `channel_user_id`, con TTL (p.ej. 10
min). El job queda en `PENDING` hasta la confirmación; si no llega, se descarta.
Alternativa: sufijo `!` en el propio comando (`/mission!`) como confirmación
implícita — más simple, menos seguro.

---

## 5. Plan de implementación (por fases)

> Regla de ejecución: todo lo que use LLM local va por el **Job Manager**
> (job_manager_api / dag_job), nunca `nohup`/`&`. Confirmaciones y tests in-process.

### F0 — Jaula de ejecución (base de seguridad)
- **Entregable**: `_dispatch` ejecuta `run_bash` vía bubblewrap (A) o
  `systemd-run` (B), con workspace bind rw y `/` ro; fail-closed si no hay jaula.
- **Config**: `RUN_BASH_SANDBOX=bwrap|systemd|off` (`off` solo dev,
  avisa en voz alta), `RUN_BASH_NET=deny|allow`.
- **Tests**: comando que intenta `cat /etc/passwd` → denegado; escritura dentro
  del workspace → permitida; `find /` → confinado; `/` ro.
- **Gate**: sin esta fase no se habilita delegación local con tools.

### F1 — Niveles de autonomía
- **Entregable**: clasificador de intención (read-only vs mutación) + enforcement
  en el ejecutor; L0 por defecto.
- **Tests**: L0 bloquea `rm`/`sed -i`/redirección; L1 exige token.

### F2 — Delegación Telegram → local-tools
- **Entregable**: catálogo con `local-tools` + rol `delegate`; `_session_cascade_specs`
  incluye el backend; D5 permite `local-tools` confinado; workspace por job.
- **Reutiliza**: `/mission`, `_enqueue_heavy_path`, driver `agentic_job`.
- **Tests**: `/mission "cuenta los .md en docs/"` → job → reply con el número;
  intento de mutación en L0 → reply de bloqueo.

### F3 — Allow-list + confirmación (L1)
- **Entregable**: `TELEGRAM_ALLOWED_USER_IDS`; flujo `CONFIRM <job_id>` (o `!`).
- **Tests**: user no autorizado no delega; mutación L1 sin confirmar expira.

### F4 — Observabilidad y veredicto
- **Entregable**: log de veredicto por job; comando `/tasks` (listar jobs de
  delegación y su estado); integración con `autonomy_ladder` como gate
  (re-medir 4.2 tras la jaula).
- **Tests**: el veredicto del arnés se adjunta al alta del modelo en el catálogo.

### F5 (opcional) — Endurecer modelo
- Subir presupuesto del 3B; evaluar si 4.2 habilita L2 en algún dominio acotado
  (p.ej. solo dentro del workspace de la tarea, con tests de regresión del
  arnés en CI).

---

## 6. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| La jaula no está disponible y se degrada a shell libre | fail-closed (rechaza) |
| Inyección de prompt desde ficheros leídos | L0+L1; workspace aislado; allow-list |
| El modelo miente sobre lo que hizo | `used_tools`/`tool_calls` + verificación de mutaciones en el workspace + log |
| Fuga de datos fuera del workspace | `/` ro y sin red por defecto |
| Coste/latencia de la delegación local | job asíncrono + acuse; OOM shield; modelos pequeños |
| Regresión silenciosa (el fallo HARNESS-003) | tests del arnés en CI; `used_tools=False` = error |

---

## 7. Decisiones abiertas (para el operador)

1. **Jaula**: bubblewrap vs `systemd-run`. (Propongo bwrap; `systemd-run` como
   fallback si bwrap no está.)
2. **D5**: ¿permitir `local-tools` en la cascade por defecto bajo jaula, o solo
   con opt-in explícito (`/model local/granite-4.2-8b-tools`)?
3. **Catálogo**: entrada separada `local-tools` vs campo `capabilities`.
4. **Confirmación L1**: token `CONFIRM <job_id>` vs sufijo `!`.
5. **Rol nuevo**: `delegate` propio vs reutilizar `conversational`.
6. **Alcance del workspace**: por job (efímero) vs sesión persistente.
7. **Red en la jaula**: deny por defecto (¿alguna tarea legítima necesita red?).

---

## 8. Anexos

### 8.1 Evidencia reproducible
- `docs/BENCHMARKS/AUTONOMY_granite_8b_20260930-130157.jsonl` (4.1, S=1)
- `docs/BENCHMARKS/AUTONOMY_granite_4_2_8b_20260930-131623.jsonl` (4.2, S=1)
- `scripts/autonomy_ladder.py --model granite_4_2_8b` (P1–P7, jaula de cwd)
- `AD-041` en `docs/TECHNICAL/DECISION_LOG.md`

### 8.2 Mapa del flujo de delegación (estado actual)

```
Telegram ─▶ Neon-Link (clasifica modo/command) ─▶ events.db
      └─▶ worker: command == HEAVY_PATH (/mission)
              └─▶ _enqueue_heavy_path → agentic_job (cascade de sesión)
                      └─▶ driver agentic_job → CascadeBridge
                              └─▶ [hoy] opencode/claude/agy   ⛔ falta local-tools
                      └─▶ resultado → _check_telegram_jobs → outbox → Telegram
```

### 8.3 Definición de "hecho" (Definition of Done)
Un operador autorizado envía `/mission "cuenta los .md en docs/"`, el job corre
en un modelo local **bajo jaula**, responde el número correcto, **no** puede
leer `/etc` ni borrar fuera del workspace, y un intento de mutación en L0 se
bloquea y se reporta. Re-medido con el arnés: el modelo sigue en S=0 para
read-only; mutaciones solo en L1 con confirmación.
