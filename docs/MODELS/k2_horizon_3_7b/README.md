# k2_horizon_3_7b — K2-Horizon-3.7B (candidato)

> Candidato a sustituir a `granite_8b` en el destilador de Memento. Más rápido
> (2×), mejor síntesis en español, y su defecto bloqueante —la deixis— se corrige
> con prompt: 2/5 → **5/5**. No es sustituto todavía: falta la batería completa y,
> sobre todo, la prueba de textura sobre recuerdos reales.

Perfil propuesto: `k2_horizon_3_7b` · Fichero: `K2-Horizon-3.7B-Q4_K_M.gguf`
Medido: 2026-10-29 · Origen: IFM (Institute of Foundation Models)

---

## Specs

| Campo | Declarado | Medido (GGUF) |
| --- | --- | --- |
| Contexto | 524.288 | 524.288 |
| Capas | 36 | 36 |
| Heads / kv_heads | 32 / 8 | 32 / 8 |
| Embedding / FFN | 2560 / 10240 | 2560 / 10240 |
| Vocabulario | 250.624 | 250.624 |
| rope freq base | 1e7 | 1e7 |
| Parámetros | 3,78 B core / 5,06 B con embeddings | 5.058.255.360 (safetensors) |
| Pesos Q4_K_M | — | ~2.900 MiB en VRAM |
| KV por token (f16) | — | **144 KiB** |

El vocabulario de 250.624 tokens explica la diferencia entre "3.7B" y el tamaño del
fichero: 2 × 250.624 × 2.560 = **1,28 B de parámetros solo en embeddings**.

Arquitectura propia (`k2-horizon`, `K2HorizonForCausalLM`). **Requiere
`--trust-remote-code` en Transformers y un llama.cpp con `LLM_ARCH_K2_HORIZON`**
(presente en master desde 2026-10). El `llama_cpp` 0.3.31 del venv **no lo carga**.

## Límites medidos (RTX 5070 Laptop 8 GB)

| Cuantización KV | `n_ctx` máximo | Pico VRAM |
| --- | ---: | ---: |
| f16 | **≥32.768** | 6.397 MiB |
| q8_0 | **≥49.152** (65.536 falla) | 4.831 MiB |
| q4_0 | **98.304** (131.072 falla) | 3.967 MiB |

Techo real de `q4_0`: entre 98.304 y 131.072. Los otros dos son suelos (`>=`).

## Bench (BENCHSET, 2026-10-29)

`q4_0`, `n_ctx` 32.768, n=3 por probe, temperatura 0.3. Mismos prompts y validadores
de producción que granite.

| Probe | granite | K2 |
| --- | ---: | ---: |
| `contract_entidades` | 3/3 | **1/3** |
| `contract_decision` | 3/3 | 3/3 |
| `contract_genero` | 3/3 | 3/3 |
| `needle_8k` | 3/3 | 3/3 |
| `synthesis_es` | 0/3 | **3/3** |
| **Total** | 12/15 | **13/15** |
| Latencia media | 5,3 s | **2,9 s** |

### El defecto: deixis

Los 3 fallos de `contract_entidades` son el **mismo** fallo, `no_2nd: false`:

> *"Le digo que brindo **contigo**, que esa build rc-2026.08.12 con los 42 tests
> verdes merecía algo mejor que un gin tonic."*

Los relics verbatim salen perfectos (3/3): el contenido es correcto, se le va la voz.
El prompt de producción **ya prohíbe esto** (línea 48 + BAD example); el modelo lo
ignora.

### El arreglo probado

n=5 sobre `contract_entidades`, tres brazos:

| Brazo | Deixis ok | Válido |
| --- | ---: | ---: |
| A · baseline | 2/5 (40%) | 2/5 |
| B · + bloque de recencia | **5/5 (100%)** | **4/5** |
| C · post-proceso mecánico global | 5/5 | 3/5 |

**El refuerzo por recencia funciona**: lista explícita de formas prohibidas
(`contigo, te, tu, ti…`) y su sustitución, al final del system prompt. Arregla la
deixis sin tocar el contenido.

**El post-proceso mecánico NO debe aplicarse globalmente**: reescribe ocurrencias
dentro de `relics`, que exigen ser verbatim, y rompe la validación. Si se usa, sólo
sobre `summary` y `texture`.

## Riesgo de contexto largo

Con la ventana llena de material ajeno (~31K tokens de relleno), el modelo **resume
otro documento** o entra en bucle degenerado (observado a 96K: repetición de la
propia pregunta). Aparece con las tres precisiones de KV. La ventana de 98K es
**capacidad, no capacidad de uso**: a 96K el rendimiento medido es 0–1 de 4 hechos.

## Licencia

| Campo | Valor |
| --- | --- |
| id | `apache-2.0` |
| comercial | sí |
| redistribución | sí |
| gating | no |
| fichero LICENSE en el repo | **NO** — sólo `APPENDIX.md` |
| source | https://huggingface.co/IFM/K2-Horizon-3.7B |

Apache-2.0 §4(a) exige entregar copia de la licencia al redistribuir: si el modelo se
empaqueta, hay que vendorizar el texto.

**Advertencia del fabricante, literal:** *"not optimized for moderation, refusal
behavior, or production assistant safety"* y *"documented primarily with
English-language evaluations; additional multilingual evaluation should be performed
before broad multilingual claims"*. Memento destila conversaciones privadas en
español. Se le ha observado derivar al inglés a mitad de contexto y romper la deixis
en español.

## Veredicto

**Candidato, no sustituto.** Con el refuerzo de deixis iguala o supera a granite en
4 de 5 probes y duplica la velocidad. Para cambiarlo faltan:

1. Batería completa (no sólo `--quick`) y con n≥5.
2. Estabilidad de la deixis con el refuerzo en fragmentos distintos del de prueba.
3. **Prueba de textura sobre recuerdos reales** — ver `docs/MODELS/INDEX.md`.
