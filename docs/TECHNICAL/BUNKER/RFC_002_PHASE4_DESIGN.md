# RFC-002 Enmienda — Fase 4: Curaduría dinámica, ascensos diferidos y tejido Memento-consciente

| Field | Value |
|---|---|
| **RFC** | 002 (enmienda) |
| **Title** | Fase 4 — Curaduría dinámica y ascensos diferidos |
| **Status** | DRAFT → **EN ROLLOUT** (diseño implementado; single-writer activado por piezas 2026-09-28; queda retirar la ingesta legacy y demoler). Estado real: §10. |
| **Author** | Joan García (Operator) / Aleth (Agent) |
| **Created** | 2026-09-14 |
| **Updated** | 2026-09-28 |
| **Related** | [RFC-002](./RFC_002_MEMENTO.md) §4.5 (agentic pass), §4.6 (curation gate), §6 (rollout), §5.1 (sources of truth), [RFC-004](./RFC_004_REALTIME_TAG_SIDECAR.md), `OPERATIONS/SINGLE_WRITER_ROLLOUT.md` |

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

### 2.3 Resiembra de las colecciones curadas (2026-09-14)

Qdrant `work_memories`/`social_memories` acumularon material estructural
(raw_parents, sequence_chunks, fragmentos, nodos crudos de refracción legacy):
solo ~16% de work_memories participa en el recall (5311 hubs + 29 normales de
33.508). La historia completa vive en Memento; la **resiembra** vacía las
colecciones y las re-puebla SOLO con engramas curados ascendidos.

**Validación previa (no se borra a ciegas)**: muestra de 60 refine → 60
ascendidos a una colección de prueba; replay de las 11 queries reales → **hit
rate 100%** (top_score medio 0.47) y resultados temáticamente relevantes.

`scripts/memento_reseed.py` (dry-run por defecto): verifica cobertura raw →
snapshot backup → drop+recreate work/social → ascenso estático (sig>=0.5).
Estimación dry-run: **~206 work + ~1769 social**. El refuerzo Memento-consciente
sigue ascendiendo en el sueño. La resiembra espera: fin de la redestilación en
curso + aprobación del operador.

### 2.4 Clasificación work/social por LLM en el refine (2026-09-14)

La heurística por tokens (R1) fue "una receta para el desastre": los resúmenes
técnicos perdían la densidad del código crudo y caían a `social` (89% del corpus).
El **curador LLM clasifica correctamente EN EL REFINE** (ratio `category_score`
0-1, 1=work; verificado: texto técnico → 0.8). El clasificador standalone es débil
con el LLM local (tiny_aya devuelve 0.0 siempre), así que el ascenso NO llama al
LLM: usa `category_score` del frontmatter (umbral `MEMENTO_CATEGORY_WORK_THRESHOLD`,
default 0.5 → ≥0.5 = work) con heurística R1 como fallback.

`scripts/memento_refine_rescore.py` re-refina SOLO los refine existentes (sin
re-destilar, mucho más barato) para dotarlos de `category_score` tras la
redestilación.

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

**Parametrización por modelo (2026-09-15)** — el tamaño de fragmento depende del
contexto del modelo servido:

| Modelo | n_ctx | `MEMENTO_FRAGMENT_MAX_CHARS` | Fragmento ≈ tokens |
|---|---|---|---|
| **Granite-4.1-8B** (distill/refine Memento) | 10240 | **8000** chars | ~2000-3200 → cabe holgado |
| tiny-aya-water (solo contexto largo) | 32768 | 12000 chars | ~3000-4800 |

El presupuesto del refine (`model_prompt_budget()`) también es **dinámico según
el modelo** (`engine_id`): granite → 6144 chars, aya → 28672. Un turno individual
gigante (una sola cabecera `## ts — role` con body enorme) se sub-particiona por
líneas con solape y la cabecera repetida (fix 2026-09-15, sesión b3f27f38 de 62K
chars → 9 fragmentos que caben en granite).

**Trazabilidad**: cada distill/refine guarda `engine` (modelo real servido) y
`prompt_version` (hash del prompt de la etapa) en el frontmatter; el registry
`agentic` guarda ambos + `distill_prompt_version`/`refine_prompt_version`.

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

