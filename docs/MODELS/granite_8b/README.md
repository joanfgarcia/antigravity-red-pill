# granite_8b — Granite-4.1-8B

> Destilador en producción desde v8.0.0. Deixis estable, relics verbatim fiables,
> Apache-2.0. Su ventana servible hoy es 12.288 tokens **porque el runtime no usa
> cuantización de KV**. Con `q8_0` serían 24.576.

Perfil: `granite_8b` · Fichero: `Granite-4.1-8B-Q4_K_M.gguf` · Medido: 2026-10-29

---

## Specs

| Campo | Declarado (IBM) | Medido (GGUF) |
| --- | --- | --- |
| Contexto | 131.072 | 131.072 |
| Capas | 40 | 40 |
| Heads / kv_heads | 32 / 8 | 32 / 8 |
| Embedding / FFN | 4096 / 12800 | 4096 / 12800 |
| Vocabulario | 100.352 | 100.352 |
| rope freq base | 1e7 | 1e7 |
| Pesos Q4_K_M | — | 5.100 MiB en VRAM |
| KV por token (f16) | — | **160 KiB** |

Arquitectura: transformer denso con GQA (`GraniteForCausalLM`), sin sliding window
ni híbrido SSM. `tie_word_embeddings: true`.

## Límites medidos (RTX 5070 Laptop 8 GB)

| Cuantización KV | `n_ctx` máximo | Pico VRAM |
| --- | ---: | ---: |
| f16 | **12.288** | 7.097 MiB |
| q8_0 | **24.576** | 7.259 MiB |
| q4_0 | **49.152** | 7.499 MiB |

Son **suelos**: el sondeo para en el primer valor que arranca. El techo real está
entre ese valor y el siguiente candidato que falló.

## El defecto abierto: el runtime no cuantiza el KV

`src/red_pill/core/model_runtime.py` y `model_registry.py` **no pasan `type_k` ni
`type_v`**. El `llama_cpp` del venv sí los acepta, y el arnés de bench ya los usa desde
el 2026-09-17:

```python
# scripts/bakeoff_granite_42.py:168
llm = Llama(..., n_ctx=12288, type_k=llama_cpp.GGML_TYPE_Q8_0)
```

Consecuencia: la tabla `vram_tiers` del perfil está congelada en el peor caso. Sus
filas:

```yaml
- min_free_gb: 6.5 → n_ctx: 6144
- min_free_gb: 7.2 → n_ctx: 10240     # el que se usa hoy
- min_free_gb: 7.7 → n_ctx: 12288
- min_free_gb: 8.2 → n_ctx: 16384     # INALCANZABLE: la GPU tiene 8.151 MiB
```

Dos defectos además de la falta de KV: `n_ctx: 16384` es inalcanzable con f16
(medido: 12.288), y la fila de 8,2 GB no se cumple nunca por aritmética de la tarjeta.

## Bench (BENCHSET, 2026-10-29)

`q4_0`, `n_ctx` 32.768, n=3 por probe, temperatura 0.3.

| Probe | Resultado |
| --- | --- |
| `contract_entidades` | 3/3 |
| `contract_decision` | 3/3 |
| `contract_genero` | 3/3 |
| `needle_8k` | 3/3 |
| `synthesis_es` | **0/3** — 5/8 hechos, umbral 6/8 |
| **Total** | **12/15** |

Latencia media 5,3 s. Fallo conocido y estable: no llega a 6/8 hechos en resumen de
3 frases.

## Procedencia del corpus de hubs (2026-11-15)

Los **434 hubs** de `work_memories` + `social_memories` salieron de este modelo. No
lo dice el payload — `hub_model` solo se rellena cuando se usa el camino grande y
`hub_large_path` nunca se disparó en producción — lo dice el rastro:

| Evidencia | Alcance |
| --- | --- |
| Journal del proxy (retención desde 2026-09-11) | **2.787** llamadas `task 'hub'` → `granite_8b`; **0** con otro modelo |
| `task_profiles.yaml` (actual + backups del 2026-10-30) | `hub` → `granite_8b` `default: true`; k2 y spark solo candidatos no-default desde 2026-11-09 |
| Job `b42602f3` (2026-11-09, 228/228 steps) | migración de hubs declarando `llm.model: granite_8b` |
| Job `a5790505` (2026-11-15) | re-síntesis forzada de una sesión: el proxy cargó `granite_8b` (`Granite-4.1-8B-Q4_K_M.gguf`, n_ctx 16384) y cayó a CPU; hub de 948 chars escrito |
| `scripts/hub_bakeoff.py` | mide sin escribir hubs: **no** hay hubs de k2/spark en producción |
| Atestación del Operador (2026-11-15) | los **62** hubs de feb–ago, fuera de la retención del journal, también son suyos |

**El carril de re-síntesis es granite por decisión, no por costumbre**
(Operador, 2026-11-15): la migración de noviembre, la caducidad de la espera y el
forzado manual comparten el mismo `task: hub` → `granite_8b`. Cambiar de modelo en
ese carril exige bake-off previo (`scripts/hub_bakeoff.py`, que no escribe) y una
entrada en este doc; k2 y spark siguen siendo candidatos no-default.

Consecuencia: el corpus es homogéneo **en modelo**, no **en contrato**. **77** hubs
pre-v3 (feb–oct) no tienen `hub_title` ni `hub_terms`, campos que el contrato actual
escribe siempre; re-sintetizarlos homogeneizaría la forma, no el fondo.

Pendiente de mayor retorno para auditar bake-offs: registrar el modelo **por fase**
(map/reduce/master) en vez de un único nombre — hoy el campo solo existe para el
camino grande, y un nombre único mentiría por simplificación.

## Observaciones (comportamiento, no specs)

> Medidas, no intuiciones. Sirven para **parametrizar prompts**; no son knobs.

- **No respeta estrictamente el límite de longitud que se le pide.** Medido el
  2026-11-19 en el canario MEM-011 (Q4_K_M, carril CPU, muestreo no greedy): con
  objetivo 900 y tope duro 1000 escribió resúmenes de **1048 y 1097 chars**
  (16-22 % sobre el objetivo, 5-10 % sobre el tope) y el hub se rechazó.
  **Fix**: objetivo **800** (`SLEEP_HUB_SUMMARY_TARGET_CHARS`, `790fbb7`),
  confirmado el 2026-11-20 en una sesión de 222 miembros: **15/15 partes**, raíz
  con 15 miembros, sin saltos (job `39a14b1e`, 55 min en CPU). El tope duro no
  cambió.
  **Para prompts futuros**: pedir con margen (~20 %), nunca al filo; validar o
  reintentar en vez de asumir que cumple.
- **No confundir con truncación** (`finish_reason=length`): este fallo es por
  **exceso** de longitud, no por corte del proveedor.

## Licencia

| Campo | Valor |
| --- | --- |
| id | `apache-2.0` |
| comercial | sí |
| redistribución | sí |
| fichero LICENSE en el repo | sí |
| source | https://huggingface.co/ibm-granite/granite-4.1-8b |

## Veredicto

**Titular.** Es el único modelo del elenco que sostiene deixis y relics verbatim a la
vez, que es lo que Memento necesita. Su debilidad (`synthesis_es`) no forma parte del
camino crítico del destilador.

**Acción pendiente de mayor retorno:** meter `type_k`/`type_v` en el runtime. Duplica
la ventana de 12.288 a 24.576 sin tocar el modelo y sin coste de calidad medido.
