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

### Decisión del Operador (2026-11-26): el carril pasa a 2.5

La medición decía «no cambia nada»; la decisión es alinear producción con el
modelo nuevo. Se acepta **sin ganancia de calidad esperada** (empate 5–6/8) y con
la latencia igual. Para que sea seguro no se usa el perfil base, que arranca con
thinking y sin `--reasoning off`, sino la variante **`bonsai_25_27b_distill`**:
thinking off, `--min-p 0` explícito, `top_p 0.95`, T0.3 (el 0.7 abría deixis).

Humo de carril (2026-11-26, sesión de 4,5k chars): 19,9 s en caliente, resumen en
primera persona fiel al original, keywords correctas y 4 notas ascendidas. El
primer intento sin `RP_LLM_TASK=distill` cayó al modelo por defecto del daemon
(granite) y escribió un volcado crudo: el carril **exige** la task en el entorno.
Ese fallo destapó un defecto de trazabilidad: `distill.py` sellaba `engine` con
`engine_id()` (consulta `/v1/models` cacheada al arrancar) en vez de con el motor
real de la respuesta; corregido en el mismo commit que esta ficha
(`served_engine()` + test de regresión).

## Veredicto

**Titular del carril `distill` desde 2026-11-26** (decisión del Operador). La
medición no muestra ganancia de calidad —empata 5–6/8 a igual latencia—, pero el
carril se alinea con el modelo nuevo. Se sirve con la variante
`bonsai_25_27b_distill` (thinking off, `min_p 0`, T0.3), nunca con el perfil base.
Y **candidato para Dokimé** (tool-calling ≈ FP16, 5,9 GB, 112k de ventana con
`pq2_0m`).

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
32.768, KV `q8_0`, `--reasoning on --reasoning-budget 2048`, `max_tokens 2048` ⚠.
⚠ = el `max_tokens` igualaba el presupuesto de razonamiento y no dejaba margen para
la respuesta; ver «Corrección del artefacto de d2».

| modelo | pass^1 | pass^3 | instrucción | p50 | p95 | timeouts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bonsai 2 9B (ctx 65k, budget 2048) | **86,1%** | 66,7% | **90%** | **9,0 s** | **61,5 s** | 0 |
| Bonsai 2.5 27B (cap 2048 ⚠) | 80,6% | 58,3% | 81% | 83,0 s | 900,1 s | **8** |
| **Bonsai 2.5 27B** (re-run, cap 6144) | **91,7%** | **91,7%** | **92%** | **38,0 s** | 334,8 s | **0** |
| Spark-X2.6-4B (referencia) | 69,4% | 66,7% | 75% | 27,3 s | 457,2 s | 4 |

Brazo nulo: **0/108 pass y 0/216 instrucciones** → la batería discrimina (donde
`bench_compare` saturaba en 18/18).

| familia | 9B | 2.5 27B (cap 2048) | **2.5 27B (cap 6144)** | Spark |
| --- | ---: | ---: | ---: | ---: |
| cadena | 8/9 | 9/9 | **9/9** | **9/9** |
| restricciones | 6/9 | 8/9 | **9/9** | 3/9 |
| memoria | 8/9 | 7/9 | **9/9** | 6/9 |
| ventana | 6/6 | 3/6 ⚠ | 3/6 ⚠ (d1 3/3) | 4/6 |
| recuperación | **3/3** | 2/3 | **3/3** | **3/3** |

### Re-medición con el tope sano (2026-11-26)

Mismo servidor (prism `b12178`, ctx 32.768, KV `q8_0`, `--reasoning-budget 2048`),
mismo fixture y mismo `--timeout 300`; **sólo** cambia `max_tokens 2048 → 6144`.
2.078 s de pared (34,6 min) frente a 106 min de reloj de tareas del brazo anterior.

- **33/36**: todo pasa 3/3 menos `d2`, que es el hueco del arnés (500 del tool-call).
- Los timeouts de la tercera repetición **desaparecen**: `b1` 46–88 s, `c1` 16–21 s,
  `c3` 48–80 s, `e1` 25–54 s (antes: 300 s, y `e1` 152 s en la primera). No era
  degradación térmica: era el tope cortando el razonamiento.
- Por tarea (3 pasadas): a1 12,6–16,6 · a2 10,1–10,7 · a3 13,4–13,9 · b1 46,7–87,9
  · b2 32,3–51,4 · b3 10,5–13,5 · c1 16,2–20,8 · c2 37,6–41,8 · c3 47,7–80,4 ·
  d1 42,5–43,6 · e1 25,4–54,2 · d2 261–384 (500).