0. **Distill fragmentado** (§5.4.1). ✅ **IMPLEMENTADO (2026-09-14)**
   Partición por turnos con solape (2 msgs,
   parametrizable), prompts por posición (apertura vs continuación con memoria
   emocional), marcado `fragment`/`fragments_total`/`fragment_of`, slugs
   `NNN-<slug>-fragmento-i-de-N.md`. `MEMENTO_FRAGMENT_OVERLAP_MESSAGES=2` y
   `MEMENTO_FRAGMENT_MAX_CHARS=12000` (presupuesto por fragmento).
   En `memento/agentic/` (`fragments.py`: `_split_messages`/`_fragment_messages`/`_render_fragment`;
   prompts `DISTILL_USER_OPENING`/`DISTILL_USER_CONTINUATION` en `prompts.py`).
1. **Refine multi-idea** (§5.4.2). ✅ **IMPLEMENTADO (2026-09-14)**
   `refine_multi()` que lee M fragments y extrae
   N ideas (JSON array), escribe `refine/NNN-<slug>.md` por idea con
   `fragment_ref`. Particionado en lotes si los fragments exceden
   (`_split_to_fit`). El 1:1 anterior queda obsoleto.
   En `memento/agentic/` (`prompts.py`: `REFINE_MULTI_SYSTEM`/`REFINE_MULTI_USER`;
   `refine.py`: `_extract_json_array`, `_format_fragments`, `_split_to_fit`, `_refine_multi`).
2. **`ascender()` — promoción refine → engrama curado.** ✅ **IMPLEMENTADO (2026-09-14)**
   Función que crea/upsert
   un engrama en `work_memories` **o `social_memories`** (según el tipo del
   contenido: work vs social) a partir de un `refine/*.md` (content = summary
   refinado, payload con `session_id`, `source_lines`, `significance`, `theme`,
   `emotion`, `intensity`, `cross_refs`, `origin: "memento"`). Idempotente
   (point id uuid5 por `session_id`+`source_lines`; upsert, no duplica).
   Sello `ascended`/`ascended_at`/`ascended_to`/`ascended_point_id` en el
   frontmatter del refine (in-place). Vive en
   `src/red_pill/memento/ascension.py`.
3. **`refine.polaroid_stability`** — ✅ **IMPLEMENTADO (2026-09-14)** campo nuevo en
   frontmatter de refine + registry
   (float, con `last_reinforced_at`). Escritura atómica (mismo patrón que el sello
   de significance §4.5.1). `reinforce_refine()` aplica decay temporal
   `S *= e^(-Δt/τ)` + `GAIN`, y si `S >= POLAROID_REVIVAL_GATE` asciende.
   `polaroid_decay()` maneja epoch/ISO/datetime nativo (YAML).
4. **`weave_memento_reinforcement()`** — ✅ **IMPLEMENTADO (2026-09-14)** el paso
   Memento-consciente del weaver
   (§4.2). Nuevo, no toca `weave_cross_axons`.
   Colecciona temas de engramas nuevos en `work_memories` (ventana
   `AXON_WINDOW_HOURS`), y para cada refine NO ascendido con afinidad de tema
   (`_temas_afines`: theme exacto o ≥3 tokens) aplica `reinforce_refine`
   (decay+GAIN) y asciende si supera el gate. Vive en `ascension.py`.
   **Integrado** como etapa `memento-reinforce` del sueño (`sleep.yaml`, tras
   `finalize`; wrapper `scripts/memento_reinforce.py`).
5. **Ascenso estático** — ✅ **IMPLEMENTADO (2026-09-14)** tras `memento-agentic`,
   promover refinados con
   `significance >= umbral` (reemplaza el gate de ingesta, §3.3).
   `ascend_by_threshold()` (en `ascension.py`), integrado en `run_agentic` al
   final del pase. **En sombra por defecto** (`MEMENTO_STATIC_ASCENSION_ENABLED`
   default false): solo cuenta cuántos ascenderían; el experimento (§6.9) lo
   flipea a true.
