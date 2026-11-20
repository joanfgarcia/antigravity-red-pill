# Admisión al banco de Dokimé

Un modelo no entra al banco por bueno que sea en benchmarks: entra si pasa **tres mínimos**.
Decididos por el Operador el 2026-11-19, tras el barrido de voces.

| requisito | por qué | cómo se mide |
|---|---|---|
| **Español** | la tarjeta, la memoria y los encargos están en español | «¿capital de Francia?» → debe contener «París» |
| **Tooling** | sin `tool_calls` no hay arnés (`pi` ni red-pill) | se le da `leer_fichero` y se exige una llamada con ese nombre |
| **Multiturno** | recordar un dato dentro de la conversación | se le da 4712 y se le pregunta después, con historial |

Herramienta: `scripts/bench_admission.py`. Datos: `configs/bench/admission.yaml`.
Cada modelo se sirve igual (alias `bench`, `--jinja`, 16k) para que la comparación no se
contamine con la configuración.

## Resultado (2026-11-19)

| perfil | modelo | español | tools | multiturno | apto |
|---|---|---|---|---|---|
| `spark_x2_6_4b` | Spark 4B | sí | sí | sí | **SÍ** |
| `mimo_v26_9b` | MiMo 9B | sí | sí | sí | **SÍ** |
| `qwen35_9b` | Qwen3.5 9B | sí | sí | sí | **SÍ** |
| `granite_4_2_8b` | Granite 4.2 8B | sí | sí | sí | **SÍ** |
| `llama_32` | Llama 3.2 3B | sí | sí | sí | **SÍ** |
| `qwen3_8b` | Qwen3 8B | sí | sí | sí | **SÍ** |
| `hermes_8b` | Hermes-3 Llama 8B | sí | no | sí | no |
| `gemma_3_4b` | Gemma 3 4B | sí | no | sí | no |
| `phi_mini` | Phi-4 mini | sí | no | sí | no |
| `samantha` | samantha (Mistral 7B) | sí | no | sí | no |
| `smollm3_3b` | SmolLM3 3B | sí | no | sí | no |
| `tiny_aya_global` | Tiny Aya | sí | no | sí | no |
| `bonsai_2_27b` | Bonsai 27B (ternario) | sí | sí | sí | **SÍ*** |

\* Bonsai pasa los tres **hasta 16k** y **sólo con el fork `llama_cpp_prism`**. El llama.cpp
estándar no carga el GGUF (`failed to read tensor info`), así que en el sandbox actual no
arranca. VRAM medida: 8k→6,37 GB · 12k→6,51 GB · 16k→6,65 GB (con la GPU libre; el primer
intento a 16k falló porque Spark ocupaba 5,5 GB). Medido en host, no en el sandbox.

## Lo que este resultado NO dice

- **Un «no» en tools no es una condena.** Los seis suspensos contestan en texto en vez de
  emitir `tool_calls`. Eso puede ser **plantilla** (sin bloque de herramientas) y no
  capacidad; Hermes-3 se entrenó para function calling. Segunda pasada pendiente con
  plantilla explícita antes de descartar a nadie.
- **Multiturno aquí es dentro de la sesión.** La continuidad entre sesiones se mide con el
  ciclo de sueño y el recall (memento), no con este probe.
- **No mide calidad.** Un modelo puede pasar la puerta y ser flojo, o al revés.

## Lecciones de instrumentación (nos costaron dos falsos negativos)

1. El probe corría desde el host y no resolvía `llama` (red interna de podman): **todo
   salió «no»**. Ahora el checker se copia y se ejecuta dentro del sandbox.
2. Un modelo con plantilla de razonamiento devuelve `content` vacío si se le acaba el
   presupuesto pensando (Spark «suspendía» español con un «París» perfecto en
   `reasoning_content`). Se pide `enable_thinking=false` con fallback y warm-up.
3. Si un modelo falla, **antes de culpar al modelo** hay que descartar plantilla, ventana y
   presupuesto. Dos veces esta noche el fallo era del marco.


## Coste de la KV, medido (no estimado)

Condiciones: `-ctk q8_0 -ctv q8_0 -fa on -np 1`, RTX 5070 Laptop (8.151 MiB).

| modelo | MiB por 1k tokens | GiB por 1k | GB por 1k (decimal) | techo |
|---|---|---|---|---|
| Spark 4B | **24,2** | 0,0236 | 0,0254 | 180k |
| Bonsai 27B | **35,0** | 0,0342 | 0,0367 | 44k |

Las dos cifras del Operador eran correctas **en unidades distintas**: 0,035 GB/K para Bonsai
es 35 MiB = 0,0342 GiB (0,0367 GB decimales); 0,024-0,025 para Spark es 24 MiB = 0,0236 GiB
(0,0254 GB). Por eso conviene fijar la unidad: **MiB/1k** es la que no engaña.

El crecimiento es lineal dentro de lo medido (Bonsai: 35 MiB/1k en los cuatro tramos), así
que la regla sirve para calcular cualquier ventana:

    VRAM ≈ pesos + overhead + (ctx/1024) × MiB_por_1k

Con 8.151 MiB y ~400 MiB para el escritorio, el presupuesto útil son ~7.750 MiB.
