# Admisión de modelos por carril — distill y annotate

> Puerta de entrada para un modelo (o una versión nueva) que quiera ser **candidato**
> a un carril del sueño/Memento. No es la admisión del banco de Dokimé
> (`BENCH_ADMISSION.md`) ni la de minions (`capability_bench.py`): aquí se decide
> si un modelo puede **producir memoria** en `distill` o `annotate` sin degradarla.
>
> Regla de oro: **se evalúa con el tamaño de unidad que el carril usa de verdad**,
> a su contexto de producción y en GPU. Un modelo que solo pasa con fragmentos de
> juguete no entra.

## 1. El contrato común

Un candidato a cualquiera de los dos carriles debe:

1. **Estar declarado como perfil** en `model_profiles.yaml` con `kv_cache`,
   `vram_footprint` y `hardware_affinity` (sin esos datos no hay plan de VRAM ni
   se puede calcular la exigencia de contexto).
2. **Correr en GPU, sin fallback a CPU**: `device_fallback: ["gpu"]` y `mode: gpu`
   en `/status`. La CPU no es un carril de producción para memoria: cambia la
   latencia del ciclo y rompe las comparaciones.
3. **Pensar apagado** (`thinking: off`) si el carril declara `thinking: off` en
   `task_profiles.yaml`, con los flags del perfil en `extra_server_args`
   (`--reasoning off --reasoning-budget 0`). Un modelo que gasta el presupuesto
   pensando devuelve `content` vacío y no es admisible.
4. **Sellar el motor**: la respuesta debe traer el modelo servido (`served_engine`)
   para que `distill/_meta.json` y el registry no mientan.

## 2. La regla de contexto (la que faltaba)

El tamaño de unidad no puede ser una constante del código sin mirar el modelo.
Para cada carril:

> **Caber no es destilar bien.** Que el modelo cargue a `n_ctx` no dice nada de
> la calidad a ese contexto: atención más diluida, KV más larga y más ruido
> pueden empeorar las notas aunque no haya un solo truncado. Por eso la
> admisión tiene **dos** puertas obligatorias: (a) cabe, y (b) **produce memoria
> de calidad a ese contexto**, medida con unidades reales del carril. Aprobar
> (a) sin (b) no es admisión.

```text
n_ctx_min = ceil(chars_unidad_max / ratio) + max_tokens_salida + 512
```

- `chars_unidad_max`: el tamaño máximo de unidad que el carril le pasa al modelo
  **de verdad** (no el de un fixture).
- `ratio`: **2,5 chars/token** como ratio de planificación (conservador; medido
  3,0 en K2 el 2026-11-27). Si el modelo tokeniza peor, el margen lo cubre.
- `512`: system prompt, plantilla de chat y holgura.

### Qué exige cada carril hoy

| Carril | Unidad máxima real | Salida | `n_ctx_min` | Estado |
|---|---:|---:|---:|---|
| `distill` | 8.000 chars (`MEMENTO_FRAGMENT_MAX_CHARS`) | 2.048 | **5.760 → 6.144** | Cumple el titular (K2 distill a 24.576; Granite a 10.240) |
| `annotate` **troceado (vigente, AD-146)** | 8.000 chars (`MEMENTO_ANNOTATE_CHUNK_CHARS`) | 4.096 | **6.144** | **K2 a 10.240 cumple y está medido** (§5): 29 notas en el p99, 0 errores |
| `annotate` **sin trocear (alternativa)** | 24.107 chars (p99 real) | 4.096 | **12.800** | **No basta con caber**: K2 a 16.384 no completa el p99 (timeout >180 s) |

> Consecuencia escrita: `annotate` trocea en partes similares de ≤8.000 (no
> 8000+1000). La alternativa de subir el contexto no está prohibida por la
> fórmula, pero **sí por la medición**: caber no es destilar bien, y a 16.384 el
> p99 real no termina dentro del watchdog. Cualquier candidato nuevo se evalúa
> contra la opción vigente y con la tabla A/B de §2.

> **Y en ambos casos hay que medir la calidad al contexto elegido.** Subir el
> `n_ctx` de K2 a 16.384 se midió el 2026-11-27 y **no sirve** para el p99 (ver
> §5): no basta con que la unidad quepa. Trocear a 8.000 también se midió: el
> p99 produce 29 notas, 0 errores y las mismas ideas que el split entero en
> p50/p90, sin la duplicación work→social que inflaba el conteo del split entero.

