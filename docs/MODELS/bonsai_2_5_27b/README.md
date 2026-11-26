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
fixture** (no por la prosa), `n=3`, brazo nulo en cada pasada.

**Hay dos brazos y no son intercambiables** (`run_one`, `bench_hard.py`):

| brazo | qué ejecuta | de dónde sale `max_tokens` |
| :--- | :--- | :--- |
| `dokime` | la CLI de **Pi** dentro de la caja (texto, `--tools bash`, sin MCP) | del `models.json` de Pi: **no** lo pone `bench_hard` |
| `minion` | `local_minion` con **sólo** `run_bash` | de `bench_hard --max-tokens` |

Por eso las dos tablas van separadas: **no se pueden restar**. Todo lo publicado
el 25-nov es `dokime`; todo lo medido el 26-nov es `minion`.

### Brazo `dokime` (Pi) — medido el 2026-11-26 con config explícita

Mismo brazo que lo publicado, pero con el `models.json` de la caja escrito por el
propio banco (`maxTokens: 16384` explícito), GPU libre al arrancar y los tres
modelos seguidos. Servidor: prism `b12178`, ctx 32.768 (27B) / 65.536 (9B y
Spark), KV `q8_0`, `--reasoning-budget 2048` (Spark 256), `--timeout 300`.

| modelo | pass^1 | pass^3 | instrucción | p50 | p95 | timeouts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Bonsai 2.5 27B** | **91,7%** | **83,3%** | **92%** | 27,3 s | 633,1 s | 2 |
| Bonsai 2 9B | 86,1% | 75,0% | 89% | 24,2 s | **41,2 s** | 0 |
| Spark-X2.6-4B | 86,1% | 75,0% | 90% | **21,9 s** | 354,5 s | 2 |

| familia | 27B | 9B | Spark |
| --- | ---: | ---: | ---: |
| cadena | **9/9** | 8/9 | **9/9** |
| restricciones | **9/9** | 7/9 | 6/9 |
| memoria | 7/9 | 7/9 | 7/9 |
| ventana | 5/6 | **6/6** | **6/6** |
| recuperación | **3/3** | **3/3** | **3/3** |

- **`d2` en este brazo**: 27B **2/3** (300 s y 633 s; la tercera se queda vacía a
  los 633 s), 9B **3/3** en 20–34 s, Spark **3/3** (una a 663 s). El 27B sabe
  hacerlo con 16k de tope; lo que no tiene es prisa.
- Los timeouts que quedan son de `c3` (27B y Spark) y `e1` (Spark), todos a 300 s.
- Ninguno de los tres se despega: 27B +5,6 puntos sobre los otros dos, con p50
  ×1,25 y peor cola. La diferencia cae dentro del ruido de la máquina (abajo).

### Lo publicado el 2026-11-25 — no comparable

Misma tabla, misma máquina, otra corrida. Se conserva como historia, no como vara:
cada brazo se midió en un estado distinto de la máquina.

| modelo | pass^1 | pass^3 | p50 | timeouts |
| --- | ---: | ---: | ---: | ---: |
| Bonsai 2 9B | **86,1%** | 66,7% | **9,0 s** | 0 |
| Bonsai 2.5 27B | 80,6% | 58,3% | 83,0 s | **8** |
| Spark-X2.6-4B | 69,4% | 66,7% | 27,3 s | 4 |

**Por qué no se puede restar**: con el mismo binario y el mismo modelo, el p50 del
9B fue **9,0 s** entonces y **24,2 s** ahora (×2,7), y el del 27B **83,0 s** contra
**27,3 s** (×3). Un factor 3 entre corridas idénticas se come cualquier diferencia
de calidad de 5 puntos. En la corrida publicada el 27B fue el último de los tres
(tras ~2 h de carga) y se llevó 7 timeouts a 300 s; el 9B, el primero, ninguno.
**El orden de los brazos confunde modelo con estado de la máquina.**

### Brazo `minion` (`local_minion`) — medido el 2026-11-26

Mismo servidor prism `b12178` para los tres, contexto y presupuesto de cada modelo,
la misma caja, el mismo fixture y `--timeout 300`; `--max-tokens 6144`.

| modelo | pass^1 | pass^3 | instrucción | p50 | p95 | timeouts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Bonsai 2.5 27B** | **91,7%** | **91,7%** | **92%** | 38,0 s | 334,8 s | 0 |
| Bonsai 2 9B | 72,2% | 41,7% | 83% | **7,9 s** | **39,2 s** | 0 |
| Spark-X2.6-4B | 63,9% | 58,3% | 72% | 8,2 s | 37,4 s | 0 |

| familia | 27B | 9B | Spark |
| --- | ---: | ---: | ---: |
| cadena | 9/9 | 7/9 | 9/9 |
| restricciones | 9/9 | 6/9 | 1/9 |
| memoria | 9/9 | 5/9 | 9/9 |
| ventana | 3/6 | **6/6** | 4/6 |
| recuperación | 3/3 | 2/3 | 0/3 |

- Los tres con **cero timeouts**. Pared total: 2.078 s (27B) · 1.120 s (9B) · 434 s
  (Spark).