6. **`nightly.yaml`** — ✅ **IMPLEMENTADO (2026-09-14)** el mega-ciclo
   composición (§5.2) + `redpill-nightly.timer`
   (03:00). Retirar los timers individuales de sleep/chronicle (decisión §5.3,
   opción A confirmada). `configs/jobs/nightly.yaml` compone chronicle → sleep
   (`type: dag` + `recipe`, `on_fail: warn`). `schedule_pulse.py` actualizado
   (Linux/macOS/Windows): registra el nightly y retira los individuales.
   Timers systemd aplicados en el host.
7. **Config keys** — ✅ **IMPLEMENTADO (2026-09-14)**, ajustadas por el experimento:
   `POLAROID_REVIVAL_GATE=7.0` (era 5.0),
   `POLAROID_TAU=90`, `POLAROID_GAIN=0.5` (era 1.0),
   `MEMENTO_GATE_MIN_SIGNIFICANCE=0.5` (ya existía),
   `MEMENTO_STATIC_ASCENSION_ENABLED=false` (sombra),
   `MEMENTO_FRAGMENT_OVERLAP_MESSAGES=2`, `MEMENTO_FRAGMENT_MAX_CHARS=12000`,
   `MEMENTO_CURATED_IMPORTANCE_FACTOR=5.0` (curados erodan lento),
   `MEMENTO_CATEGORY_WORK_THRESHOLD=0.5` (ratio LLM del curador),
   `NIGHTLY_ENABLED=true`. Declaradas en `red_pill.config`.
8. **Purga de `archive_memories`** — ✅ **SCRIPT LISTO (2026-09-14)** (con **backup
   previo** del collection) +
   **eliminación de `chronicle_distill.py`/`chronicle_refine.py`** (hecho).
   `scripts/memento_purge_archive.py`: dry-run por defecto, `--apply` hace
   verificación de cobertura raw → snapshot backup → drop. Cobertura real
   verificada: 690/690 (100%). La purga efectiva espera la señal del operador
   (cutoff de seguridad).
9. **Experimento de calibración** — ✅ **EJECUTADO (2026-09-14)** (τ/GAIN/gate)
   en sombra sobre el corpus real
   (1962 refine no ascendidos, 12604 engramas, 30 ciclos). `scripts/memento_calibrate.py`.
   **Resultado**: los provisionales (τ=90d, GAIN=1.0, gate=5.0) SATURABAN
   (~95% ascenderían — el matching por ≥2 tokens era demasiado amplio).
   Ajustes aplicados:
   - Matching endurecido: theme exacto o **≥3 tokens** (era ≥2).
   - `POLAROID_GAIN: 1.0 → 0.5`, `POLAROID_REVIVAL_GATE: 5.0 → 7.0`
     (τ se mantiene 90d) → ~6% ascenderían (minoría sostenida).
   El gate sigue en sombra (`MEMENTO_STATIC_ASCENSION_ENABLED=false`).
10. **Query log / replay de recall** — ✅ **IMPLEMENTADO (2026-09-14)** — el corpus de
    `search_memory_research` sigue
    acumulándose; el umbral Q4 se confirma con el replay (RFC-002 §4.6).
    `scripts/memento_replay_recall.py` re-ejecuta las queries del log
    (`search_query_log.jsonl`) contra el corpus curado y mide hit rate, top_score
    y contribución de engramas ascendidos (`origin: memento`). Estado real: 11
    queries, 100% hit rate, 0 ascendidos (gate en sombra) → **sin evidencia aún
    para flipear el gate estático** — se espera el refuerzo acumulado o más
    queries antes del enforce.

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
1. **τ/GAIN/gate**: fijados provisionalmente y **ajustados por el experimento de
   calibración** (§6.9) → τ=90d, **GAIN=0.5**, **gate=7.0** (los provisionales
   GAIN=1.0/gate=5.0 saturaban el corpus real).
2. **`archive_memories`**: **backup previo** del collection y **después purga total**.
3. **Timers**: **Opción A** confirmada (§5.3) — un único `redpill-nightly.timer`;
   se retiran los individuales de sleep/chronicle.