### Cómo se mide «produce memoria de calidad a ese contexto»

No basta con una corrida ni con un fixture corto. Protocolo mínimo:

1. **Unidades reales del carril**, no sintéticas: la p50, la p90 y la **p99**
   (por chars) de una sesión representativa, con el mismo prompt y sampling que
   producción.
2. **Dos contextos, mismo modelo**: el vigente (A) y el candidato (B). N=3
   repeticiones por unidad (el muestreo no es determinista: se comparan
   medianas, no una pasada).
3. **Métricas por unidad**:
   - contrato: JSON cerrado y válido, `finish_reason≠length` (0 truncados);
   - cobertura: nº de ideas/notas y qué tramos del fragmento cubren;
   - separación work/social y voz en 1ª persona, sin deixis;
   - fidelidad: ninguna nota introduce un hecho que no esté en la unidad
     (0 invenciones en la muestra revisada).
4. **Criterio**: B no puede caer por debajo de A en ninguna métrica; un empate
   con menos coste se acepta, una caída exige justificación y visto bueno del
   Operador. Una muestra de 5 notas se revisa a mano (las heurísticas no ven la
   invención sutil).
5. **Registro**: la tabla A/B va en la ficha del modelo con el veredicto. Sin
   esa tabla, «subimos el contexto» no es una admisión, es un cambio de fe.

## 3. Requisitos por carril

### `distill` (polaroids del sueño)

| Requisito | Umbral | Cómo se mide |
|---|---|---|
| **Cabe** | `n_ctx_efectivo ≥ 6.144` con unidad de 8.000 chars | `scripts/kv_ceiling.py --profile <p>` + la fórmula §2 |
| Memoria | Carga **GPU-only** al `n_ctx` del carril; `vram_footprint` declarado | `/status` (`mode: gpu`) y `kv_ceiling` (presupuesto) |
| Contrato | 100 % de unidades producen secciones con título y cuerpo; **0 truncadas** en el peor caso | Corrida completa sobre la sesión de peor caso (p99 de chars) |
| Voz | 1ª persona sostenida, español, sin deixis («brindo contigo») ni invención | `scripts/distiller_fidelity.py` + revisión de textura |
| **Calidad @ contexto de producción** | Medida con la unidad real **al `n_ctx` del carril** (A/B, N=3): **sin regresión** frente al titular; 0 invenciones en la muestra revisada | Protocolo §2 + `distiller_fidelity.py`/`distiller_bakeoff.py` |
| Latencia | La sesión peor caso cabe en el techo del carril (45 min) y ≤ 2× ms/char del titular (2,6 ms/char en 2.5) | `stage_seconds`/`item_seconds` del dag_job |

### `annotate` (notas desde el raw)

| Requisito | Umbral | Cómo se mide |
|---|---|---|
| **Cabe** | `n_ctx_efectivo ≥` el de la opción vigente (§2): 6.144 si se trocea a 8.000, 12.800 si no | Fórmula §2 + `kv_ceiling` |
| Memoria | Igual que distill (GPU-only, footprint declarado) | `/status` + `kv_ceiling` |
| Contrato | Array JSON válido y **cerrado**; 0 truncados (`finish_reason=length`) en el fixture | `scripts/bench_annotate.py --repetitions 3` |
| Cobertura | 2 llamadas por split (work + social), o 1 si el modelo soporta el prompt combinado | `bench_annotate` (`extract_por_fragmento`) |
| **Calidad @ contexto de producción** | Medida con unidades reales (p50/p90/p99) **al `n_ctx` del carril** (A/B, N=3): notas en 1ª persona, work/social separados, sin deixis, **sin regresión** frente a A/K2 y 0 invenciones en la muestra | Protocolo §2 + `bench_annotate` + revisión manual de 5 notas |
| Latencia | La sesión peor caso cabe en el techo del carril (40 min) | `item_seconds` del dag_job |

### `titles` (título de una nota, AD-148)

Carril corto y separable: recibe el **texto autocontenido de la nota** y devuelve
un título ≤80 chars. No lee el raw ni el destilado; no extrae hechos.

