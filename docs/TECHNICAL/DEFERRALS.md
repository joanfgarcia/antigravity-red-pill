# Aplazamientos — cuatro nombres, cuatro conductas

En este kernel hay **cuatro mecanismos que aplazan algo** y durante un tiempo
compartieron la misma palabra (`deferred`). No hacen lo mismo y no caducan igual,
así que confundirlos produce diagnósticos falsos. Esta es la tabla de verdad.

| Mecanismo | Nombre en código | Qué aplaza | Cuándo vuelve | ¿Caduca? |
|---|---|---|---|---|
| **Espera de re-síntesis** | `waiting` · `hubs_waiting` · `SW_HUB_SYNTH_WAIT_RETRY_DAYS` | el pago del LLM para un hub cuya entrada ya se rechazó N veces | cuando **caduca la ventana** (7 d) o cambia la entrada | **sí, con fecha** |
| **Techo de presupuesto** | `deferred_stage_ids` · `deferred_by_budget` | instancias de fan-out de un compuesto que agotó su techo de pared (F3) | el **ciclo siguiente**, y por delante (stale-first) | no: no hay fecha, hay siguiente noche |
| **Entorno no disponible** | `JobDeferred` (excepción) | el job entero | en cuanto la cola lo vuelve a coger | no: depende del entorno (VRAM, IDE, SIP) |
| **Entrega de mensajes** | `deferred` en `session/delivery.py` | la entrega de un aviso a un alma | en la siguiente pasada de entrega | no: depende de que haya cuerpo vivo |

## La que importa para los hubs: espera ≠ fallo

Una sesión **EN ESPERA** no es un hub roto. Es una sesión cuya entrada ya pagó
`SW_HUB_SYNTH_MAX_REJECTIONS` síntesis con el mismo `hub_input_hash`: el veredicto
no cambia si el input no cambia, así que no se vuelve a pagar. Pero una sesión
cerrada no cambia de entrada nunca, así que sin caducidad no se escribiría jamás
y su aviso no moriría nunca.

Por eso hay **dos canales separados**, y esto es contrato, no detalle:

| | dolor | espera |
|---|---|---|
| señal | `hub_synthesis_failed` | `hub_synthesis_waiting` |
| tipo | `pain` · `criticality=WARNING` | `info` · `criticality=INFO` |
| dice | cuántos hubs no se escribieron y **por qué** | cuántas sesiones esperan y **cuándo caduca la primera** |
| se entierra | cuando un ciclo no tiene fallos | cuando no queda nadie esperando |
| vuelve a hablar | cuando hay un fallo nuevo | cuando la espera **caduca y el intento vuelve a fallar** |

El ciclo de vida completo, sin ambigüedad:

1. Entrada rechazada N veces con el mismo hash → **EN ESPERA** (INFO, sin dolor).
2. Mientras la ventana corre: silencio de dolor. El INFO dice la fecha.
3. **Caduca** (o cambia la entrada) → **un** intento más.
4. Si escribe → hub, marcador limpio, el INFO se entierra.
5. Si vuelve a fallar → marcador re-fechado (**otra** ventana) y **WARNING**,
   porque es un fallo nuevo con evidencia nueva.

Consecuencia de coste: **una síntesis por ventana y sesión**. Ni cero para
siempre (la trampa que cerró la caducidad) ni una por noche (el re-pago que cerró
la compuerta).

`SW_HUB_SYNTH_WAIT_RETRY_DAYS=0` desactiva la caducidad (espera indefinida, la
conducta anterior a 2026-11-12). `SW_HUB_SYNTH_MAX_REJECTIONS=0` desactiva la
compuerta entera (reintento cada noche).

## Por qué el nombre importa

`deferred` ya nombraba la cola de entrega (`no_live_body`,
`no_injection_point`) y el fan-out cortado por presupuesto. Un aplazamiento de
**entrega** sí se entrega solo el día que toca; una **espera** de síntesis no se
ejecuta sola: recibe un intento cuando caduca y puede volver a esperar. Tres
conductas incompatibles bajo una palabra, y un operador (y una agente) leyendo
"deferred" en tres sitios con tres significados.

Regla: **el nombre dice la conducta**. `waiting` espera una fecha; `deferred`
(entrega) espera un cuerpo; `budget_exhausted` espera al ciclo siguiente.

## Dónde se ve

- Tablero: `hub_synthesis_failed` (WARNING) y `hub_synthesis_waiting` (INFO).
- Log del sueño: `[SLEEP ENGINE] Hubs: {'hubs_written': …, 'hubs_failed': …,
  'hubs_waiting': …}`.
- Log de la fase: `[HUBS] … en espera: entrada rechazada 2× sin cambios…` y
  `[HUBS] … en espera CADUCADA (… ≥ 7 d): un intento más`.
- Por sesión, sin abrir Qdrant a mano: `python scripts/hub_synth_state.py`
  (read-only). Da el veredicto de la compuerta —`open` / `waiting` /
  `expires_now` / `hub` / `stale`— con los días que faltan para el intento, así
  que una espera se lee como una fecha y no como un dolor mudo.

Implementación: `src/red_pill/metabolism/hub_synthesis.py`
(`_synthesize_one`, `_emit_hub_failure_signal`, `_emit_hub_waiting_signal`).