4. **Los 98 `raw/` reconstruidos**: **destilado normal**, mismo patrón que los no
   reconstruidos. El destilado es ~idempotente (la esencia se mantiene si modelo y
   prompt no cambian; el LLM no garantiza byte-identidad, y no hace falta).
   `reconstructed` marca la fidelidad del *raw*, no excluye del pipeline.
5. **Clasificación work/social por LLM** (§2.4): el curador puntúa `category_score`
   (ratio 0-1) EN el refine; el ascenso lo consume con umbral
   `MEMENTO_CATEGORY_WORK_THRESHOLD` (0.5). El clasificador standalone es débil con
   el LLM local → no se usa on-the-fly; la heurística R1 queda como fallback.
6. **Los curados no se olvidan**: importance = significance × 5
   (`MEMENTO_CURATED_IMPORTANCE_FACTOR`) → α bayesiana alta → un engrama curado
   vive a 365 días vs ~60 de uno normal.
7. **No usar la refracción del `sanitize` en work/social** (incidente 2026-09-14):
   degradaba hubs y creaba nodos crudos que ensuciaban el recall. Guard
   estructural añadido: la refracción solo aplica a engramas `normal` legacy
   políglota (`USER:`/`ASSISTANT:`).
8. **`add_memory` ya NO fragmenta mecánicamente** (2026-09-14): `synaptic_split`
   cortaba por separadores sin criterio y producía `_is_fragment` excluidos del
   recall (ruido muerto). La fragmentación la hace la curaduría CON CRITERIO
   (LLM, distill fragmentado §5.4.1). El texto largo se guarda completo.
   Consecuencia: `core_directives` re-sembrada (3 engramas completos, inmunes,
   sin fragmentos) y `red_pill_checkpoints`/`soul_memories` (residuos legacy)
   limpiados.
9. **Backup obligatorio antes de purgar** `archive_memories` y de resembrar
   work/social: `memento_purge_archive.py` y `memento_reseed.py` abortan si el
   snapshot backup falla.

**Todas las preguntas del diseño resueltas.** Listo para integrar como §10 del
RFC-002 tras la implementación (o antes, como diseño aprobado).

---

## 9. Estado actual y pendientes (2026-09-14)

### 9.1 Implementado (todo el checklist §6 + extras)

| Pieza | Ubicación |
|---|---|
| `ascender()` (idempotente, sello, importance curado) | `src/red_pill/memento/ascension.py` |
| `polaroid_decay` / `reinforce_refine` (estabilidad temporal) | `ascension.py` |
| `weave_memento_reinforcement` (weaver Memento-consciente) | `ascension.py` + etapa `memento-reinforce` en `sleep.yaml` |
| `ascend_by_threshold` (ascenso estático, en sombra) | `ascension.py` + integrado en `run_agentic` |
| Distill fragmentado (§5.4.1) | `memento/agentic/` (`fragments.py`: `_split_messages`/`_fragment_messages`; prompts por posición en `prompts.py`) |
| Refine multi-idea + `category_score` (§5.4.2, §2.4) | `memento/agentic/` (`refine.py`: `refine_session`/`_refine_multi`) |
| `nightly.yaml` + timers (opción A) | `configs/jobs/nightly.yaml`, `schedule_pulse.py`, systemd |
| Config keys | `red_pill.config` (POLAROID_*, MEMENTO_*, NIGHTLY_ENABLED) |
| Purga de `archive_memories` (script listo) | `scripts/memento_purge_archive.py` |
| Calibración τ/GAIN/gate (experimento) | `scripts/memento_calibrate.py` |
| Replay de recall (umbral Q4) | `scripts/memento_replay_recall.py` |
| Re-refinado con `category_score` | `scripts/memento_refine_rescore.py` |
| Resiembra de work/social (script listo) | `scripts/memento_reseed.py` |
| Fix sanitize (guard estructural, incidente) | `memory.py` + `tests/test_biological_refraction.py` |

### 9.2 Pendiente (secuencia tras la redestilación `f6493c71`)

