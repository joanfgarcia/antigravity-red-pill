# spark_x2_6_4b — Spark-X2.6-4B (candidato)

> 4B real de XHToken, orientado a agentes on-device. **Es el mejor lector de contexto
> largo de la casa**: 262.144 de ventana con `q4_0` (y 117.676 verificados con
> recuperación correcta) en 3,5 GB. No es destilador: sin razonamiento falla un desliz
> de deixis. No es de herramientas: llama bien a una, no encadena.

Perfil propuesto: `spark_x2_6_4b` · Fichero: `Spark-X2.6-4B-Q4_K_M.gguf` (3,54 GB)
Runtime: **llama.cpp stock** (arch `spark2_5`) · Medido: 2026-10-30

---

## Specs

| Campo | Valor |
| --- | --- |
| Arquitectura | `Spark2_5ForCausalLM` (`spark2_5`) |
| Capas / heads / kv_heads / head_dim | 36 / 16 / **4** / **256** |
| Hidden / ffn | 2560 / 10240 |
| Vocabulario | 131.072 (con `tie_word_embeddings`) |
| Parámetros calculados | **~4,1 B** reales (sin el truco de embeddings de K2) |
| Contexto declarado | **1.048.576** |
| Licencia | Apache-2.0, sin gating (179K descargas en 11 días) |
| Thinking | 3 niveles: `none` / `low` / `high` |

**Runtime:** llama.cpp master lo soporta (`spark2_5` en `libllama.so`), pero
**`llama-cpp-python` 0.3.31 del venv no** → va por el camino de binario (AD-049), con
el provider de fork ya construido. No necesita el fork prism: el stock basta.

## Límites reales (RTX 5070 Laptop 8 GB) — sondeado **hasta el OOM**

| KV | Último que arranca | Primero que falla | VRAM al último |
| --- | ---: | ---: | ---: |
| f16 | **114.688** | 131.072 | 7.341 MiB |
| q8_0 | **163.840** | 196.608 | 6.979 MiB |
| q4_0 | **262.144** | 327.680 | 6.965 MiB |

**KV real: ~13-14 KiB por token.** Calculado desde el `config.json` daba **144 KiB**
— diez veces más. La arquitectura usa un esquema de atención mucho más barato de lo
que sugieren `kv_heads × head_dim`, y el config no lo declara. Lección: el KV se mide
por consumo de VRAM, no se deduce del config.

## Calidad (BENCHSET, `q4_0` @ 16.384, n=3)

| Probe | reasoning OFF | reasoning ON (budget 4096) |
| --- | :-: | :-: |
| `contract_entidades` | **2/3** | **3/3** |
| `contract_decision` | 3/3 | 3/3 |
| `contract_genero` | 3/3 | 3/3 |
| `needle_8k` | 3/3 | 3/3 |
| `synthesis_es` | 3/3 | 2/3 |
| **Total** | **14/15** | **14/15** |
| Latencia media | **~3 s** | **~58 s** |

**El razonamiento arregla la deixis** (2/3 → 3/3) y cuesta **~10×** de latencia.
Misma puntuación total; lo que cambia es dónde falla.

## Contexto largo (lo que lo hace único aquí)

```
prompt de 117.676 tokens (449.540 chars), dato enterrado al 50% de profundidad
→ 56,9 s de prefill, respuesta correcta: '774219'
→ 5 GB de VRAM en total
```

Comparado con el K2-3.7B, que tiene 98K de ventana pero **resume otro documento** a
partir de ~46K de relleno. Aquí la recuperación aguanta a 117K.

## Herramientas: el multiturno SÍ funciona (el que fallaba era el arnés)

**Corrección del 2026-10-30.** El `multi_step` del bake-off pedía **dos llamadas
en UNA respuesta** (`_validate_multi_step`: `len(set(calls)) >= 2`) y **nunca
devolvía el resultado de la herramienta** al modelo. Eso no mide multiturno, mide
paralelismo. Spark llamaba `list_dir`, esperaba y paraba — que es exactamente lo
correcto — y el arnés lo contaba como fallo.

Con un bucle de verdad (`scripts/tool_loop_probe.py`: `tools` → `tool_calls` →
`role: tool` con el resultado → repetir):

| Escenario | Pasos | Responde | ¿Usa el resultado devuelto? |
|---|:-:|:-:|:-:|
| Buscar los `async` de `src/` | 2 (`list_dir` → `grep`) | sí | **sí** (`foo`, `bar`) |
| "¿cuántas funciones async hay?" | 2 | sí | **sí** |
| "mira `src/a.py`" | 1 (`read_file`) | sí | **sí** |

0,2-0,4 s por vuelta. **Encadena, usa el contenido que se le devuelve y cierra.**
Ni era el modelo ni era el template de llama.cpp (que renderiza `role: tool` bien
y parsea su `<tool_call>` con `<arg_key>`/`<arg_value>` sin ayuda).

Lo del "formato" era real pero de otra capa: el fabricante valida en vLLM con
`--tool-call-parser spark25`, que llama.cpp no tiene; el parser genérico basta,
como demuestra la tabla.

## Herramientas (bake-off original, para el registro histórico): 4/5

| Probe | Resultado |
| --- | --- |
| `simple` | ✅ 0,7 s |
| `multi_sel` | ✅ 0,6 s |
| `json_args` | ✅ 22,0 s (49,6 s con thinking) |
| `no_tool` | ✅ 11,1 s |
| **`multi_step`** | ❌ **no encadena** |

