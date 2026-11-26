# bonsai_25_27b — Ternary Bonsai 2.5 27B (PTQ1_0)

> El mismo ternario que `bonsai_2_27b` (5,93 GB, base Qwen3.8-27B) con la
> conducta agéntica arreglada: tool-calling a nivel FP16 y menos sobre-razonamiento.
> Medido: 2026-11-25.

Perfil: `bonsai_25_27b` (+ `bonsai_25_27b_instruct`) · Fichero:
`Ternary-Bonsai-2.5-27B-PTQ1_0.gguf` · Runtime: **`llama_cpp_prism` `b12178`**
(prebuilt oficial, CUDA 13.3) · Hermana MTP: `...-PTQ1_0-mtp.gguf` (6,23 GB).

---

## Specs

| Campo | Valor |
| --- | --- |
| Parámetros | 27,36B (24,35B backbone + 2,54B embed/LM head + 0,47B visión) |
| Cuantización | ternaria g128, **1,76 bpw**, PTQ1_0 (5,93 GB) |
| Base | Qwen3.8-27B, atención híbrida (~75% lineal / ~25% completa) |
| Contexto declarado | 262.144 |
| Modalidades | texto + imagen (mmproj aparte, `Q8_0` 629 MB) |
| Razonamiento | `xhigh` (defecto) o `medium`; **`low` NO existe** |
| Licencia | Apache-2.0 |

## Techos de contexto MEDIDOS (RTX 5070 Laptop 8 GB, 7500 MiB de presupuesto)

| KV | MiB/1k | techo verificado |
| --- | ---: | ---: |
| `q8_0` | 33,2 | **43k** |
| `q4_0` | 17,6 | **80k** |
| **`pq2_0m`** | **8,8** | **112k** |

`pq2_0m` (KV de 2 bits, nuevo en `b12178`) duplica `q4_0`. **Y no es sólo carga:
lee.** Needle a ventana llena (`scripts/needle_window.py`, 5/5 aciertos):

| prompt real | resultado | latencia |
| ---: | :--: | ---: |
| 21.580 | ✓ | 58 s |
| 43.085 | ✓ | 126 s |
| 64.567 | ✓ | 206 s |
| 86.072 | ✓ | 298 s |
| **103.253** | ✓ | 379 s |

Prefill ≈ 270–290 tok/s: 100k de contexto cuesta ~6 min de lectura. La ventana es
real, no gratis.

## BENCHSET v1 (2026-11-25, `n_ctx` 24.576)

| variante | contratos | needle 16k/8k | síntesis | latencia |
| --- | :--: | :--: | :--: | --- |
| thinking `medium` | 3/3 | 2/2 | **8/8** | 22–128 s |
| off con sampler de thinking | 2/3 | 2/2 | 5/8 | 16–31 s |
| **instruct (T0.7 / top_p 0.80)** | **3/3** | **2/2** | 7/8 | 9–32 s |

Comparativa del elenco (misma sesión): K2-7B 3/3 · síntesis 6/8; Spark-4B 3/3 ·
7/8; 9B-instruct 3/3 · 5/8. **Subconjunto común (3 contratos + síntesis): 2.5 4/4,
K2 4/4, Spark 4/4, 9B 3/4.**

## Carril de destilado: NO cambia nada (medido, 3 reps)

| config | síntesis | latencia | contrato |
| --- | --- | ---: | :--: |
| `bonsai_2_27b` (prod: off, T0.3) | 5,6,6 /8 | 6–10 s | ✓ |
| 2.5 instruct (off, T0.7) | 7,5,6 /8 | 6–10 s | ✗ deixis ("brindo contigo") |
| 2.5 off (T0.3) | 5,6,6 /8 | 7–8 s | ✓ |
| 2.5 thinking medium | 8,8,7 /8 | 35–37 s | ✓ 113 s |
| 2.5 thinking **low** | 7,8,8 /8 | 34–47 s | ✓ 128 s |
| 2.5 thinking budget 1024 | 7,7,7 /8 | 43–140 s | ✓ 172 s |
| 2.5 thinking budget 512 | 8,7,7 /8 | 59–134 s | ✓ 203 s |

Conclusiones:
- **A igual latencia, empata con 2.0** en destilado. Su valor es agéntico.
- **`low` == `xhigh`**, como avisa la doc: ni una décima de ahorro.
- **`--reasoning-budget` empeora**: el modelo entra en bucle de verificación
  ("Check sentence count…") y además el rastro se cuela en `content`
  (`[End thinking] El 14 de marzo…`). Veneno para un carril que parsea JSON.
- **T0.7 con thinking off abre un fallo de deixis** (segunda persona). Si se usa,
  el carril debe ir a T0.3.