1. **Restaurar el daemon LLM a `granite_8b`** — `redpill-llm.service` está en
   `MINION_PROFILE=tiny_aya_water` (temporal, para la redestilación). Restaurar y
   reiniciar el servicio al terminar.
2. **Redestilación reanudable** (`configs/jobs/memento_redistill.yaml`,
   2026-09-15): el job `f6493c71` (single, 5h42) se colgó ~2h en una generación
   del LLM. El nuevo recipe es **pausable por sesión** (`--limit 5` + bounded por
   ronda via `--redistill-round 2026-09-14T16:58:00Z`), **reanudable sin repetir**
   (solo reprocesa las ~9 sesiones con `distilled_at` anterior a la ronda), y con
   **watchdog doble**: `max_step_minutes: 20` (systemd-run mata el cgroup si un
   step cuelga → JobStepTimeout) + `MEMENTO_LLM_TIMEOUT=180s` (timeout por
   llamada; 3 timeouts → deferral exit 77). El job quedó PAUSED* (316 de 386
   re-procesadas; ~377 con la ronda UTC correcta, 9 pendientes).
3. **Re-refinado con `category_score`**: `memento_refine_rescore.py --all` — dota
   a todos los refine de la clasificación LLM del curador (los actuales no la
   tienen). No re-destila (barato). **No correr mientras la redestilación esté en
   curso** (carrera de escritura sobre `refine/`).
4. **Resiembra de las colecciones curadas**: `memento_reseed.py --apply` —
   backup snapshot → drop+recreate `work_memories`/`social_memories` → ascenso
   estático (~1900 engramas con score del curador y erosión lenta). Validado en
   muestra (recall 100%). **Revisión del operador antes de `--apply`**.
5. **Purga de `archive_memories`**: `memento_purge_archive.py --apply` (backup
   previo; cobertura raw 100% verificada). Señal del operador (cutoff).
6. **Flipear el gate estático**: `MEMENTO_STATIC_ASCENSION_ENABLED=true` cuando el
   replay Q4 o el refuerzo acumulado den evidencia (hoy: 11 queries, 0 ascendidos).

### 9.3 Estado de las colecciones (datos del 2026-09-14)

- `work_memories`: 33.508 pts — solo **~5.340 (16%) es memoria curada real**
  (5311 hubs + 29 normales legítimos); el resto (83%) es material estructural
  (raw_parents, sequence_chunks, fragmentos) excluido del recall. Tras el
  incidente de `sanitize` se borraron ~1.580 nodos crudos de refracción.
- `social_memories`: 2.483 pts (intacta, ~97 participantes en recall).
- Memento: **690 sesiones con raw/ (100%)**, 2.030+ refine no ascendidos (la
  redestilación en curso los está regenerando).

---

*Diseño DRAFT 2026-09-14 (implementado; pendiente la secuencia de resiembra).
A integrar en RFC-002 como §10 tras revisión del operador.*
---

## 10. Estado de rollout, demolición y release (2026-09-28)

> Este apartado es la **fuente de verdad del estado**. La checklist de §6 queda
> como registro histórico de implementación (2026-09-14).

### 10.1 HECHO

| Pieza | Estado | Evidencia |
|---|---|---|
| Fase 4 core (§6.0–§6.7): fragmentación, refine multi-idea, `ascender()`, polaroid, weaver Memento-consciente, ascenso estático, `nightly.yaml` | ✅ implementado (2026-09-14) | §6; producción desde el reseed |
| Single-writer M0–M9 (captura, ascensión, dedup, hubs, hilo, ingesta retirada, situación, erosión, interactivos, observabilidad D26) | ✅ implementado | `CHANGELOG` 7.22.0; 50 tests `test_sw_*` |
| Activación por piezas (G1–G4 en `.env`) | ✅ ACTIVO 2026-09-28 | `OPERATIONS/SINGLE_WRITER_ROLLOUT.md` §6 |
| RFC-004 (sidecar UDS Laya + tag en captura + solera + aviso WEAK) | ✅ COMPLETE (P1–P4) | `RFC_004_REALTIME_TAG_SIDECAR.md` |
| Ascenso estático (`MEMENTO_STATIC_ASCENSION_ENABLED`) | ✅ ON | `.env` |

