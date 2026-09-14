# RFC-002 Enmienda — Fase 4: Curaduría dinámica, ascensos diferidos y tejido Memento-consciente

| Field | Value |
|---|---|
| **RFC** | 002 (enmienda) |
| **Title** | Fase 4 — Curaduría dinámica y ascensos diferidos |
| **Status** | DRAFT (diseño, pre-revisión del operador) |
| **Author** | Joan García (Operator) / Aleth (Agent) |
| **Created** | 2026-09-14 |
| **Related** | [RFC-002](./RFC_002_MEMENTO.md) §4.5 (agentic pass), §4.6 (curation gate), §6 (rollout), §5.1 (sources of truth) |

---

## 0. Resumen ejecutivo

La Fase 4 cierra el ciclo de la memoria: **Memento es el archivo, Qdrant es la
memoria curada**. El gate de curación deja de ser en sombra y pasa a enforce, con
una novedad que este diseño introduce y que el RFC-002 §4.6 ya preveía pero dejó
sin mecanismo: el **ascenso diferido por refuerzo** — un fragmento refinado que
hoy no merece subir a Qdrant puede subir más adelante si su tema reaparece. Para
ello el hilo de Ariadna (axon-weaver) se hace **Memento-consciente**: teje entre
colecciones *teniendo en cuenta* Memento, no solo Qdrant↔Qdrant.

Este documento NO modifica el cuerpo del RFC-002: es la especificación de la
Fase 4 para su revisión, y al aprobarse se integra como sección en el RFC.

---

## 1. Contexto y decisiones ya tomadas (2026-09-10/14)

Antes del diseño, lo ya decidido y ejecutado:

1. **El chronicle ya no toca Qdrant.** `chronicle_daily.py` retiró las fases
   legacy (discover/ingest/finalize + `chronicle_distill`/`chronicle_refine`).
   Hoy el chronicle (dag_job `chronicle-daily`) corre **solo** `memento` (render
   delta) + `memento-agentic` (distill→refine). **Qdrant no se escribe desde el
   chronicle**: el archivo es Memento en disco.
2. **`chronicle_distill.py` y `chronicle_refine.py` están desconectados** (0
   referencias en src/scripts/configs). Su destino es la eliminación.
3. **`archive_memories` ya no es fuente de reconstrucción**: el árbol Memento
   tiene **690/690 sesiones con `raw/` (100%)** — 592 nativos + 98 reconstruidos
   (marcados `reconstructed: true`). Nada depende de archive_memories para
   regenerarse; su destino es la purga (tras el cutoff de seguridad).
4. **`raw/` reconstruido**: `scripts/memento_rebuild_raw.py` regeneró los `raw/`
   faltantes desde `index.md`, marcados como reconstruidos (no verbatim exacto).
5. **Destilado casi completo**: 672/690 sesiones destiladas; quedan ~17
   (antigravity_export 15 + antigravity 2).

**Consecuencia**: la Fase 4 ya no necesita "gatear la ingesta a archive_memories"
(esa vía está muerta). El gate ahora decide **qué asciende de Memento a Qdrant
como engrama curado**.

---

## 2. Cambio de paradigma: de "gate de ingesta" a "ascenso curado"

### 2.1 Lo que cambia

| Antes (RFC-002 §4.6) | Ahora (Fase 4) |
|---|---|
| El chronicle ingesta TODO a `archive_memories` y el gate decide qué queda | El chronicle NO ingesta a Qdrant; Memento es el archivo completo |
| Gate = filtro de lo que entra | Gate = promotor de lo que asciende (de Memento a Qdrant) |
| `archive_memories` = sumidero | `archive_memories` = se purga; Qdrant curado vive en `work_memories`/`social_memories` |
| Refuerzo ("referenced by later sessions") sin mecanismo | Refuerzo = ascenso diferido con estabilidad temporal (este diseño) |

### 2.2 Las colecciones tras la Fase 4

- **`work_memories`** — memoria de trabajo consolidada por el sueño + los engramas
  curados ascendidos desde Memento.
