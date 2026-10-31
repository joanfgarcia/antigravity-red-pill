# Cómo medir un modelo antes de adoptarlo

> Procedimiento para decidir si un modelo entra en el elenco local. Nace de la
> auditoría del 2026-10-29 (K2-Horizon vs Granite-4.1), donde se descubrió que los
> dos procedimientos previos no cubrían **la cuantización de KV** y que el runtime
> de producción nunca la ha usado, aunque el arnés de bench sí.
>
> El objetivo no es puntuar modelos: es saber **qué ventana sirve de verdad esta
> máquina** y **dónde deja de poder usarse**.

Status: vigente. Scope: modelos GGUF locales servidos por llama.cpp.

---

## 0. Qué cubre y qué no

| Documento | Cubre |
| --- | --- |
| `docs/TECHNICAL/COGNITIVE/DISTILLER_SELECTION.md` | Qué modelo elige la tarea (bakeoff de capacidad) |
| `docs/2026-08-13-MODEL-BAKEOFF.md` §4 | Cómo medir el encaje (pesos, pico de VRAM, cascada) |
| **este documento** | **Límites por cuantización de KV + higiene estadística** |

Los tres son complementarios. Este NO sustituye al bakeoff de tarea: lo precede y
lo condiciona (si el modelo no cabe, la puntuación es irrelevante).

---

## 1. Specs declaradas — 5 minutos, sin GPU

Antes de descargar nada grande: leer la cabecera del GGUF. No hace falta servidor.

```bash
python3 scripts/gguf_info.py models/<fichero>.gguf
```

Campos que importan y por qué:

| Campo GGUF | Para qué |
| --- | --- |
| `general.architecture` | ¿La soporta el binario? Comprobarlo **antes** de compilar/servir |
| `*.context_length` | Lo que el fabricante **promete**, no lo que cabe |
| `*.block_count` / `attention.head_count` / `head_count_kv` | Entran en el cálculo de KV (§2) |
| `*.rope.freq_base` | Cuánto se estiró la ventana en entrenamiento |
| `tokenizer.ggml.tokens` (longitud) | Explica el tamaño real de los embeddings |

Contrastar con la ficha oficial (Hugging Face `config.json` + model card). Si el
GGUF y la ficha discrepan, manda el GGUF: es lo que se va a cargar.

**Caso real:** K2-Horizon-3.7B declara 524.288 de contexto y pesa como un 5B. No es
un error: 250.624 tokens de vocabulario × 2 × 2.560 = 1,28 B de parámetros solo en
embeddings. El "3.7B-core" es cierto; el resto es diccionario.

---

## 2. KV por token — aritmética, sin servidor

El coste real de la ventana no está en los parámetros. Está aquí:

```
bytes_por_token = 2 × capas × kv_heads × head_dim × bytes_por_dato
```

`2` = K y V. `bytes_por_dato` = 2 (f16), 1 (q8_0), 0,5625 (q4_0 en bloques de 32).

| Modelo | f16 | q8_0 | q4_0 |
| --- | ---: | ---: | ---: |
| K2-Horizon-3.7B (36 capas, 8 kv) | 144 KiB | 76 KiB | 40 KiB |
| Granite-4.1-8B (40 capas, 8 kv) | 160 KiB | 85 KiB | 45 KiB |

A 512K tokens, K2 en f16 pediría **72 GiB** de KV frente a **9,4 GiB** de pesos. La
ventana cuesta 8× más que el modelo. Esto se sabe sin encender la GPU y decide de
antemano si una ventana es siquiera planteable.

---

## 3. `n_ctx` máximo **por cuantización de KV** — el hueco que faltaba

Los procedimientos previos medían la cascada solo en `f16`, por prueba y error de
picos. Resultado: subestimación de hasta 4× en esta máquina.

### Procedimiento

Para cada cuantización (`f16`, `q8_0`, `q4_0`), sondeo **descendente** de candidatos:

1. Arrancar `llama-server` con `-c <n> -ctk <q> -ctv <q> -fa on -ngl 99`.
2. Esperar `/props`. **Si el proceso muere, ese `n` no cabe** — no esperar el
   timeout completo: comprobar `kill -0 $PID` en cada iteración.