### 10.2 QUEDA (inmediato, en orden)

1. **Verificar tras el nightly** (03:00): `hub_coverage_pct > 0` en work/social,
   ascensión Memento fluyendo, hilo de Ariadna presente.
2. **Validar el punto de riesgo**: que `chronicle_sources/` (Memento) cubre
   **todos** los providers (opencode/claude_code/pi/antigravity). Si algún
   provider solo entraba por `staging`, no se puede retirar la ingesta.
3. **Encender `SW_INGEST_RETIRED`** (punto de no retorno operativo) una vez 1–2
   esté probado.
4. **Demolición + release** (§10.4–§10.5).

### 10.3 Semántica de `SW_INGEST_RETIRED` (5 puntos)

Retira la **ingesta legacy de material crudo → memoria curada** y el `staging`
que la alimentaba:

| # | Punto | Efecto con el flag ON |
|---|---|---|
| 1 | `phases/consolidation.py` | deja de drenar `interaction_memories`→`work/social` (sin distill/chunks/raw_parents); queda solo hub synthesis + hilo |
| 2 | `metabolism/ls_snatcher.py` | no snatchea trayectorias de LanguageServers |
| 3 | `metabolism/chronicle/claude_code_plugin.py` | no extrae JSONL de Claude Code a staging |
| 4 | `telegram/session.py::mark_for_deletion` | no copia a staging |
| 5 | `telegram/session.py::trigger_compaction` | no copia a staging |

**NO toca**: la captura a `interaction_memories` (`queue_worker`), el pipeline
Memento (chronicle→distill→refine/annotate→ascensión), hubs/hilo/erosión/
situación/tags. No borra datos. El buffer pasa a tener como único trimmador el
janitor TTL (`SW_PURGE_GATE_ENABLED`, ya ON).

### 10.4 Demolición (inventario de "obras")

Cuando 10.2.3 esté probado, un PR dedicado (no mezclado con features) elimina:

1. `consolidation.py`: rama drain/distill/staging + el `if retired` (queda hubs+hilo).
2. `ls_snatcher.py` + `chronicle/antigravity_plugin.py` (llamada) + **la clase
   `ClaudeCodeExtractorPlugin`** de `chronicle/claude_code_plugin.py` (los
   **helpers** ya viven en `utils/chronicle_render.py` — ver SHARD-01 resuelto).
3. `paths.get_staging_dir` + directorio `staging/` (+ `paths_to_wipe`/`migration_map`).
   **CORREGIDO (SHARD-10, 2026-09-28)**: `scripts/chronicle_extractor.py` (+`_ls`/`_aes`)
   NO se borra — es el **productor de Memento** para antigravity: escribe
   `unencrypted_conversations/` que consume `chronicle_sources/antigravity.py`
   (vivo, `redpill-extractor.timer`). Es distinto de `ls_snatcher.py` (ESE sí es
   la vía legacy a `staging/`).
4. `telegram/session.py`: `copy_to_staging` + sus dos ramas.
5. Flags sin consumidor (`SW_INGEST_RETIRED` y los de migración) + sus tests.

### 10.5 Release y migración

**Asimetría clave** (dos públicos):

- **Instalación nueva**: recibe el código **sin legacy y sin flags de
  migración**; Memento→ascensión→hubs es el único camino por defecto. **Cero
  ritual.** Seeds/`install_neo.sh` nacen limpios.
- **Actualización** (instalación con datos legacy): necesita un camino de
  migración **automático e idempotente**, no un runbook manual:
  `scripts/migrate_single_writer.py` (dry-run por defecto):
  1. Verifica que Memento cubre las sesiones de todos los providers (si falta
     alguna → **para** y avisa; no demoler con memoria sin archivar).
  2. **Absorb único** de lo que quede en `staging/` (archivar en Memento) antes de
     descartarlo.
  3. Trima el buffer `interaction_memories` (tope de edad).
  4. Marca estado "migrado" (no repetir).

- **Flags de feature, no de migración**: hubs/thread/situación/erosión/tags pasan
  a default ON o config — un recién llegado no debe "encender hubs".