- La prosa de thinking es la mejor de las medidas (8/8 sin inventar: "revisión
  mensual durante seis semanas" está en la fuente), pero cuesta 4–5×.

## Veredicto

**Candidato para Dokimé** (tool-calling ≈ FP16, 5,9 GB, 112k de ventana con
`pq2_0m`). **NO para el carril `distill`**: no baja tiempos y abre riesgo de
deixis/JSON. El titular del sueño no se toca sin una prueba de textura.

## Sandbox de Dokimé (2026-11-25)
Con la imagen `localhost/prism-llama:b12178-cu13` (prebuilt `b12178` sobre CUDA 13):

- **Admisión (`bench_admission`)**: español ✓ · tools ✓ (`leer_fichero`) ·
  multiturno ✓ → **apto**, ya ejecutándose como contenedor hermano en `dokime-net`.
- **Bench de Dokimé (`bench_compare`, 18 tareas, 1 trial)**:

| modelo | pass | tiempo medio | total |
| --- | :--: | ---: | ---: |
| **Bonsai 2.5 27B** (ctx 32k, q8_0, budget 2048) | **18/18** | 11,1 s | 204 s |
| Spark-X2.6-4B (config guardada del alma) | 18/18 | **5,1 s** | 97 s |

Ambos saturan la batería: **no hay ganancia de calidad medible aquí**, sólo el
doble de latencia del 27B (thinking). Para decidir Dokimé con 2.5 hace falta una
batería más dura (o `bench_memory`, que mide la capa de memoria, no la prosa).

## Batería de techo (`bench_hard`, 2026-11-26)

`scripts/bench_hard.py` — 12 tareas en 5 familias, gradación por **estado del
fixture** (no por la prosa), `n=3`, brazo nulo en cada pasada. Config: `n_ctx`
32.768, KV `q8_0`, `--reasoning on --reasoning-budget 2048`.

| modelo | pass^1 | pass^3 | instrucción | p50 | p95 | timeouts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bonsai 2 9B (ctx 65k, budget 2048) | **86,1%** | 66,7% | **90%** | **9,0 s** | **61,5 s** | 0 |
| **Bonsai 2.5 27B** | 80,6% | 58,3% | 81% | 83,0 s | 900,1 s | **8** |
| Spark-X2.6-4B (referencia) | 69,4% | 66,7% | 75% | 27,3 s | 457,2 s | 4 |

Brazo nulo: **0/108 pass y 0/216 instrucciones** → la batería discrimina (donde
`bench_compare` saturaba en 18/18).

| familia | 9B | **2.5 27B** | Spark |
| --- | ---: | ---: | ---: |
| cadena | 8/9 | **9/9** | **9/9** |
| restricciones | 6/9 | **8/9** | 3/9 |
| memoria | **8/9** | 7/9 | 6/9 |
| ventana | **6/6** | 3/6 | 4/6 |
| recuperación | **3/3** | 2/3 | **3/3** |

- **Gana donde el 4B no llega**: restricciones contadas. `b1` 3/3 con 61–63
  palabras y cierre exacto (Spark escribe 19–45); `b3` 3/3 en «exactamente dos
  frases» (Spark envuelve en JSON o numera la lista). El coding no separa a nadie
  (cadena 9/9 en los dos).
- **Pierde en ventana**: `d2` (agregar etiquetas en ~19k) **0/3, las tres a 900 s**.
- **Ocho timeouts**, casi todos con prompts de 24–100 tokens: `b1`, `c1`, `c3`,
  `e1`. No es lentitud de prefill, es cuelgue. Un `e1` consta como pase porque el
  estado ya era correcto antes del cuelgue.
- **Se degrada con el uso**: p50 por repetición 46 s → 48 s → **256 s** (5/12
  por encima de 290 s en la tercera), compatible con throttling térmico del
  portátil tras ~40 min de carga continua. El orden de las pasadas (Spark → 9B →
  27B) también le deja la GPU más caliente.

**Contra la regla pactada** (desplazar a Spark exige ganar ≥2 bloques con margen,
no regresar el contrato y aceptar por escrito la latencia): gana **sólo
restricciones** con margen, empata cadena, pierde ventana y recuperación, y su
latencia es ×3 (no ×2) con el doble de timeouts. **No desplaza a Spark.**

## Peculiaridades de configuración
- `min_p` debe pasarse explícito (`--min-p 0`): llama.cpp aplica 0.05.
- Muestreo por modo: thinking `1.0/0.95/20/min_p 0/presence 0`; instruct
  `0.7/0.80/20/min_p 0/presence 1.5`. `presence_penalty` no viaja por request
  (`conduct._SAMPLER_KEYS`) → va como default de servidor.
- Razonamiento por defecto `xhigh`: sin `max_tokens` generoso, corta a mitad.
- MTP disponible con el build `b12178` (`--spec-type draft-mtp`, 3 borradores).