Llama bien a **una** herramienta, con nombre y argumentos correctos. Falla al
encadenar: pide `list_dir` y se para. **Con y sin thinking, mismo fallo.**

No es problema de parser: llama.cpp lee su formato `<tool_call>` con argumentos
etiquetados sin problema (de ahí los 4 aciertos). El fabricante valida en vLLM con
`--tool-call-parser spark25`, que llama.cpp no tiene — así que la comparación no es
perfecta, pero en nuestro runtime el encadenado no ocurre.

## Veredicto

**Se queda como lector de contexto largo. No como destilador ni como minion_tool.**

| Papel | Veredicto |
| --- | --- |
| Lector de contexto largo | **Mejor de la casa** (262K, 13 KiB/token, 117K verificados) |
| `distill` (Memento) | No: empata a 14/15 con bonsai pero falla deixis sin thinking, y la voz la decide bonsai |
| `minion_tool` | No todavía: falla el encadenado |

**Pendiente:** `multi_step` con más repeticiones (un intento no basta), calidad de
síntesis a ventana llena, y `synthesis_es` con thinking (falla 1 de 3 por cobertura).

## Por qué NO es el destilador de esta noche (2026-10-30)

Medido en los tres probes de contrato, que es la forma de la tarea de destilado:

| Modelo | tok generados | seg | tok/s |
| --- | ---: | ---: | ---: |
| `granite_8b` (titular) | 258 | 4,6 | 55,6 |
| `bonsai_2_27b` (off) | 265 | 6,2 | 42,5 |
| **`spark` (off)** | 295 | **3,7** | **79,0** |
| **`spark` (thinking 4096)** | **4.276** | **50,4** | 84,8 |

**El thinking no lo hace lento: lo hace verboso.** Es el más rápido en tok/s de los
cuatro y aun así tarda 11× más, porque escribe **14× más tokens** para la misma
respuesta. Con el ciclo nocturno a ~5 s por fragmento, eso convierte una noche en once.

Sin thinking es **más rápido que granite** (3,7 s vs 4,6 s), pero falla un desliz de
deixis (2/3).

### Palanca pendiente

`--reasoning-budget 4096` fue el techo: escribió 4.276. Con budgets de **512 / 1.024 /
2.048** el coste bajaría a 12-15 s por fragmento. **Falta medir si mantiene la deixis
3/3 a ese precio** — es la prueba que decide si Spark puede destilar de noche.

## El presupuesto de razonamiento: 15/15 a 7 s (2026-10-30)

El modelo "rumiaba" demasiado: con thinking libre escribía **19.571 caracteres de
traza** y **no dejaba sitio a la respuesta** (contenido vacío, `finish_reason=length`).
La tarjeta documenta tres niveles (`none` / `low` / `high`) con dos variables de
plantilla, `enable_thinking` y `reasoning_effort`. Probadas, con el mismo probe y
6.144 tokens de presupuesto:

| Ajuste | Latencia | Traza | Respuesta |
|---|---:|---:|---|
| `enable_thinking: false` | 5,1 s | 0 chars | válida (387 tok) |
| **`reasoning_effort: low`** | 74,8 s | 19.571 chars | **vacía** |
| `reasoning_effort: high` | 76,1 s | 19.648 chars | **vacía** |

**`reasoning_effort` es un no-op en este runtime**: `low` y `high` dan exactamente
lo mismo. Lo que sí muerde es el **tope duro de traza** de llama.cpp
(`--reasoning-budget`):

| `--reasoning-budget` | Latencia | Traza | Válido |
|---:|---:|---:|:-:|
| (sin tope) | 75 s | 19,6 KB | **no** |
| 256 | **8,5 s** | 876 chars | sí |
| 512 | 12,0 s | 1,8 KB | sí |
| 1024 | 17,2 s | 3,6 KB | sí |
| 2048 | 35,5 s | 6,6 KB | sí |

Y con **256**, el BENCHSET completo (n=3):

| Probe | Resultado | Latencia |
|---|:-:|---:|
| `contract_entidades` | **3/3** | 7,9 s |
| `contract_decision` | **3/3** | 6,8 s |
| `contract_genero` | **3/3** | 6,6 s |
| `needle_8k` | **3/3** | 2,8 s |
| `synthesis_es` | **3/3** | 5,6 s |
| **TOTAL** | **15/15** | **~7 s** |

**El mejor resultado de la casa**, empatado con K2-7B y a la mitad de su coste de
memoria (3,5 GB), con la deixis arreglada: el 2/3 de "sin thinking" era el modelo
rumiando en plaza. Configuración, no código:

```yaml
extra_server_args: ["--reasoning", "on", "--reasoning-budget", "256"]
```

Cautela: n=3 por probe y una sola configuración medida. El 15/15 es firme como
medida de hoy; el *óptimo* de budget (256 vs 1024) no está sondeado.

**Estos valores son de ESTE puesto** (RTX 5070 Laptop, 8 GB, GPU). El tope de
traza reparte presupuesto entre pensar y responder, y ese reparto cambia con el
modelo, el prompt y el motor: en otra máquina hay que buscar la curva (ver
`PROCEDURE.md` GP-3b). El síntoma de un tope demasiado alto es una **respuesta
vacía**, no un error. En iGPU o CPU no se ha medido y no se publica.