- **Release**: bump **major** (cambio de comportamiento) + `docs/.../MIGRATION_SINGLE_WRITER.md`
  + sección "Upgrading" en el CHANGELOG.

**Secuencia de release**: observar (esta semana) → PR de demolición (quita legacy
+ flags de migración + añade migrador y doc) → release major. La activación de
G1–G4 es **banco de pruebas del operador**, no el entregable.

### 10.6 Hallazgos del scout (2026-09-28) — la demolición está BLOQUEADA

Scout (lentes architecture + consistency) sobre `src/` vs §10.3/§10.4 → **14
shards** en `.cell/shards.json` (reportes `.cell/reports/scout-architecture.json`
y `scout-consistency.json`). Veredicto: **NO demoler y NO encender
`SW_INGEST_RETIRED` todavía**; el inventario de §10.4 era optimista.

**Bloqueadores críticos (consent `operator`):**

| Shard | Qué | Por qué bloquea |
|---|---|---|
| SHARD-01 | `chronicle/claude_code_plugin.py` aloja **helpers compartidos** (`extract_user_content`, `extract_assistant_blocks`, `_render_tool_use/_result`) que consume Memento | §10.4.2 decía borrar el módulo entero → rompería la fuente Memento. Hay que mover los helpers a un módulo neutral y borrar solo la clase extractora |
| SHARD-10 | `scripts/chronicle_extractor.py` **es el productor real** de `unencrypted_conversations/` que consume `chronicle_sources/antigravity.py` (vivo, `redpill-extractor.timer` horario) | §10.4.3 lo daba por muerto con un "revisar qué queda". No lo está: hay que decidir si `chronicle_extractor_ls.py`/`_aes.py` se mantienen como productor de Memento |
| SHARD-02 | `get_staging_dir` tiene consumidores **fuera** del drenaje (`paths_to_wipe` en `memory.py:1342`, `migration_map.staging_buffer`) | Borrarlo sin quitar esos consumidores deja referencias colgando |

**Funcional bajo `SW_INGEST_RETIRED` (arreglar ANTES de encenderlo):**

| Shard | Qué | Efecto |
|---|---|---|
| SHARD-13 | `telegram/session.py::run_janitor_sweep` decide la purga por `metadata.source_buffer_id` del drenaje legacy | Con RETIRED ON, las sesiones Telegram `pending_purge` **nunca se purgarían** (acumulación). Hacer el predicado Memento-consciente (`telegram:<uuid>` en el registro) |
| SHARD-12 | `TelegramSessionManager.__init__` llama `get_staging_dir()` (no cubierto por §10.4.4) | Ampliar el inventario de Telegram (import + atributo `staging_dir`) |

**Correcciones al inventario §10.4 (medios):**
- **SHARD-03**: falta `rituals.py::consolidation_ritual` (Phase 0 'snatch' a staging), `scripts/trigger_pulse.py` y la config `CHRONICLE_*`.
- **SHARD-04/05**: enumerar flags de migración vs feature; añadir `MEMENTO_GATE_ENFORCED` (sin consumidor).
- **SHARD-06**: listar tests huérfanos (`tests/test_claude_code_plugin.py`; reescribir los de drain en `test_sleep_phases.py`/`test_sleep.py`).
- **SHARD-11**: docstrings de `consolidation.py` describen aún el pipeline legacy.

**Docs desactualizadas (bajos/medios):** SHARD-08
(`CHRONICLE_INGESTION_GUIDE.md`), SHARD-09 (`AGENT_UPDATE_GUIDE.md` +
`SERVICE_HEALTH_CONTRACT.md` citan timers retirados), SHARD-14
(`RFC_002_MEMENTO.md` cita `chronicle_daily.py` inexistente).

**Consecuencia para la secuencia:** el orden de §10.2 cambia — **antes** de
encender `SW_INGEST_RETIRED` hay que resolver SHARD-13 (purga Telegram) y
SHARD-10/01 (autonomía de las fuentes Memento). El resto son obras de demolición
sin riesgo funcional.

### 10.7 Resueltos post-scout (2026-09-28)

