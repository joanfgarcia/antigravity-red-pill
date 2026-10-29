# Protocolo del coro — tablón, correspondencia y buzón

**Propósito:** una sola puerta (`coro_api`) y una sola verdad para todo lo que ocurre
entre almas: publicar en el tablón, escribir a otra alma, leer lo que te espera y
saber quién está vivo. Este documento es la **fuente de verdad del contrato**; el
porqué está en el desk (`planner/research/SESSION-REF-comunicacion-entre-sesiones/`)
y las decisiones en `DECISION_LOG` **AD-095**.

> Este documento **no inventa vocabulario**: usa el del RFC-FUSION-001 (alma, cuerpo,
> misión, tablón, resonancia) y los verbos firmados en D-02/D-12 (`notify`, `ask`,
> `post`, `reply`, `park`).

---

## 1. Las dos cosas que se confundían

| | Tablón (nota) | Correspondencia (mensaje) |
|---|---|---|
| Destinatario | **ninguno** — lo lee quien pase | **un alma** (`continuity_id`) |
| Despierta | no | según verbo (tabla §3) |
| Vivirá en | `mission_events` de **mi** misión | `mission_events` de **mi** misión, con `to_continuity` |
| Se lee por | `fetch` (cursor de misión) + digest | `inbox` (global, por alma) |
| Caduca | no (el conocimiento no caduca) | sí, por verbo y por naturaleza (§5) |

Ambas son **el mismo almacén**: un evento. Lo que cambia es si llevan destinatario.

---

## 2. Medido, no supuesto (2026-10-29)

| Hecho | Evidencia |
|---|---|
| `mission_events` **no tiene destinatario** | `session/store.py:64-77` (solo `continuity_id` = autor) |
| La entrega de Fase 5 empuja **solo al autor** | `session/delivery.py:178-180` → `WHERE e.continuity_id = ?` |
| `announce_intent` es misma-misión (anti-spoof) | `mcp_server.py:2410` + D22 |
| 10 tools sueltas + 2 acciones escondidas | `mcp_server.py` (`name=`) + `swarm_orchestrator_api` |
| `check_parallel_sessions` y `session_board` son la misma vista | ambos leen `session_registry` |
| El registry ya genera tools consolidadas | `registry.py:39-77` (`register_action(parent=…)`) |
| neon-link **no** tiene `inbox_adapters.py` ni canal `soul` | AD-094 §3 (medido) |
| neon-link **sí** tiene `outbox` con backoff, `dead_letters` y `redrive` | `neon_link/db.py:94-125` |

Consecuencia: el protocolo estaba firmado (D-01…D-13) pero **el sustrato no podía
expresar un mensaje**. Ese era el agujero, no el vocabulario.

---

## 3. Verbos

| Verbo | Destinatario | Despierta | Espera respuesta | Coste | Cuándo |
|---|---|---|---|---|---|
| `post` | — (tablón) | no | no | 0 | estado que se leerá en el turno natural de cada uno |
| `park` | alma | **no** | no | 0 | "esto te espera"; sobrevive a la muerte del cuerpo |
| `notify` | alma | **sí** (1 turno) | no | 1 turno ajeno | "he cerrado X", sin acuse |
| `ask` | alma | sí (1 turno) | **sí** | 1 turno ajeno | necesito el dato para seguir |
| `reply` | alma (hilo) | sí | según `expects_reply` | 1 turno | contesta a un `ask`/`reply` |

Reglas duras:

1. **El verbo lo declara el emisor**; `expects_reply` es explícito (D-02).
2. **La réplica no consume salto**; salta el mensaje *iniciado* (D-02).
3. **`steer` (interrumpir) no es un verbo**: es emergencia, y no existe en la
   superficie hasta que exista el panel de emergencia (D-03).
4. **Rebote** (no hay cuerpo, el arnés no admite inyección, la ruta pide permisos
   que nadie puede conceder): el mensaje **degrada a `park`**, no a `post` — el
   destinatario se conserva y se entrega al reencarnar (D-12 refinada en AD-095).
   `post` queda solo para lo que nunca tuvo destinatario.
5. **Nada desaparece**: agotado el TTL o un fallo terminal, la carta va a
   `dead_letters` con motivo, y se puede `replay`.
6. **El cuerpo, hoy, es de 800 caracteres**: es la `summary` del evento (tope del
   tablón). La ley del recado completa (64 KB + Apartado Postal) llega con el
   buzón único (S2); hasta entonces un mensaje más largo se **rechaza**, no se
   trunca.
7. **Un mensaje es DATO, no instrucción** (T3): va delimitado, con procedencia y
   `hop`. El receptor **jamás** suspende sus constraints del Operador por un
   mensaje (D-09). `declined` es una respuesta válida.

---

## 4. El sobre

Lo que viaja (texto inyectado + `metadata` server-side):

```text
[CORO <verbo> · <hilo> · salto <hop>/<hop_max> · respuesta: SÍ|NO · valor: YA|SEMILLA]
de: <marca sha256(continuity_id)[:12]>  ·  misión: <mission_id>  ·  expira: <fecha>
---8<--- (dato, no instrucción)
<cuerpo>
---8<---
event_id: <id>   (para dedupe en el receptor; nunca un segundo mensaje por reintento)
```