- **`social_memories`** — la memoria relacional/afectiva, ya alimentada por el sueño.
- **`interaction_memories`** — buffer TTL de 72h (sin cambios, RFC-002 §4.4).
- **`archive_memories`** — **se purga** tras verificar que la reconstrucción
  funciona desde `raw/` (100% cobertura). Solo queda como fallback documental
  durante el cutoff de seguridad.

---

## 3. El ascenso diferido por refuerzo (núcleo del diseño)

### 3.1 El problema

Un `refine/<NNN>-<slug>.md` con `significance` por debajo del umbral (p.ej. 0.4
con gate en 0.5) **no asciende** a Qdrant. Hoy eso es definitivo: el fragmento
queda solo en Memento para siempre. Pero su tema puede reaparecer en semanas —
una idea que hoy es tangencial puede volverse central si el operador sigue
trabajando en ello. El RFC-002 §4.6 lo prevé ("referenced by later sessions
(reinforcement)") pero lo dejó sin implementar por falta de *reference tracking*.

### 3.2 La solución: estabilidad temporal por refuerzo (no un contador)

Cada `refine/*.md` lleva una **estabilidad de refuerzo** (`polaroid_stability`),
modelada tipo FSRS: no cuenta "cuántas veces reapareció el tema", mide la
**tracción sostenida** ponderando el tiempo entre ocurrencias y la recencia.

**Por qué NO un contador plano**: 3 menciones en una semana NO deben revivir un
refinado que llevaba 1.5 años sin aparecer — la estabilidad de ese refinado decayó
a casi cero durante el silencio, y 3 picos recientes no la recuperan. En cambio,
un tema mencionado mensualmente durante un año sí acumula estabilidad. Esto
filtra el falso positivo del "pico de una semana" (caso del operador, 2026-09-14).

**Modelo** (análogo a `drive_evaluator`, half-life):

```
estabilidad S; decae entre refuerzos; cada refuerzo la sube:

  entre ocurrencias:  S *= e^(-Δt / τ)          # Δt = tiempo desde el último refuerzo
  en cada refuerzo:   S += GAIN                 # GAIN = incremento por reaparición

  ascenso:            S >= POLAROID_REVIVAL_GATE
```

- **`τ` (tau)**: constante de decaimiento. Propuesta `τ = 90 días` (un tema
  silenciado ~3 meses pierde la mayor parte de su estabilidad). Calibrable.
- **`GAIN`**: incremento por reaparición. Propuesta `GAIN = 1.0` por evento.
- **`POLAROID_REVIVAL_GATE`**: umbral de ascenso. Con τ=90d y GAIN=1.0, un tema
  mencionado semanalmente durante un trimestre acumula estabilidad > umbral;
  un pico de 3 en una semana tras 1.5 años de silencio queda lejos del umbral.
- **Reset por descarte explícito**: si el operador marca un refine como
  "no relevante" (o el washout lo elimina de candidatos), su estabilidad se
  pone a 0 y deja de competir.

**Dónde vive la estabilidad**: frontmatter del `refine/*.md` (campo
`polaroid_stability`, float) y espejado en `memento_registry.json`. Memento sigue
siendo la fuente de verdad; Qdrant solo recibe el engrama ascendido. El `mtime`
del refine no cuenta (la escritura del frontmatter lo alteraría); se usan los
timestamps de los eventos de refuerzo registrados en el registry.

**Firma del mecanismo**:

```
Cada refine tiene: significance, theme, cross_refs, polaroid_stability, last_reinforced_at

Evento de refuerzo (noche, en el weaver Memento-consciente):
  nuevo_engrama.ver tema T
  for refine in refinados_no_ascendidos:
      if temas_afines(refine.theme, T):        # matching de theme + cross_refs
          refine.decay_stability(τ)            # S *= e^(-(now - last)/τ)
          refine.polaroid_stability += GAIN
          refine.last_reinforced_at = now
          if refine.polaroid_stability >= POLAROID_REVIVAL_GATE:
              ascender(refine)                  # → engrama curado en work_memories
```

**Decisiones de diseño**:
- **`temas_afines`**: matching exacto de `theme` (snake_case) o de los `keywords`
  del distill; el cruce con `cross_refs` (sesiones relacionadas) cuenta como
  refuerzo adicional.
- **No re-evalúa significance**: el ascenso por refuerzo NO re-destila — el
  contenido ya está refinado; solo cambia su estado de promoción. (Si más tarde
  el refinado original cambia, la invalidación §4.5.1 ya regenera distill/refine.)
- **Idempotente**: `ascender()` es un upsert con `session_id`/`source_lines` como
  clave — re-promover el mismo refine no duplica.
- **Calibración empírica**: τ, GAIN y el umbral se ajustan con el shadow-report
  (cuántos ascienden / cuántos quedan) antes de que el gate sea estricto.

### 3.3 El ascenso por umbral (criterio estático)

Complementa al refuerzo. Tras la fase `memento-agentic`, todo `refine` con
`significance >= MEMENTO_GATE_MIN_SIGNIFICANCE` asciende. Este es el gate
"estático" del RFC-002 §4.6, ahora sin `archive_memories`.

### 3.4 El ascenso por operador

`significance` marcada por el operador (un `refine` tocado a mano, o un engrama
favorito) asciende de inmediato. Es la vía deliberada del "álbum de fotos".

---

## 4. El hilo de Ariadna Memento-consciente

### 4.1 El weaver hoy (sin cambios en la mecánica)

`AxonWeaverPhase` (ADR-AXON-001) teje `social_memories` → `work_memories` con
ventana temporal (`AXON_WINDOW_HOURS`) y score `W = α·sim + (1-α)·temporal`.
Es CPU-only y corre en el sueño (fase 3). **No consulta Memento.**

### 4.2 La ampliación: tejer teniendo en cuenta Memento

La Fase 4 añade un **paso de refuerzo** al weaver (nuevo, sin tocar la mecánica
existente):

```
weave_cross_axons()              # lo de siempre, social↔work
weave_memento_reinforcement()    # NUEVO: Memento-consciente
    # 1. Coleccionar temas de engramas nuevos en work_memories (ventana reciente)
    # 2. Para cada refine NO ascendido (polaroid_stability < gate):
    #      - temas_afines(refine.theme, tema_engrama) → decay + GAIN
    #      - si polaroid_stability >= POLAROID_REVIVAL_GATE → ascender(refine)
    # 3. Guardar estabilidad en el frontmatter + registry
```

**Por qué "teniendo en cuenta Memento" y no "entre colecciones y Memento"**:
el weaver no crea axones hacia Memento (Memento no es un nodo de Qdrant); usa
Memento como **fuente de candidatos a promoción**. Los axones siguen siendo
Qdrant↔Qdrant; Memento alimenta la *decisión* de qué ascender. Es exactamente la
distinción que planteaste — y es la correcta: Memento es el archivo, no un nodo.

### 4.3 Frecuencia

El refuerzo corre **en el sueño** (noche) sobre la ventana reciente — no en
tiempo real. El ascenso estático y el de operador corren tras `memento-agentic`
(en el chronicle). Así: el chronicle produce refinados → el sueño refuerza y
asciende.

---

## 5. El mega-ciclo nocturno: chronicle → sleep (secuencial, sin stop)

### 5.1 El problema de orden

Hoy: sleep (03:00, prio 8) → chronicle (04:00, prio 7). El sueño consolida
**antes** de que el chronicle produzca refinados → los refinados de hoy no entran
en la consolidación de esta noche. Para la Fase 4 el orden correcto es:

```
chronicle (produce refinados, y el ascenso estático/de operador) → sleep (consolida, teje, refuerza, poda, asciende por refuerzo)
```

### 5.2 El mecanismo: composición por referencia (`type: dag`)

El driver `dag_job` ya soporta `type: dag` con `recipe` (RFC_JOB_DAG §4.5): una
etapa incrusta OTRA receta dag_job como compound, expandida en el submit, con
`depends_on` y `on_fail` por etapa. Se define un **`nightly.yaml`** que compone:

```yaml
source: dag_job
priority: 8
title: Ciclo nocturno (chronicle → sleep)
mission_id: nightly-cycle
nightly_exempt: true
manifest:
  workdir: .
  stages:
    - id: chronicle
      type: dag
      recipe: chronicle        # memento + memento-agentic
      on_fail: warn            # si falla → log + señal, NO bloquea
    - id: sleep
      type: dag
      recipe: sleep            # 3 rituales + 10 fases + thread + finalize
      on_fail: warn
      depends_on: [chronicle]
```

**Semántica**: `on_fail: warn` en ambos — si el chronicle falla, el sueño corre
igual (consolida lo existente, poda, teje); si el sueño falla, no hay nada que
frenar. El runner serializa (sigue siendo secuencial); `job_pause`/`resume`
operan en la frontera de etapa aplanada (p.ej. `chronicle/memento-agentic`).

**Timers — decisión pendiente (ver §5.3).** Los recipes `sleep.yaml` y
`chronicle.yaml` siguen existiendo como unidades ejecutables; el nightly los
compone. La pregunta es qué hacer con los timers individuales.

### 5.3 Los timers: individuales vs nightly único

**Situación actual** (dos timers independientes):

```
redpill-sleep.timer     (03:00) → redpill-sleep.service     → job submit --recipe sleep.yaml --singleton
redpill-chronicle.timer (04:00) → redpill-chronicle.service → job submit --recipe chronicle.yaml --singleton
```

Cada timer dispara un servicio `oneshot` que **encola** un job (no lo ejecuta —
el runner `redpill-queue.timer` lo recoge). El flag `--singleton` evita encolar
un duplicado del MISMO recipe.

**El problema con el nightly + individuales a la vez**: si añadimos
`redpill-nightly.timer` (que encola `nightly.yaml`, el cual compone chronicle →
sleep) y **mantenemos** los individuales, los procesos se ejecutan **DOS VECES**:

- El `--singleton` no protege: el sleep dentro del nightly es una **etapa
  aplanada**, no un job `source=sleep`, así que el singleton de `sleep.yaml` no
  lo ve → el timer individual de sleep encolaría OTRO sleep.
- Lo mismo con el chronicle a las 04:00.

Es decir, mantener ambos no es "respaldo": es **duplicación de trabajo** (dos
consolidaciones, dos destilados) cada noche.

**Opciones:**

| Opción | Qué implica | Veredicto |
|---|---|---|
| **A. Solo nightly** | Retirar `redpill-sleep.timer` y `redpill-chronicle.timer`; `redpill-nightly.timer` (03:00) encola el nightly. Los recipes individuales quedan en disco para ejecución **manual** (`job submit --recipe sleep`) cuando haga falta. | **Recomendada** |
| **B. Individuales en orden inverso** | Mantener los dos timers pero intercambiar horas (chronicle 03:00, sleep 04:00). Sin nightly. | Funciona, pero no da un solo job pausable/reanudable y duplica la lógica de orden en los timers |
| **C. Nightly + individuales** | Ambos activos. | **Malo**: duplica la ejecución nocturna |

**¿Qué aportan los timers individuales como "respaldo"?** Nada real: no son
alternativas al nightly (que los *contiene*), sino el mismo trabajo. Un "respaldo"
solo tendría sentido si fueran mutuamente excluyentes (si el nightly corrió, los
individuales no) — eso añade lógica de exclusión sin valor. Para ejecutar UNO
solo (p.ej. solo el chronicle porque hay sesiones nuevas y no quieres el sueño
completo) se usa el **submit manual** del recipe, que no necesita timer.

**Decisión (operador, 2026-09-14): Opción A.** Un único `redpill-nightly.timer`
(03:00) que dispara el nightly; se **retiran** `redpill-sleep.timer` y
`redpill-chronicle.timer`. Los recipes `sleep.yaml` y `chronicle.yaml` se
conservan como unidades manuales (y como componentes del nightly). El sueño y el
chronicle dejan de ser "pulsos" independientes y pasan a ser **fases de un ciclo
nocturno único**, coherente con la filosofía del DAG.

**Nota sobre `--singleton`**: al ser un solo job nightly, el `--singleton` sigue
protegiendo contra relanzamientos duplicados del nightly (reboot, doble timer).

---

## 5.4 Distill fragmentado y refine multi-idea (rediseño del pase agéntico)

**Motivación (2026-09-14)**: las sesiones largas (las más valiosas) exceden la
ventana del LLM. Hoy el transporte las recorta (pierde el final) — inaceptable.
Además, `refine_session` es **1:1** (1 distill → 1 refine), pero una sesión con
100 ideas debería producir 100 refine, y 3 destills que forman una sola idea
deberían producir 1.

### 5.4.1 Distill fragmentado (map-reduce con solape y memoria emocional)

Cuando un work unit (split o index) excede el presupuesto de contexto:

1. **Partición por turnos con solape** — se parsean los mensajes (`## ts — role`)
   y se agrupan en N fragmentos que quepan, con **solape de 2 mensajes** entre
   fragmentos (el último mensaje se repite al inicio del siguiente). Así los
   límites no cortan el diálogo a medias. Solape **parametrizable**
   (`MEMENTO_FRAGMENT_OVERLAP_MESSAGES`, default 2) — marcado en el código para
   poder cambiarlo.
2. **Prompts distintos por posición**:
   - Fragmento 1 (apertura): "distill this OPENING section, capturing decisions,
     insights, and the emotional tone that sets the session."
   - Fragmento i>1 (continuación): "the previous fragment distilled to:
     `<summary_anterior>`. Continue, keeping narrative and EMOTIONAL continuity."
     → el resumen anterior se inyecta como contexto, **transmitiendo la emoción**.
3. **Marcado de parte** en el frontmatter del distill:
   `fragment: i`, `fragments_total: N`, `fragment_of: <NNN>` (el work unit).
4. **Slugs**: `NNN-<slug>-fragmento-i-de-N.md` (orden visible en Obsidian).

### 5.4.2 Refine multi-idea (N ideas de M destills)

Refine lee **todos los fragmentos de un work unit** (M ficheros) y extrae
**N ideas variables** (0 a N, sin número fijo — lo decide el LLM):

```
for work_unit (grupo de fragmentos 001-fragmento-1-de-N ... N):
    ideas = refine_multi(transport, fragments=[{title, summary} x M], candidates)
    # ideas = [{title, significance, emotion, intensity, theme, relics, cross_refs, fragment_ref}]
    for idea in ideas:
        if idea.significance >= MEMENTO_REFINE_MIN_SIGNIFICANCE:
            escribir refine/NNN-<slug>.md   # UNO POR IDEA, no por fragmento
```

- **Prompt**: devuelve un **JSON ARRAY** de ideas (puede ser vacío). Cada idea
  lleva `fragment_ref` (de qué distill vino).
- **Ventaja**: 2-3 destills que forman una idea → 1 refine (no 3 redundantes);
  1 destill con 100 ideas → 100 refine. Granularidad del LLM, no del fichero.
- **Contexto**: si los M fragments exceden la ventana, se particionan en lotes
  (map-reduce también en refine) o el reintento adaptativo del transporte los
  recorta. Decisión de implementación: **particionar en lotes** para no perder.

### 5.4.3 El 500 por contexto (raíz)

El reintento adaptativo de `http_transport` (recortar y reintentar) es la red de
seguridad inmediata. La solución de fondo es el distill fragmentado de §5.4.1:
los fragmentos se dimensionan para caber, sin recortar contenido.

---

## 6. Lo que queda por implementar (checklist Fase 4)

0. **Distill fragmentado** (§5.4.1): partición por turnos con solape (2 msgs,
   parametrizable), prompts por posición (apertura vs continuación con memoria
   emocional), marcado `fragment`/`fragments_total`/`fragment_of`, slugs
   `NNN-<slug>-fragmento-i-de-N.md`. `MEMENTO_FRAGMENT_OVERLAP_MESSAGES=2`.
1. **Refine multi-idea** (§5.4.2): `refine_multi()` que lee M fragments y extrae
   N ideas (JSON array), escribe `refine/NNN-<slug>.md` por idea con
   `fragment_ref`. Particionado en lotes si los fragments exceden.
2. **`ascender()` — promoción refine → engrama curado.** Función que crea/upsert
   un engrama en `work_memories` **o `social_memories`** (según el tipo del
   contenido: work vs social) a partir de un `refine/*.md` (content = summary
refinado, payload con `session_id`, `source_lines`, `significance`, `theme`,
   `emotion`, `intensity`, `cross_refs`, `origin: "memento"`). Idempotente.
3. **`refine.polaroid_stability`** — campo nuevo en frontmatter de refine + registry
   (float, con `last_reinforced_at`). Escritura atómica (mismo patrón que el sello
   de significance §4.5.1).
4. **`weave_memento_reinforcement()`** — el paso Memento-consciente del weaver
   (§4.2). Nuevo, no toca `weave_cross_axons`.
5. **Ascenso estático** — tras `memento-agentic`, promover refinados con
   `significance >= umbral` (reemplaza el gate de ingesta, §3.3).
6. **`nightly.yaml`** — el mega-ciclo composición (§5.2) + `redpill-nightly.timer`
   (03:00). Retirar los timers individuales de sleep/chronicle (decisión §5.3,
   opción A recomendada).
7. **Config keys** (provisionales, a ajustar con el experimento): `POLAROID_REVIVAL_GATE`
   (umbral de estabilidad), `POLAROID_TAU` (decaimiento, días), `POLAROID_GAIN`
   (incremento por refuerzo), `MEMENTO_GATE_MIN_SIGNIFICANCE` (ya existe,
   provisional), `NIGHTLY_ENABLED`, `MEMENTO_FRAGMENT_OVERLAP_MESSAGES=2`.
8. **Purga de `archive_memories`** (con **backup previo** del collection) +
   **eliminación de `chronicle_distill.py` / `chronicle_refine.py`** (tras cutoff
   de seguridad).
9. **Experimento de calibración** (τ/GAIN/gate): antes de enforce, correr el
   refuerzo en sombra sobre el corpus real y medir cuántos ascenderían con cada
   combinación. Fija los provisionales; el experimento los ajusta.
10. **Query log / replay de recall** — el corpus de `search_memory_research` sigue
    acumulándose; el umbral Q4 se confirma con el replay (RFC-002 §4.6). La Fase 4
    NO flipea el gate "estático" a ciegas: espera el replay O el refuerzo
    acumulado, lo que llegue primero con evidencia.

---

## 7. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Ascenso por refuerzo sube ruido (temas vagos reaparecen) | `POLAROID_REVIVAL_GATE` + matching de theme/keywords (no sim libre); la estabilidad temporal filtra picos recientes; shadow-report mide |
| `work_memories` crece con engramas Memento | Ya tiene erosión/washout (lentitud revisada 2026-09-14: curados deben erodear más lento) |
| Re-promoción duplica | `ascender()` idempotente por session_id+source_lines |
| Purga de archive_memories pierde algo | 100% cobertura raw + cutoff de seguridad (backup antes de purgar) |
| El mega-ciclo falla y no hay respaldo | Timers individuales de respaldo (sleep/chronicle) se mantienen |
| Estabilidad mal calibrada (τ/GAIN/gate) | Calibración empírica con shadow-report antes de enforce |

---

## 8. Decisiones y preguntas

**Resueltas (operador, 2026-09-14):**
1. **τ/GAIN/gate**: fijar como **provisionales** (τ=90d, GAIN=1.0) y **ajustar con
   un experimento** de calibración (§6.8) antes de enforce.
2. **`archive_memories`**: **backup previo** del collection y **después purga total**.
3. **Timers**: **Opción A** confirmada (§5.3) — un único `redpill-nightly.timer`;
   se retiran los individuales de sleep/chronicle.
4. **Los 98 `raw/` reconstruidos**: **destilado normal**, mismo patrón que los no
   reconstruidos. El destilado es ~idempotente (la esencia se mantiene si modelo y
   prompt no cambian; el LLM no garantiza byte-identidad, y no hace falta).
   `reconstructed` marca la fidelidad del *raw*, no excluye del pipeline.

**Todas las preguntas del diseño resueltas.** Listo para integrar como §10 del
RFC-002 tras la implementación (o antes, como diseño aprobado).

---

*Diseño DRAFT 2026-09-14. A integrar en RFC-002 como §10 tras revisión del operador.*