3. El primer `n` que arranca se registra. Bajar el candidato y repetir.
4. Al terminar, matar el servidor. Nunca dejar dos cargados.

### Advertencia metodológica

El sondeo descendente **para en el primero que arranca**: eso es un **suelo**, no un
máximo. Si se publica como "máximo", se miente. Escribir siempre `>=`.

Para tener techo real hacen falta dos valores: uno que arranca y el siguiente que
falla. Entonces se escribe el rango, no un número.

### Resultado esperado (RTX 5070 Laptop 8 GB, 2026-10-29)

| Modelo | f16 | q8_0 | q4_0 | Declarado |
| --- | ---: | ---: | ---: | ---: |
| Granite-4.1-8B | 12.288 | 24.576 | 49.152 | 131.072 |
| K2-Horizon-3.7B | ≥32.768 | ≥49.152 | 98.304 | 524.288 |

**Conclusión estructural:** la ventana servible es el 9–19% de la declarada, y la
cuantización de KV multiplica por 3–4 el techo. Cualquier tabla de perfiles que solo
tenga una columna `n_ctx` está midiendo el peor caso y congelándolo.

---

## 4. Calidad — aquí se rompe todo

Tres trampas que han producido conclusiones falsas en esta auditoría. Las tres me
mordieron a mí el mismo día.

### 4.1 La trampa de `max_tokens`

Un marcador que busca cadenas concretas en la respuesta **mide también la
verbosidad**. Si el modelo razona antes de responder, agota el presupuesto y la
respuesta se corta: parece un fallo de conocimiento y es un fallo de longitud.

- **Obligatorio:** registrar y revisar `finish_reason`. Si es `length`, la medición
  no vale: subir `max_tokens` y repetir.
- **Obligatorio:** registrar `completion_tokens` por corrida. Un salto de 270 a 780
  tokens entre dos configuraciones cambia el significado del marcador.

### 4.2 Una muestra no es una medición

`n=1` produjo rankings que se invirtieron con `n=5`. Con temperaturas 0 la varianza
no desaparece: `sd` llegó a 1,34 sobre 4 y hubo configuraciones con `sd=0` y media 1.

- **Obligatorio:** `n>=5` por celda, y publicar media **y** `sd`.
- Si `sd` es del orden de la diferencia entre configuraciones, **no hay conclusión**.

### 4.3 El confound de orden y caché de prefijo

El mismo prompt, byte a byte, dio respuestas distintas entre arranques distintos del
servidor (caché de prefijo, orden de peticiones, lotes). En una tanda, f16 resumió el
documento equivocado; en otra, con el mismo prompt, identificó el correcto 5/5.

- **Obligatorio:** aleatorizar el orden de las configuraciones, o servir cada una
  desde un proceso limpio y con el mismo orden interno.
- **Obligatorio:** declarar el orden usado.

### 4.4 Qué NO se puede concluir hoy

Con estas condiciones, **no está demostrado** que la cuantización de KV degrade la
calidad en el rango donde el modelo funciona. Lo medido: a `n_ctx` 24.576 las tres
configuraciones dan resultados idénticos; al llenar la ventana (~31K con relleno) el
comportamiento es inestable con todas.

El fallo dominante observado **no es precisión, es selección de documento**: con la
ventana llena de material ajeno, el modelo resume otro documento o entra en bucle.
Ese fallo aparece en las tres precisiones.

---

## 5. Cumplimiento de tarea (BENCHSET)

Para la tarea concreta que vaya a desempeñar el modelo:

```bash
PYTHONPATH=src .venv/bin/python scripts/bench_local.py --models <perfil> --quick
```

Probes: `contract_*` (JSON estricto con relics verbatim y deixis), `needle_8k`,
`synthesis_es`. Reutilizar **los validadores de producción**, no reinventarlos.

Si el modelo no lo carga el `llama_cpp` del venv (arquitecturas nuevas), servirlo con
el binario de `llama.cpp` y pasar los mismos validadores por HTTP — el prompt
congelado y el contrato son lo que da comparabilidad, no el transporte.

---

## 6. Licencia — cuatro preguntas

