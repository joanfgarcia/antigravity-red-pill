# Ciclo de vida de las señales — el dolor nace con su entierro

Regla única: **toda señal de DOLOR se emite con su camino de entierro**. Si no
puede morir cuando la causa cesa, no es un aviso: es una mentira que se queda en
el tablero y que alguien tendrá que investigar más tarde sin motivo.

## El caso que la motivó (medido 2026-11-12)

De las nueve señales que emiten los plugins del Janitor, **ocho no tenían
entierro**. Consecuencia real, no teórica: `memento_stale_distill` saltó a las
08:00 con 16 sesiones; la noche las destiló todas; la señal siguió viva en el
buzón y nadie podía cerrarla. Ese dolor huérfano es lo que hace que un despertar
autónomo «encuentre» trabajo: el tablero le miente y él va a comprobarlo.

Las muted estaban peor: `MinionInbox` no tenía API de entierro. Un dolor
silenciado no se podía cerrar **de ninguna forma**.

## Tres clases de señal, tres ciclos

| clase | qué es | `signal_type` | entierro |
|---|---|---|---|
| **estado** | hay N colgados, la cobertura está baja, el espejo creció | `"pain"` | `bury_signal(name)` → `evaporate_signals` |
| **estado silenciado** | lo mismo, pero no al tablero sino al buzón | `"pain"` + `muted=True` | `bury_signal(name, muted=True)` → `MinionInbox.resolve_report("signal_<name>")` |
| **instantánea** | foto del estado actual (métricas de salud) | `"status"` / `"info"` | ninguna: se reinyecta en cada pase y se sobrescribe por nombre |

**Estado vs evento**: un estado se entierra cuando cesa (`else: bury_signal`). Un
evento que ya ocurrió no es un estado — y si se emite como `pain` persistente,
miente en el siguiente pase (caso `interaction_unrendered_purged`: se modeló como
estado —«¿está el chronicle perdiendo turnos?»— precisamente para poder enterrarlo).

## Cómo se escribe bien

```python
if problema:
	mem.inject_signal(name="mi_estado", intensity=4.0, signal_type="pain", source="Janitor", message="…")
else:
	bury_signal("mi_estado", memory_manager=mem)   # o muted=True si va al buzón
```

Detalle que muerde: el `else` va del `if`, **nunca del `try`**. Un `else` colgado
de un `try/except` se ejecuta cuando la inyección *no lanzó*, o sea enterraría el
dolor recién alzado. Está fijado con test (`test_janitor_signal_burial.py`).

## El guard

`tests/test_signal_lifecycle_contract.py` recorre el paquete con `ast` y **falla**
si una señal `pain` no tiene su entierro:

- tablero → exige `evaporate_signals(name)` o `bury_signal(name)`;
- silenciada → exige `resolve_report(name)`/`resolve_report("signal_<name>")` o `bury_signal(name, muted=True)`;
- `status`/`info` → exentos (instantáneas).

No es una revisión de estilo: es lo que impide que el defecto **nazca** en el
siguiente plugin. Antes de esto, cada emisor nuevo copiaba el patrón roto y el
error aparecía una noche después, en forma de «el despertar encontró algo».

Límite conocido: un nombre construido con f-string no se resuelve
estáticamente; el contrato lo ignora (no lo exime) y esos emisores se siguen
leyendo a mano.

## Qué NO es este contrato

- No dice que un dolor deba ser efímero: mientras la causa exista, el aviso debe
  estar. Solo exige que **sepa morir**.
- No cubre la caducidad por tiempo (eso es otra pieza: `SW_HUB_SYNTH_WAIT_RETRY_DAYS`
  y los dolores con acantilado de `signal_profiles`).
- No sustituye al acuse (`ACK_*`, AD-108): acuse y entierro son cosas distintas —
  el acuse dice «lo he visto», el entierro dice «ya no existe».

Implementación: `swarm/agents/janitor_plugins/base.py::bury_signal` y
`core/inbox.py::MinionInbox.resolve_report`.