- `pass^3` salta de 58,3 % a **91,7 %**: el modelo «inestable» era el cap.

- **Gana donde el 4B no llega**: restricciones contadas. `b1` 3/3 con 61–63
  palabras y cierre exacto (Spark escribe 19–45); `b3` 3/3 en «exactamente dos
  frases» (Spark envuelve en JSON o numera la lista). El coding no separa a nadie
  (cadena 9/9 en los dos).
- **Pierde en ventana** (medido, ver corrección abajo): `d2` (agregar etiquetas
  en ~19k) **0/3**, las tres cortadas a 900 s por el banco. **No es del modelo**:
  `max_tokens` (2048) igual al `--reasoning-budget` (2048) deja cero margen para la
  respuesta. Con 6144 → **3/3**, `TAG-A1`, en 112–147 s (2026-11-26).
- **Ocho timeouts**, casi todos con prompts de 24–100 tokens: `b1`, `c1`, `c3`,
  `e1`. No es lentitud de prefill, es el mismo tope: el razonamiento de estas
  tareas mide 1,9k–4,1k tokens y el corte estaba en 2048 (`b1` responde con 1957
  y 91 de margen: por eso pasa a veces y a veces no).
- **NO se degrada con el uso** (corregido 2026-11-26): tres pasadas idénticas dan
  29,1 · 29,0 · 28,9 tok/s con la GPU a 45–48 °C. El p50 46→48→**256 s** del banco
  no era el silicio, era el contenedor y el tope de tokens.

**Contra la regla pactada** (desplazar a Spark exige ganar ≥2 bloques con margen,
no regresar el contrato y aceptar por escrito la latencia): leído el brazo con el
tope sano, el 27B **no regresa ningún bloque** —33/36, todo 3/3 menos el hueco de
`d2`— y gana restricciones (9/9 vs 3/9) y memoria (9/9 vs 6/9), empata cadena y
recuperación. La latencia ya no es ×3: **p50 ×1,4** (38,0 vs 27,3 s) y **p95 mejor**
(334,8 vs 457,2 s), con 0 timeouts frente a 4. Sobre el papel eso **sí** cumpliría
la regla.

Lo que falta: los números de Spark y del 9B son de **otra corrida** (GPU con
inquilinos, cap 2048), así que la comparación pareada no está hecha. Para re-tomar
el veredicto hay que re-correr sus dos brazos con el mismo `max_tokens 6144`.
Mientras eso no pase, el veredicto anterior queda **suspendido**, no ratificado: se
apoyaba en un artefacto del banco.

> **Re-medido (2026-11-26, cap sano)**: 33/36 → **91,7% pass^1 y 91,7% pass^3**,
> p50 38,0 s, p95 334,8 s, **cero timeouts**. Todo pasa 3/3 menos `d2`, que no es
> medible por este arnés (§ corrección). El motivo para no desplazar a Spark ya no
> puede ser «peor calidad»: en el mismo arnés, el 27B saca 12 puntos más de pass^1
> que el 9B y 22 más que Spark, con p50 ×1,4 de Spark y p95 mejor. Pero **la tabla
> no es comparable entre corridas** (9B y Spark vienen de la corrida contaminada):
> para re-tomar el veredicto hay que re-correr sus dos brazos con el mismo tope.

## Corrección del artefacto de `d2` (2026-11-26)

Síntoma publicado: `d2` 0/3, las tres pasadas a 900 s, y «se degrada con el uso».
Medido in-process con el servidor del equipo (mismo GGUF, mismo build `b12178`):

| sonda | ajustes | tokens | tok/s | pared | resultado |
| :--- | :--- | ---: | ---: | ---: | :--- |
| 3× idénticas | ctx 24576 · T1.0 · cap 512 | 512 | 29,1 · 29,0 · 28,9 | 49/18/18 s | `length`, sin respuesta |
| `d2` con el cap del banco | ctx 24576 · T0.7 · cap 2048 | 2048 | 28,7 | **103 s** | `length`, sin respuesta |
| `d2` con margen | ctx 32768 · T1.0 · cap 6144 | 4102 | 18,0 | 262 s | **`TAG-A1`** |
| `d2` con args del banco, margen | `--reasoning-budget 2048` · cap 6144 · seed 42 | 2054 | 18,2 | 113–147 s | **3/3 `TAG-A1`** |
| `d2` por el arnés `minion` (tools) | cap 6144 | — | — | 254 s | 500: tool-call cortado |