1. ¿Licencia declarada en la ficha **y** en los metadatos del repo? (deben coincidir)
2. ¿Hay fichero `LICENSE` en el repo? Apache-2.0 §4(a) exige entregar copia.
   **K2-Horizon no lo trae.**
3. ¿Comercial y redistribución? Declararlo en el bloque `license:` del perfil.
4. ¿Tiene condiciones de uso más allá de la licencia? Leer el `APPENDIX` o equivalente.

**Defecto conocido de nuestra capa:** `_KNOWN_LICENSES["apache-2.0"]` tiene
`attribution_required: False`. Apache-2.0 §4(b) exige conservar el `NOTICE` al
redistribuir. Para uso personal es irrelevante; para empaquetar modelos, no.

Y una regla que no es de licencia pero decide igual: **si el fabricante dice para qué
no sirve, hay que leerlo**. K2-Horizon declara *"not optimized for moderation,
refusal behavior, or production assistant safety"* y *"documented primarily with
English-language evaluations"*. Hoy se le ha visto fallar justo en deixis y derivar
al inglés. El aviso del fabricante predijo nuestros fallos.

---

## 7. Dónde se registra

Una carpeta por modelo, con la ficha autocontenida:

```
docs/MODELS/<perfil>/
    README.md     ← veredicto, specs declaradas vs medidas, licencia, bench
```

`<perfil>` = el id de `model_profiles.yaml`, para que el documento y el runtime
hablen del mismo objeto. Índice en `docs/MODELS/INDEX.md`.

Tamaño máximo de la ficha: **15 KB**. Es el mismo criterio que el planner aplica a
sus documentos: si un modelo de 9B no puede leer dos fichas a la vez, la ficha es
demasiado larga para servir de nada.

---

## 8. Checklist para añadir un modelo al elenco

Ningún modelo entra por «cabe y responde». El caso `bonsai_2_27b` (2026-10-29) costó
una purga fallida por saltarse el paso GP-1 y un diagnóstico de latencia equivocado
por saltarse GP-5.

### GP-1 · ¿Lo puede servir el runtime de PRODUCCIÓN?

Medir con un binario no es medir en producción. Comprobar el formato de cuantización
contra el runtime real del daemon:

```bash
python3 scripts/gguf_info.py modelo.gguf | grep file_type
grep -c "ptq1_0" .venv/lib/python*/site-packages/llama_cpp/lib/libggml-base.so.0   # 0 = no lo lee
```

`llama-cpp-python` del venv **no conoce** las extensiones de fork (`PTQ1_0`, `PQ2_0`).
Un modelo en formato de fork exige:

- un `kind` de provider que lance el binario del fork (ver `runtimes.yaml`), **o**
- renunciar a servirlo por el daemon.

Precedentes: `BitNetInferenceProvider`, `FastFlowLMInferenceProvider`. Falta el de
binarios de fork (`llama_cpp_prism`, `llama_cpp_xdna`).

### Formatos: el binario de producción decide, no la moda

| Formato | Contenedor | Lo sirve | Cuándo tiene sentido |
| --- | --- | --- | --- |
| `GGUF` Q4/Q5/Q6/Q8 | GGUF | llama.cpp (stock o fork) | **Por defecto en este puesto**: KV cuantizable, control de contexto, tool parsing por jinja |
| `GGUF` `PTQ1_0` / `PQ2_0` / `i2_s` | GGUF | solo el fork del fabricante | Ternarios: mucho parámetro por byte. Exige provider de binario (AD-049) |
| `FP8` | safetensors | vLLM / SGLang | Datacenter. Mismo tamaño que `Q8_0` en un 4B; aquí no aporta |
| `INT8` `compressed-tensors` | safetensors | vLLM / transformers | W8A8: también cuantiza **activaciones**. Ventaja de velocidad con tensor cores INT8, pero solo en vLLM |
| `AWQ` / `GPTQ` | safetensors | vLLM / exllama | 4 bits con calibración. Sin ventaja frente a `Q4_K_M` aquí |

**Regla:** comparar formatos **con la misma VRAM y el mismo modelo**, y descontar el
runtime. Un `INT8` de 4,45 GB y un `Q8_0` de 4,38 GB ocupan lo mismo; la diferencia
está en si el binario de producción sabe cargarlos.