- El 27B es el que más pasa y el más lento: p50 ×4,8 del 9B.
- `d2` en este brazo: el 27B falla 3/3 con un 500 (heredoc, ver abajo), el 9B pasa
  **6/6** contestando en contexto y Spark falla 2/3 con un tool-call mal formado.
  Es una diferencia de **estrategia**, no de capacidad: el 27B sabe contar
  (3/3 directo, sin tools), pero elige un camino que no cabe en la ventana.
- El 9B baja aquí respecto del brazo Pi (86,1 → 72,2) y Spark también (69,4 →
  63,9): **no es el tope**, es el arnés. Sus fallos son de política y formato
  (cuenta mal `funcs`, contesta el puerto equivocado, inventa un código, envuelve
  el JSON en vallas), no de presupuesto.

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

**Mecanismo** (medido in-process, mismo GGUF y build): si el tope de generación no
deja sitio **después** del razonamiento, el modelo no llega a contestar —
`finish_reason: length`, `content` vacío y la traza se lo come todo. Con el
presupuesto a 2048 y el cap a 2048 el margen es **cero**; con cap 6144 el
presupuesto cierra el razonamiento en 2.048 y la respuesta sale (2.054 tokens,
`TAG-A1`). Sin presupuesto declarado la regla es la misma con el nombre cambiado:
el cap tiene que superar el razonamiento **natural** del modelo (en `d2`, 4,1k).

**Atribución — corregida el mismo día**: ese par `2048/2048` vive en `run_minion`
y en el perfil base, **no** en la tabla publicada. La tabla del 25-nov es el brazo
`dokime` (Pi), que no pasa por el `--max-tokens` de `bench_hard`. Así que el `d2`
0/3 a 900 s **no queda explicado** por este mecanismo: Pi pedía hasta 16.384 tokens
(el default de su esquema) y la máquina iba ~3× más lenta (p50 83 s), de modo que
cada vuelta del bucle de agente costaba 150–250 s de prefill y los 900 s llegaban a
las cuatro vueltas. En la corrida limpia, con el mismo tope, `d2` pasa **2/3**
(300 s y 633 s). Lo que queda probado: (a) el mecanismo del tope, y (b) que el 27B
**sabe** resolver `d2` cuando la máquina y el tope se lo permiten.

Datos de contexto que conviene tener:
- `d2` son **16.825 tokens de prompt** (24k chars ≈ 0,70 tok/char). Con el perfil
  base (n_ctx 24576, max_tokens 8192) no caben las dos cosas: 16.825 + 8192 =
  25.017 > 24.576. Para esta clase de tarea, o ctx 32768 o cap ≤ 7.751.
- Subir el contexto cuesta decodificación: **29–31 tok/s a 24.576** frente a
  **18,2 tok/s a 32.768** (−40 %), con la misma GPU y el mismo KV `q8_0`.
- `b1` responde en 1957 de 2048 tokens: el «a veces pasa» de la tabla publicada es
  exactamente eso, un margen de 91 tokens.
- Regla: `max_tokens` = **presupuesto de razonamiento + margen de respuesta**,
  nunca igual; y si el modelo no declara presupuesto, por encima de su
  razonamiento natural.

### Segundo motivo (brazo `minion`): el arnés de `d2`

En el brazo `minion` el modelo no cuenta en contexto: intenta resolverlo con
`run_bash` y un heredoc que mete el texto entero en el comando. Con 77.143
caracteres de prompt, el tool-call se corta a media cadena y el servidor responde
500:

```
Failed to parse tool call arguments as JSON: parse error at line 1, column 19321:
invalid string: missing closing quote; last read: '"grep -o \"TAG-[A-Z0-9]*\" /dev/stdin <<'EOF' | sort | uniq -c'
```

No es un fallo del servidor ni del parser: es una tarea de conteo en contexto
ejecutada con un arnés que sólo ofrece `run_bash` (y el texto no está en disco,
sólo en el prompt). Ojo: el **9B pasa ese mismo `d2` 6/6** contestando en
contexto, así que aquí hay una diferencia real de **estrategia**, no de capacidad
—el 27B contesta `TAG-A1` en 4.102 tokens cuando se le da la tarea directa, sin
tools—. En el brazo `minion`, el bloque `ventana` mide `d1` (3/3) y `d2` mide la
tendencia a resolver por shell.

## Qué queda del veredicto

- Con la configuración documentada y la GPU libre, los tres modelos quedan a menos
  de 6 puntos: **27B 91,7 % (pass^3 83,3) · 9B 86,1 % (75,0) · Spark 86,1 %
  (75,0)**. El 27B es el más consistente y el más lento (p50 ×1,25 del 9B, p95 ×15).
- **La tabla publicada no sirve como vara**: el mismo 9B, con el mismo binario,
  pasó de 9,0 a 24,2 s de p50 entre corridas, y el 27B de 83,0 a 27,3. La
  diferencia entre modelos es del tamaño del ruido del orden de las corridas.
- Por tanto «no desplaza a Spark» **no se ratifica ni se revoca**: se retira como
  conclusión medida. Lo que hay es un empate técnico en calidad con tres perfiles
  de latencia, y un banco que hoy no puede separarlos.
- Para poder decidir hace falta cambiar el diseño del banco, no el modelo:
  **intercalar** los tres brazos por tarea/trial (en vez de un modelo por corrida),
  registrar la temperatura y el estado de la GPU por pasada, y repetir con la
  máquina en frío. Con eso, la diferencia de 5 puntos se podrá atribuir o descartar.

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