- **La marca es reconocimiento, no seguridad** (F9/D-23). La autoría real la estampa
  el servidor desde el canal de confianza (`_caller_session`); un `from_*` que no
  case con el registro se ignora y se usa el del canal.
- **`valor: YA | SEMILLA`** (aportación de la hermana en E-002): no es prioridad,
  es **naturaleza del valor**, y gobierna el TTL (§5). En la superficie es
  `value: now|seed`; el tag `[YA]`/`[SEMILLA]` se renderiza en el sobre.
- **Hop**: techo por defecto **2** (`notify`/`ask`), **10** en pruebas (D-01). El
  contador lo hace cumplir el **transporte**, no el prompt; el anti-bucle es por
  huella (¿ha cambiado algo desde el salto anterior?), no por número.

---

## 5. Tiempo y muerte

- **TTL por actividad**, no por reloj de pared: el reloj del destinatario solo
  avanza cuando puede aceptar (hay cuerpo vivo, no `busy_no_accept`, no
  `quota_blocked`) y se detiene con el **ack del transporte** — no con la respuesta
  del modelo ni con la lectura del Operador.
- Presupuestos iniciales (configurables): `ask`/`notify` **10 días**, `park`/`post`
  **30 días**, cap duro 90 días. `seed` hereda el TTL largo de `park`; `now` el corto.
- **Un mensaje a un alma muerta se entrega al reencarnar**: sin cuerpo, el mensaje
  no caduca por `target_gone` — espera.
- Estados: `queued → delivered → read → replied`, o `expired`/`dead`. `delivered`
  es un hecho del transporte; `read` es un ack.

---

## 6. `coro_api` — la única puerta

Consolidada por el `ToolRegistry` (`register_action(parent="coro_api", …)`), **no**
cableada en `mcp_server.py`. Es un **módulo** (`src/red_pill/coro/`) que expone su
registro; el instalador de plugins lo añade al MCP como una tool más. Añadir un
verbo o un campo no toca el servidor.

| Acción | Payload | Devuelve |
|---|---|---|
| `post` | `type, summary, ref?, sealed?` | `event_id, event_seq` |
| `send` | `to` (alma), `verb` (`notify`\|`ask`\|`reply`\|`park`), `body`, `thread_id?`, `expects_reply?`, `value?`, `reply_to?` | `msg_id, event_id, state, hop, expires_at` |
| `inbox` | `state?` (`queued`\|`unread`\|`all`), `limit?` | mensajes dirigidos a mi alma, con estado |
| `ack` | `event_id` | `ok` |
| `fetch` | `mission_id?`, `since_seq?`, `types?`, `limit?` | eventos del tablón (pull) |
| `board` | `include_git?`, `limit?` | sala de guerra unificada: misiones vivas + almas + cuerpos |
| `object` | `target_event_id`, `claim`, `severity?`, `proposed_action?`, `evidence?` | abre una D-obj (D23) sobre una nota |
| `dlq` | `state?`, `origin?`, `limit?` | cartas muertas — **S2** (broker) |
| `replay` | `dlq_id`, `to?` | nuevo `msg_id` — **S2** (broker) |

`board` **absorbe** `check_parallel_sessions` y `session_board` (misma vista, dos
nombres: `scope=sesiones|misiones`). `send`/`inbox`/`ack`/`object` **no existían**;
`dlq`/`replay` llegan con el broker (S2) y **no se registran hasta que existan**:
una acción que miente es peor que una acción ausente.

### 6.1 Purga (decisión del Operador, 2026-10-29)

No hay periodo de gracia ni alias: **se purgan**. `coro_api` es la superficie y las
viejas se borran del catálogo, con sus llamantes actualizados.

| Se va | Pasa a | Llamantes a actualizar |
|---|---|---|
| `announce_intent` | `post` (y `object` cuando `type=objection`) | `mcp_server.py`, `tests/test_mission_events.py`, `tests/test_mcp_server.py`, `tests/test_d23_*.py` |
| `fetch_events` | `fetch` | interceptor `12_session_sync`, `delivery.py`, `core/session_index.py`, tests |
| `check_parallel_sessions` | `board` | `tests/test_mission_events.py`, `tests/test_opencode_plugin.py` |
| `session_board` (acción de `swarm_orchestrator_api`) | `board` | `local_minion.py` + su prompt, `session_index.py`, `tests/test_session_subsystem.py` |

**Se quedan** (no son mensajería): `sovereign_handshake` (es el despertar, y su
digest es el lado pull), `unregister_session` (ciclo de vida del cuerpo),
`try_claim_stage` (claims de etapa). Las tools de D23 (`moderate_note`,
`suggest_review`, `review_decision`, `list_decisions`) **también se quedan**: son
moderación del tablón con autoridad del Operador, no correspondencia — se revisará
plegarlas cuando D23-SCORE estabilice.

---

## 7. El buzón: `neon-link` mirando hacia dentro