| Requisito | Umbral | Cómo se mide |
|---|---|---|
| **Cabe** | `n_ctx ≥ 8.192` para 24 notas/batch (24×600 chars ≈ 4,3k tokens + salida) | `kv_ceiling` + fórmula §2 |
| Memoria | GPU-only; **≤ ~3 GB de pesos** para no competir con el juez de annotate | `/status` + `kv_ceiling` |
| Contrato | 24/24 notas del batch con título; JSON cerrado; 0 inválidos | lote real de 24 |
| Fidelidad | el título sale del texto; **0 títulos de ejemplo del prompt**, 0 inventados, 0 repetidos entre notas distintas | revisión manual + heurística |
| Voz | español, ≤80 chars, sin “me pide/cuenta…”, sin “Conversación sobre” | heurística sobre el lote |
| Latencia | sesión media (~100 notas) ≤ 15 min; sesión grande (935) ≤ 10 min | `item_seconds` del dag_job |

**Baseline medido (2026-11-27, 24 notas reales, batch 12)**:

| Modelo | Válidos | s/batch | 935 notas | Nota |
|---|---:|---:|---:|---|
| **Bonsai 2-9B** | 24/24 | 5,8 | 7,5 min | Elegido (`titles`) |
| tiny-aya-water | 24/24 | 3,9 | 5,1 min | Alternativa; europeas, algo más genérica |
| Spark 4B | 0/24 | 11 | — | Falla JSON a 512 tokens |

Un título sin sellar (`title_version` vacío) **no asciende**: el gate vive en
`ascension.py` (`no_title`).

### Calibración de slots (`num_parallel`) — receta por hardware

No hay un número universal: `num_parallel` depende del **modelo** (pesos + KV),
del **contexto** que necesite la tarea y del **ancho de banda** de la GPU. Cada
agente debe correr la receta al instalarse/actualizarse y **repetirla al cambiar
de modelo o de contexto**; el resultado se aplica al perfil y a la tarea.

```bash
# 1) desk pausado (libera VRAM); el script descarga el modelo del daemon
PYTHONPATH=src .venv/bin/python scripts/calibrate_slots.py \
    --profile <perfil> --ctx <contexto total> --max-slots 8
# 2) aplicar
#    hardware_affinity.num_parallel: N
#    MEMENTO_TITLES_CONCURRENCY=N
```

El script levanta el servidor con `-np 1,2,4,6,8`, lanza 4 batches sintéticos de
títulos **en concurrente**, mide tiempo/tokens/VRAM y recomienda el primer slot
donde la ganancia marginal cae por debajo del 10 %. `--dry-run` valida el plan
sin GPU; `--apply` escribe `num_parallel` en el perfil (con backup); `--json-out`
deja el detalle.

**Medido en este equipo (2026-11-27, Bonsai 2-9B, ctx 32768, 4 batches)**:

| Slots | VRAM (delta) | 4 batches | Speedup |
|---:|---:|---:|---:|
| 1 | 2.683 MB | 26,4 s | 1,0× |
| 2 | 2.717 MB | 16,5 s | 1,6× |
| **4** | **2.809 MB** | **11,2 s** | **2,36×** |
| 6 | 2.925 MB | 11,2 s | 2,36× |
| 8 | 3.021 MB | 11,1 s | 2,37× |

Recomendado **4** (8k de contexto por slot). A partir de ahí el ancho de banda
manda; más slots solo recortan el contexto por slot.

> **Cuidado con el proxy**: la receta mide el **servidor**. El daemon actual
> serializa las peticiones (`manager.lock` durante toda la generación): por el
> camino de producción la ganancia se queda en ~1,2× hasta que el lock cubra
> solo resolve/carga con un contador de in-flight. Medido el 27-11: 2,36×
> directo vs 1,19× a través del daemon.

**Distill (medido 2026-11-27, 27B real, 4 fragmentos reales de 8k de la sesión
f839399b, ctx 24.576)**:

| Slots | VRAM | 4 fragmentos | Speedup |
|---:|---:|---:|---:|
| 1 | 6.717 MB | 66,0 s | 1,0× |
| 2 | 6.675 MB | 59,1 s | 1,12× |
| 4 | 6.631 MB | 71,1 s | **0,93×** |

El 27B **no gana** con slots: 12 % a 2 y empeora a 4 (ancho de banda/cómputo).
Se deja `np=1`. Los fragmentos tienen dependencia de continuación, así que la
concurrencia solo podría explotarse entre work units/sesiones y el techo real
sería ese ~12 %. Subir a 32k cuesta +265 MB de KV y **cabe** (~7,0 GB), pero no
ataca el cuello de botella; no se adopta por ahora.

## 4. Procedimiento de admisión