- **SHARD-13 CERRADO**: el janitor de Telegram (`session.py::_is_archived`) es
  Memento-consciente cuando `SW_INGEST_RETIRED` está ON, **acotado a la fuente
  `telegram`** (sin falsos positivos por UUIDs crudos repetidos en antigravity);
  fail-safe (no purga si no puede verificar) y el janitor ya no instancia
  `MemoryManager` en modo retirado. `MementoRegistry.is_rendered(sid, sources=)`
  nuevo. Tests `test_telegram_janitor_purge.py` + suite de Telegram hermética.
- **Deuda de hermetismo detectada**: `tests/test_sleep_phases.py::test_drain_cutoff…`
  asume el drenaje legacy y falla con `SW_INGEST_RETIRED=true` (pre-existente, no
  introducido por SHARD-13). Entra en SHARD-06 (tests huérfanos a reescribir).

**Pendiente para desbloquear RETIRED**: SHARD-10/01 (autonomía de las fuentes
Memento) y verificar la cobertura de `chronicle_sources/telegram.py` (existe y
está en `CHRONICLE_ARCHIVE_SOURCES`).

- **SHARD-01 CERRADO (2026-09-28)**: los helpers compartidos
  (`extract_user_content`, `extract_assistant_blocks`, `_render_tool_use`,
  `_render_tool_result`) se movieron de `metabolism/chronicle/claude_code_plugin.py`
  a **`src/red_pill/utils/chronicle_render.py`** (módulo neutral). Las fuentes de
  Memento (`chronicle_sources/{opencode,claude_code}.py`) ya NO importan del
  paquete legacy (guardarraíl de test); el plugin legacy los re-exporta
  (mismas funciones, sin duplicar). Ya se puede borrar la clase extractora sin
  romper Memento.
- **SHARD-10 CERRADO (2026-09-28)**: `scripts/chronicle_extractor*.py` es el
  **productor de Memento** (antigravity → `unencrypted_conversations/`), NO
  legacy; §10.4.3 corregido. Queda desbloqueado borrar `staging/` y
  `ls_snatcher` sin tocar el extractor.

### 10.8 Demolición por lotes (2026-09-28)

- **Lote 1 (docs/docstrings)**: SHARD-08/09/11/14 — `CHRONICLE_INGESTION_GUIDE`,
  `AGENT_UPDATE_GUIDE` §4.11, `SERVICE_HEALTH_CONTRACT`, `RFC_002_MEMENTO` §1.1,
  docstrings de `consolidation`/`phases`. ✅
- **Lote 2 (retiradas seguras)**: SHARD-12 (`TelegramSessionManager.copy_to_staging`
  + `staging_dir` + ramas), SHARD-03 (Phase 0 'snatch' de `consolidation_ritual`),
  SHARD-04/05 (`CHRONICLE_PLUGINS` y `MEMENTO_GATE_ENFORCED` sin consumidor;
  filas de `ENV_REFERENCE`). ✅
- **Lote 3 (destructivo)**: ✅ **COMPLETADO 2026-09-28**.
  - 3a: borrado `metabolism/chronicle/*` (base + claude_code + antigravity) y
    `ls_snatcher` (+ su test). Helpers en `utils/chronicle_render`.
  - 3b: `consolidation.py` reescrito a **hubs-only** (fuera el drenaje completo);
    eliminados/reescritos los tests del drenaje; `conftest` hermético a los flags.
  - 3c: fuera `get_staging_dir` y sus consumidores (`paths_to_wipe`/`migration_map`);
    queda `get_legacy_staging_dir` (solo lectura) para el migrador.
  - 3d: fuera `SW_INGEST_RETIRED` (y `MEMENTO_GATE_ENFORCED`/`CHRONICLE_PLUGINS`);
    el janitor de Telegram verifica Memento sin flag.
  - **Verificación**: suite completa **2205 passed** (con flags del `.env`), ruff
    limpio, Sound of Silence OK. Commits locales (sin push).
  - **Nota**: `scripts/chronicle_extractor*.py` se conserva — es el productor de
    Memento para antigravity (`unencrypted_conversations/`), NO legacy (SHARD-10).