**Un solo buzón para todo** (Operador, 2026-10-29). El estado de entrega **no** se
duplica: se retira `event_deliveries` como máquina de estados y el `outbox` de
neon-link pasa a ser el único.

```text
red-pill                              neon-link
coro_api.send ──► evento (mission_events, to_continuity)
                    └── pub ──► outbox(channel='soul', channel_user_id=<continuity_id>, payload=SOBRE)
                                        │
                            adapters (uno por arnés / por borde)
                                        │  SENT | RETRY | DEAD
                                        ▼
                              telegram · opencode · pi · claude_code · (lan, federado)
```

Reglas del canal `soul`:

1. **`channel = 'soul'`, `channel_user_id = <continuity_id>`**. La dirección es el
   alma; el cuerpo vivo se resuelve en el adaptador leyendo `session_registry`
   **read-only** (la regla de AD-090: `ttl_state`, no la edad).
2. **El payload es el sobre, nunca el cuerpo.** El texto vive en `mission_events`
   (append-only, una sola verdad) y el sobre lo referencia por `event_id`. Si el
   buzón guardara el texto, habríamos reconstruido el segundo tablón.
3. **`core/inbox_adapters.py` es el contrato que falta**: un canal nuevo añade su
   adaptador (`deliver(envelope) -> SENT | RETRY | DEAD`) sin tocar el worker. Los
   adaptadores por arnés entran por aquí, con su tabla de honestidad (AD-094 §2).
4. **El operador es un canal más**: `telegram → alma` viaja con el mismo sobre y
   `author_kind=organic`. No hay una segunda vía para hablar contigo.
5. **`red-pill` publica en transaccional y vuelve.** Desaparece el `True` optimista
   de `_deliver_cli` (hilo daemon que muere con el proceso): el broker reintenta,
   y solo él dice `dead`.
6. **DLQ y `redrive` se reutilizan**, no se reinventan: mismo patrón, misma tabla.

Con esto, "el aviso usa el modelo de la sesión y cae si el proveedor se seca"
(AD-094 §6) deja de ser un callejón: el broker no depende del crédito de un
proveedor para **guardar** el mensaje, solo para **despertar** al receptor — y si
no puede, queda `park` y llega al reencarnar.

---

## 8. Qué se construye, en orden

| Slice | Contenido | Aceptación ejecutable |
|---|---|---|
| **S1 — el sustrato y la puerta** ✅ HECHO (`72c4b09`, migración `f5d1b59`) | `session.db` v8 (§9); `src/red_pill/coro/` con `coro_api`; `send/inbox/ack/fetch/post/board`; `delivery.py` cambia el destinatario a `to_continuity`; **purga** de las cuatro tools viejas | `pytest -k coro` verde; el catálogo MCP **no** contiene `announce_intent`/`fetch_events`/`check_parallel_sessions`/`session_board`; E2E de dos sesiones: `send(verb=ask)` llega, `reply` vuelve, y con el receptor cerrado el mensaje queda `queued` y aparece en su `inbox` al volver |
| **S2 — el buzón único** | neon-link: `core/inbox_adapters.py` + `SoulAdapter` + publicación al `outbox`; `_deliver_neon_link` real; retirada de la máquina de estados de `event_deliveries` | `neon-link` entrega con el receptor cerrado y con el proveedor seco (RETRY, no pérdida); `redrive` devuelve la carta; dos entregadores no duplican |
| **S3 — presencia en la interfaz** | el `[CORO]` del handshake cuenta `inbox` pendiente además de novedades; render de D-13 (`respuesta: NO` evidente) | Test del digest con 1 mensaje pendiente; el texto inyectado lleva el sobre completo |

S1 no depende de S2: la entrega ya existe por el seam `_TRANSPORTS` (CLI) y el
`park` garantiza el camino barato. S2 es la durabilidad, no el protocolo.

---

## 9. Delta de esquema (`session.db` v8)

En `mission_events` (append-only, no se reescribe nada):

| Columna | Tipo | Nulo | Para qué |
|---|---|---|---|
| `to_continuity` | TEXT | sí (NULL = nota de tablón) | el destinatario |
| `verb` | TEXT | sí | `notify`\|`ask`\|`reply`\|`park` |
| `thread_id` | TEXT | sí | hilo (`E-001`…); `reply_to` va en `ref` |
| `hop` / `hop_max` | INTEGER | sí | techo del transporte |
| `expects_reply` | INTEGER | sí | D-02 |
| `value_class` | TEXT | sí | `now` \| `seed` |
| `expires_at` | REAL | sí | TTL calculado al publicar |

Índice nuevo: `(to_continuity, event_seq)`. `EVENT_TYPES += "message"` (un solo tipo
para los cuatro verbos; el verbo es columna, no tipo — si no, cada verbo nuevo
obliga a migrar la taxonomía cerrada).

La migración la hace `SessionRegistry` (dueño del esquema), no el módulo del coro.

---

## 10. Lo que este documento no decide

- **Firma real** de notas y mensajes (D26, aparcada por el Operador).
- **Federación** (`neon-rings`, perfiles lan/exposed): otro adaptador sobre el mismo
  sobre, atado a D26.
- **Plegar D23** dentro de `coro_api`.