1. **Perfil**: alta en `model_profiles.yaml` (bloque de conducta + `kv_cache` +
   `vram_footprint` + `hardware_affinity`).
2. **Techo y memoria**: `PYTHONPATH=src .venv/bin/python scripts/kv_ceiling.py
   --profile <perfil> --kv q8_0,q4_0` → contexto máximo que carga y footprint.
3. **Contrato y calidad**:
   - distill: `scripts/distiller_fidelity.py` (ambos lados, fidelidad) y
     `scripts/distiller_bakeoff.py` (formato/JSON) con el prompt del carril.
   - annotate: `PYTHONPATH=src .venv/bin/python scripts/annotate_context_ab.py`
     (unidades reales p50/p90/p99, A/B de contexto, N=3; §5) y
     `scripts/bench_annotate.py --repetitions 3` para el coste/contrato.
4. **Peor caso end-to-end**: una unidad real del p99 (por chars) por el pipeline
   de producción (`memento_agentic --phase <fase> --target <sesión>`), con la GPU
   libre, midiendo `finish_reason`, secciones/notas y tiempo.
5. **Calidad al contexto**, A/B y N=3 (§2): el mismo modelo al `n_ctx` vigente y
   al candidato, con las mismas unidades (p50/p90/p99). Sin esta tabla no hay
   admisión: caber no es destilar bien.
6. **Registro**: la ficha del modelo (`docs/MODELS/<modelo>/README.md`) lleva la
   tabla A/B de contexto/calidad y un veredicto explícito: **admisible / no
   admisible** y por qué. Sin ese registro no hay admisión, aunque los números
   «parezcan» bien.

## 5. Baselines de referencia (2026-11-27)

| Carril | Titular | Contexto de producción | Medido |
|---|---|---:|---|
| distill | `bonsai_25_27b_distill` | 24.576 (tier 7,4 GB) | 2,6 ms/char (101.884 chars → 18 secciones en 261 s), 0 degradadas |
| annotate | `k2_horizon_7b` + trozos ≤8.000 | 10.240 | p99 24,1k → 4 trozos (5,8–6,4k), 29 notas, 196–297 s/unidad, 0 errores |

### A/B/C de annotate (2026-11-27, K2, N=3, unidades reales)

Unidades p50/p90/p99 de chars del árbol (12.224 / 14.321 / 24.107). Notas por
unidad = work + social + todos los trozos (mediana de 3 reps).

| Brazo | p50 | p90 | **p99** |
|---|---:|---:|---:|
| A · K2 a 10.240 | 19 notas · 66 s · 0 err | 11 · 66 s · 0 err | **0 · 6/6 `PromptTooLongError`** |
| B · K2 a 16.384 | 12 · 63 s · 0 err | 12 · 115 s · 0 err | **0 · 6/6 `ReadTimeout`** (360 s/unidad) |
| C · K2 a 10.240 + trozos | 13 · 71 s · 0 err | 15 · 86 s · 0 err | **29 · 272 s · 0 err** |

Lectura: A no puede servir el p99 (el prompt completo son 29.194 chars); B
tampoco (el prompt completo + 4.061 de salida no termina en 180 s y el servidor
de un solo slot encola el resto); C es la única que completa las tres. En
p50/p90 el conteo de A está inflado por duplicación work→social (el dedup P1-A
la colapsa en producción); el contenido es el mismo. Detalle y decisión en
**AD-146**.

## 6. Si no cumple

No entra como candidato de producción. Puede seguir siendo:
- **candidato de banco** si el hueco es de calidad y no de contrato/memoria;
- **candidato con condiciones** si el fallo es de contexto y se resuelve troceando
  o subiendo `n_ctx` — pero se vuelve a medir con la condición aplicada.

El motivo del rechazo se escribe en su ficha. «Carga y responde» no es un criterio.

## 7. Cuándo se repite

- Versión nueva del modelo (aunque sea el mismo nombre).
- Cambio de `MEMENTO_FRAGMENT_MAX_CHARS`, de `MEMENTO_ANNOTATE_CHUNK_CHARS`, del
  tope de annotate, del prompt o de `thinking`.
- Cambio de `n_ctx` del perfil o del tier de VRAM aplicado.

## 8. Qué no cubre

- El banco de Dokimé (`BENCH_ADMISSION.md`): otro objeto, otro contrato.
- Minions y tool-calling (`scripts/capability_bench.py`).
- El chat del daemon (`task: conversation`): no produce memoria.
