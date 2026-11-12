# Presupuesto nocturno — cómo se acota la noche (NB-001)

Guía breve del mecanismo de cota y coste del ciclo nocturno (`chronicle → sleep`).
Los flags citados siguen RULE 4 (`CONVENTIONS.md`): uno por pieza, default `False`,
leídos en un punto. Apagados, el comportamiento es exactamente el de siempre.

## Cómo se acota la noche

Tres palancas independientes y reversibles:

1. **Reuso incremental por unidad** — distill (`MEMENTO_DISTILL_REUSE_ENABLED`, F2a)
   y annotate (`MEMENTO_ANNOTATE_REUSE_ENABLED`, F2b). La unidad es el **rango de
   mensajes** (`memento/NNN-mensajes-XXXX-YYYY.md`), clave `unit_key`. Un manifest
   persistente (`_meta.json`) guarda por unidad `content_hash` + `prompt_version`/
   `engine` (+ fragmentación en distill); se reusa lo intacto y solo se re-procesa lo
   nuevo o lo tocado. Una unidad `degraded` (prompt truncado en el fallback HTTP 500)
   **jamás** se reusa. La primera noche se **siembra** (adopta lo ya destilado con la
   firma vigente, D-NB-11).
2. **Techo de pared por compuesto** (`JOB_COMPOUND_DEADLINE_ENABLED`, F3).
   `control.deadline_minutes` (por compuesto, clamp `[0, 720]`) ancla un techo al
   **primer step del compuesto** y acota su fan-out: agotado, no se arrancan
   instancias nuevas. Solo fan-out — ver «Lo que el techo NO acota» abajo.
3. **Presupuesto por coste real por etapa** (`MEMENTO_NIGHT_COST_MODEL_ENABLED`, F5).
   La selección presupuesta en la **divisa de cada fase**: chars de work-unit en
   distill, unidades (splits) + notas esperadas en annotate. Conserva el tope de
   sesiones (`MEMENTO_AGENTIC_NIGHT_LIMIT`) y el anti-hambruna (la primera sesión
   entra siempre).

## Qué se difiere y qué no

- **Se difiere**: las instancias de **fan-out** pendientes de un compuesto cuyo techo
  se agotó. Se cierran con `JobDeferred("budget_exhausted")` y el contador
  `deferred_by_budget` se publica en el checkpoint (D-NB-13). Vuelven la noche
  siguiente por **stale-first** (D-NB-07).
- **NO se difiere nunca**: la **cola del sueño** (`thread`, `finalize`,
  `memento-reinforce`) ni ninguna etapa no-fanout. El techo solo corta fan-out
  (D-NB-02).
- **NO se corta a mitad de sesión**: la instancia en vuelo termina; solo se deja de
  arrancar las siguientes (D-NB-02).

## Lo que el techo NO acota (medido 2026-11-12)

`deadline_minutes` solo corta **fan-out** (D-NB-02). Un compuesto sin fan-out no
tiene cota efectiva, y ese es el caso del **sueño**: sus 16 etapas son comandos
atómicos, así que `sleep.yaml` declara 60 min y no los aplica nunca. No es un bug
del techo: es su contrato. El `60` se conserva para el día que el sueño tenga
fan-out (`deep_sleep`); mientras tanto, promesa sin mecanismo — y así queda
anotado en el yaml.

**No hace falta cota ahí.** Ciclo nocturno `4047324f` (primera noche con F0/F3
encendidos y medición completa):

| | pared | hojas | nota |
|---|---|---|---|
| Noche completa | **76.8 min** | 73 | 0 fallos, 0 diferidos |
| `chronicle` | **70.9 min** | 57 | 92 % de la noche · 74.6 s/hoja |
| `sleep` | **5.7 min** | 16 | consolidación 5.1 · refuerzo 0.3 |

Con 27 sesiones en el delta, la crónica cerró a las 08:20:55 contra un techo de
08:29:13: **8 min de margen, cero diferidos**. El techo aguanta ~34 sesiones; el
cuello de la noche es la crónica, y esa sí está acotada de verdad. El sueño no:
consolidó 331 sesiones (24 hubs escritos, 303 ya al día) en 5 min.

Consecuencia operativa: **no mires el sueño cuando la noche se estire**; mira el
delta de la crónica y el coste por hoja.

## Cómo leer `item_seconds` y `stage_seconds`

El `dag_job` funde telemetría aditiva de duración en su checkpoint (F0):

- **`stage_seconds`**: duración de **cada hoja ejecutada**, clave por `stage_path`
  (p. ej. `{"impl": 12.4, "smoke": 3.1}`). Cubre el árbol completo.
- **`item_seconds`**: duración de **cada instancia de fan-out** (hojas con `_item`
  presente), misma clave por `stage_path` (p. ej. `{"plant/plant-0": 30.1, …}`).
  Es un subconjunto de `stage_seconds` que aísla el coste **por sesión/item**.

Las fases del sueño por el camino one-shot (`perform_sleep_cycle`) dejan además
`durations` por fase en `sleep_phase_status.json`. Juntos calibran el techo y el
ETA: `stage_seconds` da el coste por etapa, `item_seconds` el coste por sesión
(la noche la dominan 1-2 sesiones gigantes, ~58 % medido).

Flags y presupuestos completos: `docs/ENV_REFERENCE.md` (sección «Cota y coste del
ciclo nocturno»). Decisiones: `docs/TECHNICAL/DECISION_LOG.md` (AD-118).