Causa raíz: **`max_tokens` (2048) = `--reasoning-budget` (2048)**. El modelo
razona 2048 tokens (6.172 chars), el presupuesto lo cierra justo ahí y ya no queda
ni un token para la respuesta: `finish_reason: length` y `content` vacío. No hay
cuelgue ni throttling: el corte llega en 103 s, no en 900.

Datos de contexto que conviene tener:
- `d2` son **16.825 tokens de prompt** (24k chars ≈ 0,70 tok/char). Con el perfil
  base (n_ctx 24576, max_tokens 8192) no caben las dos cosas: 16.825 + 8192 =
  25.017 > 24.576. Para esta clase de tarea, o ctx 32768 o cap ≤ 7.751.
- Subir el contexto cuesta decodificación: **29–31 tok/s a 24.576** frente a
  **18,2 tok/s a 32.768** (−40 %), con la misma GPU y el mismo KV `q8_0`.
- `b1` responde en 1957 de 2048 tokens: el modo «a veces pasa, a veces no» de la
  tabla es exactamente eso, un margen de 91 tokens.
- Regla para el banco: con modelos que piensan, `max_tokens` tiene que ser
  **presupuesto de razonamiento + margen de respuesta**, nunca igual.

### Segundo motivo: el arnés de `d2` (medido 2026-11-26)

Aun con el tope corregido, `d2` **no es medible por el brazo `minion`**. El
modelo no cuenta en contexto: intenta resolverlo con `run_bash` y un heredoc que
mete el texto entero en el comando. Con 77.143 caracteres de prompt, el tool-call
se corta a media cadena y el servidor responde 500:

```
Failed to parse tool call arguments as JSON: parse error at line 1, column 19321:
invalid string: missing closing quote; last read: '"grep -o \"TAG-[A-Z0-9]*\" /dev/stdin <<'EOF' | sort | uniq -c'
```

No es un fallo del servidor ni del parser: es una tarea de conteo en contexto
ejecutada con un arnés que sólo ofrece `run_bash` (y el texto no está en disco,
sólo en el prompt). Sin tools, el mismo prompt contesta `TAG-A1` en 4.102 tokens
(tabla de arriba). Consecuencia para leer la tabla: el bloque `ventana` del brazo
`minion` mide `d1` (que sí pasa 3/3) y **no** mide `d2` — su hueco es del arnés.
Para medir el 27B en ventana hay que darle la tarea directa (sin tools), o un
fixture con el texto en disco.

## Peculiaridades de configuración
- `min_p` debe pasarse explícito (`--min-p 0`): llama.cpp aplica 0.05.
- Muestreo por modo: thinking `1.0/0.95/20/min_p 0/presence 0`; instruct
  `0.7/0.80/20/min_p 0/presence 1.5`. `presence_penalty` no viaja por request
  (`conduct._SAMPLER_KEYS`) → va como default de servidor.
- Razonamiento por defecto `xhigh`: sin `max_tokens` generoso, corta a mitad.
- MTP disponible con el build `b12178` (`--spec-type draft-mtp`, 3 borradores).

### El tope de tokens y el carril de `distill` (2026-11-26)

La regla `max_tokens > presupuesto de razonamiento` sólo existe **cuando el modelo
piensa**. El carril de destilado no piensa: el daemon lo arranca con
`--reasoning off --reasoning-budget 0` (journal 2026-11-26 14:35:34), así que sus
2.048 tokens son todos para la sección y la desigualdad se cumple sola. Sus números
no cambian: 101.884 chars → 18 secciones en 261 s, 2,6 ms/char, 0 degradadas.

Lo que **sí** le afectaba es el fallo de AD-140: un servidor que no aplicaba
`profile.extra_server_args` servía el perfil con el thinking encendido, y entonces
los 2.048 tokens se iban en razonamiento y `content` volvía vacío — medido con este
mismo perfil antes del arreglo: 2.817 y 5.853 chars de `reasoning_content`,
`finish_reason: length`, cero contenido. Una sección vacía no falla: se escribe
vacía o se descarta.

Auditoría de los `task_profiles` (2026-11-26): `distill`, `annotate`, `refine`,
`validate` y `minion_tool` van con thinking off y tope 1.024–2.048; `distill_low`
(low, 4.096) y `conversation` (low) tienen margen; `hub` declara `on` en la task
pero el modelo lo sobreescribe a off. Ningún carril de producción queda expuesto.
`annotation_phases.py:36` ya grita «el modelo puede gastarlo pensando» cuando ve un
array JSON sin cerrar: es el mismo fallo, visto al final en vez de al principio.
