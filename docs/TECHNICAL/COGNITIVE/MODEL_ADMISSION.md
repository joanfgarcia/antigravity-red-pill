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
| `annotate` **troceado a 8.000** | 8.000 chars | 4.096 | **6.144** | Cumpliría K2 a 10.240 |
| `annotate` **sin trocear (hoy)** | 20.000 chars (tope de `_fit_prompt`) | 4.096 | **12.608 → 12.800** | **K2 a 10.240 NO cumple**: el p99 (24,1k) se recorta en silencio |

> Consecuencia escrita: hoy `annotate` no puede admitir un modelo con `n_ctx`
> 10.240 si se mantiene el contrato de splits enteros. O se trocea a 8.000 (la
> estrategia que ya usa `distill`) o el perfil del juez sube a `n_ctx` ≥ 12.800.
> Cualquier candidato nuevo se evalúa contra la opción vigente.

> **Y en ambos casos hay que medir la calidad al contexto elegido.** Subir el
> `n_ctx` de K2 a 16.384 es una *hipótesis*, no un arreglo: antes hay que
> comprobar que K2 sigue anotando igual de bien con la unidad real a ese
> contexto. Lo mismo vale para trocear a 8.000: hay que medir que los fragmentos
> más pequeños no pierden ideas ni cambian la voz.

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

## 4. Procedimiento de admisión

1. **Perfil**: alta en `model_profiles.yaml` (bloque de conducta + `kv_cache` +
   `vram_footprint` + `hardware_affinity`).
2. **Techo y memoria**: `PYTHONPATH=src .venv/bin/python scripts/kv_ceiling.py
   --profile <perfil> --kv q8_0,q4_0` → contexto máximo que carga y footprint.
3. **Contrato y calidad**:
   - distill: `scripts/distiller_fidelity.py` (ambos lados, fidelidad) y
     `scripts/distiller_bakeoff.py` (formato/JSON) con el prompt del carril.
   - annotate: `PYTHONPATH=src .venv/bin/python scripts/bench_annotate.py
     --repetitions 3` (fixture fijo, detecta truncados y JSON inválido).
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
| annotate | `k2_horizon_7b` | 10.240 | ~800 tokens de salida por split de 16,6k; 2 llamadas/split; **no cubre el p99 de 24,1k** |

> K2 a 12.800 o 16.384 **no está medido**: por el contrato, hoy no es admisible
> para annotate sin trocear. Subir el contexto exige la tabla A/B de §2; hasta
> entonces es una hipótesis, no un titular.

## 6. Si no cumple

No entra como candidato de producción. Puede seguir siendo:
- **candidato de banco** si el hueco es de calidad y no de contrato/memoria;
- **candidato con condiciones** si el fallo es de contexto y se resuelve troceando
  o subiendo `n_ctx` — pero se vuelve a medir con la condición aplicada.

El motivo del rechazo se escribe en su ficha. «Carga y responde» no es un criterio.

## 7. Cuándo se repite

- Versión nueva del modelo (aunque sea el mismo nombre).
- Cambio de `MEMENTO_FRAGMENT_MAX_CHARS`, del tope de annotate, del prompt o de
  `thinking`.
- Cambio de `n_ctx` del perfil o del tier de VRAM aplicado.

## 8. Qué no cubre

- El banco de Dokimé (`BENCH_ADMISSION.md`): otro objeto, otro contrato.
- Minions y tool-calling (`scripts/capability_bench.py`).
- El chat del daemon (`task: conversation`): no produce memoria.