Caso real (2026-10-30): `Spark-X2.6-4B` tiene GGUF, FP8 e INT8. Se usa GGUF porque es
el único que sirve llama.cpp, que es lo que corre en producción; FP8 e INT8 exigirían
vLLM, que no está desplegado en un portátil de 8 GB.

### GP-2 · `flash_attn` declarado (AD-037)

Sin `flash_attn: true` **y** `fa_capable: true` en el perfil, el daemon lo resuelve a
`auto` y puede correrlo **sin Flash Attention**: menos ventana útil y más lento. El
caso de AD-037 fue un OOM en el scratch de prefill que parecía «contenido venenoso».

### GP-3 · Conducta: medir con y sin razonamiento

**Presupuesto de salida acorde a la conducta.** Los `max_tokens` del BENCHSET están
calibrados para modelos sin razonamiento. Con thinking activo, el modelo se gasta el
presupuesto entero razonando y el JSON no llega: `Spark-X2.6-4B` generó 2.547 tokens
en una sola petición de contrato y hubo que abortar la tanda (2026-10-30). Antes de
medir con thinking: subir `max_tokens` (×2-3) o acotar con `--reasoning-budget`.

Un modelo de razonamiento sin `reasoning off` multiplica la latencia. `bonsai_2_27b`:
misma puntuación con y sin thinking, **7× más lento con él**. Declarar en el perfil qué
conducta usa el carril, no la que trae el template.

### GP-3b · Niveles de razonamiento — calibrar `max` en ESTA máquina

Los perfiles exponen cuatro niveles estándar (`low|medium|high|max`, default
`medium`; `low` = sin thinking). El perfil **declara a qué flags equivale cada
nivel en su runtime**; el código solo traduce. Dos cosas que hay que medir aquí,
no copiar de nadie:

**1. `max` es el que engaña.** Un tope demasiado alto no da "más calidad": deja al
modelo sin presupuesto y devuelve **`content` vacío con `finish_reason=length`**.
Medido el 2026-10-30 con Spark-X2.6-4B: sin tope → 19,6 KB de traza, respuesta
vacía, 75 s. Con 256 → respuesta válida y **15/15** en el BENCHSET a ~7 s.

El valor de `max` se busca con la curva, no a ojo:

| `--reasoning-budget` | Latencia | Traza | Respuesta |
|---:|---:|---:|:-:|
| 256 | 8,5 s | 876 chars | válida |
| 1024 | 17,2 s | 3,6 KB | válida |
| 2048 | 35,5 s | 6,6 KB | válida |
| sin tope | 75 s | 19,6 KB | **vacía** |

Se baja hasta que la respuesta vuelve a salir válida y se sube hasta que deja de
mejorar. **El síntoma de un `max` mal puesto es una respuesta vacía, no un error.**

**2. Los valores de este repo son ORIENTATIVOS.** Están medidos en el puesto del
operador (RTX 5070 Laptop, 8 GB, 2026-10-30). El reparto entre traza y respuesta
depende del modelo, del prompt y del motor, no solo de los tokens: **cada máquina
tiene que buscar su curva** con el método de arriba. Un `max: 4096` copiado de
aquí puede dejar sin respuesta a un modelo en otro equipo.

**Alcance: GPU.** Estos números se miden y se publican para GPU. En iGPU o CPU el
reparto cambia por completo —y el driver puede no soportar el modelo— así que
esos carriles quedan fuera de esta guía hasta que se midan por separado.

### GP-4 · Latencia en **tok/s**, no en segundos

Los segundos absolutos engañan: dependen de cuánto escriba el modelo. `bonsai_2_27b`
parecía 7× más lento que el 3.7B y es un 25% más lento que el titular (40,5 frente a
53,9 tok/s) midiendo la misma tarea.

### GP-5 · Límites por cuantización de KV

Sección 3 de este documento. Siempre `>=` cuando el sondeo no encontró el techo.

### GP-6 · Ficha, licencia y **carril**

Un perfil sin carril no se usa nunca. `bonsai_2_27b` estuvo a punto de purgarse porque
nadie lo había medido: parecía inservible cuando solo estaba sin asignar. **Ningún
modelo entra sin decir qué tarea lo va a pedir.**

