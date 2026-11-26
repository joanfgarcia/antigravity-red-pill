# bonsai_2_9b — Ternary Bonsai 2 9B (PTQ1_0)

> El intermedio de la familia Bonsai 2: base Qwen3.5-9B, 2,00 GB de pesos,
> 262.144 de contexto declarado. Medido: 2026-11-25.

Perfil: `bonsai_2_9b` (+ `bonsai_2_9b_instruct`) · Fichero:
`Ternary-Bonsai-2-9B-PTQ1_0.gguf` · Runtime: `llama_cpp_prism` `b12178`.

---

## Specs

| Campo | Valor |
| --- | --- |
| Parámetros | ~8,95B LM (32 bloques, hidden 4096) + ~0,46B torre de visión |
| Cuantización | ternaria g128, ~1,78 bpw, PTQ1_0 (2,00 GB) |
| Base | Qwen3.5-9B, atención híbrida 3 lineal : 1 completa |
| Contexto declarado | 262.144 |
| Drafters | MTP (`-MTP-Q8_0`, profundidad 2) y DFlash2 (código) |
| Licencia | Apache-2.0 |

## Techos de contexto MEDIDOS (RTX 5070 Laptop 8 GB, 7500 MiB)

| KV | MiB/1k | techo físico verificado |
| --- | ---: | ---: |
| `q8_0` | 16,6 | **299k** |
| `q4_0` | 8,8 | **537k** |
| `pq2_0m` | 4,4 | **553k** |

**El límite real es el del modelo, no la VRAM**: con `q8_0` el techo físico
(299k) supera los 262.144 declarados, así que este 9B es el único del elenco que
puede llevar la ventana completa en este portátil. Falta comprobar **calidad** a
ventana llena (needle), no sólo que arranque.

## BENCHSET v1 (2026-11-25)

| variante | contratos | needle 16k/8k | síntesis | latencia |
| --- | :--: | :--: | :--: | --- |
| thinking (defecto) | 0/3 | 1/2 | 5/8 | 10–65 s |
| off con sampler de thinking | 2/3 | 2/2 | 4/8 | 2–8 s |
| instruct (T0.7) | 3/3 | 2/2 | 5/8 | 2–8 s |

Subconjunto común con el resto del elenco (3 contratos + síntesis): **3/4**
(2.5-instruct 4/4, K2 4/4, Spark 4/4).

### El modo thinking se ahoga
En `contract_entidades` y `contract_genero` generó **20.659 y 21.410 caracteres**
de razonamiento y **no llegó a emitir el JSON** (`reason: no JSON`). Es la
patología de sobre-razonamiento que Bonsai 2.5 corrige en el 27B; aquí sigue.

### Vocabulario
No conoce "engrama" (lo interpreta como "enigma/adivinanza"), con y sin thinking.
El prompt congelado del benchset no usa el término y en producción sólo aparece
en docstrings, así que no contamina el carril — pero avisa del techo conceptual
del 9B en jerga propia.

## Veredicto

**Candidato a lector de contexto largo, no a destilador.** Con instruct es
rapidísimo (2–8 s) y hace 3/3 contratos, pero la síntesis se queda en 5/8 hechos
(umbral 6) y no supera a K2/Spark en el subconjunto común. Su baza es la ventana:
262K completos con `q8_0` frente a los 112k del 27B con `pq2_0m`.

**Pendiente:** needle a ventana llena (¿aguanta 200k+?) y prueba de textura si se
le quiere dar carril.

## Batería de techo (`bench_hard`, 2026-11-26)

12 tareas en 5 familias, gradación por estado del fixture, `n=3`, brazo nulo por
pasada. Config: `n_ctx` 65.536, KV `q8_0`, `--reasoning on --reasoning-budget 2048`.

| modelo | pass^1 | pass^3 | instrucción | p50 | p95 | timeouts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Bonsai 2 9B** | **86,1%** | 66,7% | **90%** | **9,0 s** | **61,5 s** | **0** |
| Bonsai 2.5 27B (ctx 32k, budget 2048) | 80,6% | 58,3% | 81% | 83,0 s | 900,1 s | 8 |
| Spark-X2.6-4B (referencia) | 69,4% | 66,7% | 75% | 27,3 s | 457,2 s | 4 |

Brazo nulo: **0/108 pass y 0/216 instrucciones** → la batería discrimina.

| familia | **9B** | 2.5 27B | Spark |
| --- | ---: | ---: | ---: |
| cadena | 8/9 | **9/9** | **9/9** |
| restricciones | 6/9 | **8/9** | 3/9 |
| memoria | **8/9** | 7/9 | 6/9 |
| ventana | **6/6** | 3/6 | 4/6 |
| recuperación | **3/3** | 2/3 | **3/3** |

- **Gana la batería**: mejor pass^1, mejor instrucción y **cero timeouts**, a 9 s
  de p50. `d2` (agregar etiquetas en ~19k) **3/3** frente al 0/3 del 27B.
- Sus fallos son de **política y formato**, no de capacidad: `c2` contestó el
  código viejo (`K7-1990`) 1/3; `a3` una vez describió el fichero en prosa en vez
  de escribirlo; `b2` 1/3 envolvió el JSON en texto; `b1` 2/3 (57 palabras una vez,
  y sin la frase de cierre que pedía el fixture).
- Ventana medida aquí: 19–21k. **No sustituye al needle de ventana llena**, que
  sigue pendiente.

**Actualización del veredicto:** en coste/calidad es el mejor de los tres en esta
batería, pero sigue sin ser destilador (síntesis 5/8 en BENCHSET). Candidato a
lector largo y a carril agéntico ligero.

## Peculiaridades
- Pide `presence_penalty 1.0` en thinking (1.5 sin thinking), **al contrario que
  el 27B**. Va como default de servidor: `conduct._SAMPLER_KEYS` no la reenvía.
- `min_p 0.0` explícito, igual que el resto de la familia 2.5.
- Drafters: MTP con profundidad 2 es la recomendación de la doc para este tamaño.
