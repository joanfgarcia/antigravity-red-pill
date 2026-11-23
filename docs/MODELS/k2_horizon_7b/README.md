# k2_horizon_7b — K2-Horizon-7B `Q5_K_M`

> **15/15 en el benchset y deixis 3/3**: el mejor del elenco en esa batería, por
> delante de granite (12/15) y del 3.7B (13/15). Es además **default del kernel**
> en tres sitios —síntesis de hubs del sueño, motor por defecto del ladder de
> minions y motor de `memento_cata`— y hasta hoy era el único de los seis con
> pesos y carril activo que no tenía ficha.

Perfil: `k2_horizon_7b` · Fichero: `K2-Horizon-7B-Q5_K_M.gguf` (6,1 GB)
Los pesos viven en `~/opt/k2-bench/models/`, **no** en `~/.local/share/red-pill/models/`:
una cosa es la ficha y otra dónde están los pesos.
Medido: 2026-10-29 → 2026-11-19 · Origen: IFM (Institute of Foundation Models)

---

## Dónde se usa (es default, no candidato)

| Sitio | Qué |
|---|---|
| `src/red_pill/config.py:1277` | `SLEEP_HUB_LARGE_MODEL` — síntesis de hubs del ciclo de sueño |
| `scripts/autonomy_ladder.py:55` | `MINION_DEFAULT_PROFILE` — motor por defecto del ladder |
| `scripts/memento_cata.py:70` | `--engine` por defecto de la cata de notas |
| `configs/jobs/hub_bakeoff*.yaml`, `minion_ladder.yaml`, `validate_judge_bench.yaml` | modelo bajo prueba |

Que sea el defecto con tres carriles activos es el argumento de esta ficha: un
default sin ficha es una decisión que nadie puede auditar.

## Coste en este puesto (RTX 5070 Laptop 8 GB)

| Métrica | Valor | Cómo |
|---|---|---|
| Pesos en VRAM | **6.166 MiB** | `load_tensors`, fork `llama_cpp_k2` |
| Overhead | 330 MiB | perfil `vram_footprint` |
| KV `q8_0` | **35 MiB/1k** — lineal | medido 2026-11-19 (fork prism) |
| KV `f16` / `q4_0` | 66 / 18 MiB/1k | `bytes_per_token_kib` del perfil |
| Prefill | **2.217 tok/s** | 2026-10-30, KV `q8_0`, 10k |
| Decode | **58 tok/s** | mismo run |
| Carga en frío | ~10 s (CUDA) | `load_time_s` del perfil |
| `n_ctx` de afinidad | 10.240 | perfil (`hardware_affinity`) |

## Ventana de contexto

Medido con KV `q8_0` y verificación por arranque (2026-11-19):

| `n_ctx` | 8.192 | 12.288 | 16.384 | 32.768 | 40.960 | 45.056 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| VRAM | 6.370 | 6.510 | 6.650 | 7.210 | 7.490 | 7.630 MiB |

**Techo `q8_0`: 45.056** — 49.152 falla al crear contexto. No es VRAM agotada, es
el límite del arranque en este puesto.

⚠️ **Incoherencia anotada, pendiente de cerrar:** la tabla del elenco
(`INVENTORY.md`, ficha de `bonsai_2_27b`) da este modelo a **40.960 con KV
`q4_0`**, que no puede ser menor que el `q8_0` medido (45.056). O la etiqueta de
esa columna está mal, o la medida es de otro binario. Se conserva aquí el `q8_0`
verificado y **no se publica un techo `q4_0`** hasta re-medirlo.

## Benchset — 15/15

Mismo BENCHSET que el resto del elenco (n=3 por probe):

| Modelo | Puntuación | Deixis |
| --- | :-: | :-: |
| **K2-Horizon-7B `Q5_K_M`** | **15/15** | **3/3** |
| `bonsai_2_27b` | 14/15 | 3/3 |
| K2-Horizon-3.7B | 13/15 | 1/3 |
| `granite_8b` (titular del sueño) | 12/15 | 3/3 |

Es el mejor de la batería y el único con **15/15 y deixis perfecta a la vez**. Lo
que lo deja sin título no es el benchset: es la textura.

## Textura sobre recuerdos reales (2026-10-29, 9 pares)

| Modelo | JSON | Vallas | 3ª persona | Escena inventada | Relics |
| --- | :-: | :-: | :-: | :-: | :-: |
| `bonsai_2_27b` | 9/9 | 0 | **0** | **1** | 27 |
| K2-Horizon-7B `Q5_K_M` | 9/9 | 0 | 1 | 6 | 29 |
| `granite_8b` | 8/9 | 2 | 12 | 7 | 41 |

Pierde el título por **6 escenas inventadas** frente a 1 de `bonsai`: en un
recuerdo, pintar atmósfera que no estaba en la fuente no se puede permitir. La
voz la firma el Operador en pares ciegos (`TEXTURE_MIMO_VS_BONSAI.md`), no la
tabla.

## Síntesis de hubs (2026-11-08)

Prompt map-reduce AD-113, `task=hub`, input real, sin escritura:

| Variante | n | ok | schema | coverage | Latencia |
| --- | ---: | :-: | :-: | ---: | ---: |
| `k2_horizon_7b` | 3 | 3/3 | 0/3 | 0.322 | 178,4 s |
| `…_concise` | 3 | 3/3 | 0/3 | 0.389 | 148,6 s |
| `…_concise_synth400v2` | 3 | 3/3 | **3/3** | 0.344 | 196,2 s |

El contrato (`schema_valid`) sólo se cumple con el prompt `synth400v2`; con el
prompt base responde pero no valida. **Ninguna fila trunca**: la compactación es
por síntesis, no por corte.

## Prompt de anotar `v3` (2026-10-30)

Con la v2 —la de granite— el **45 %** de sus notas titulaban «Joan me pide/cuenta…»
y el defecto se perdía dentro del episodio; granite daba 0 % con la misma v2. La
v3 pide el **acto**, no la escena. Es `annotate_prompt_set: v3` en el perfil y es
lo que lo hace juez del carril `annotate`.

## Lo que NO está medido

- **e2e de minion** con perfil real (varias vueltas, herramientas del repo): el
  paso que falta para subirle la prioridad en la cascada.
- **Calidad a ventana llena**: 45k es techo físico, no ventana útil. A 96k el
  3.7B bajó a 0–1 de 4 hechos; este no se ha probado arriba de 16k de contenido.
- **Techo `q4_0`**: la cifra del elenco no cuadra con el `q8_0` medido (ver arriba).
- Repeticiones n≥5: 3 escenarios × 1 pasada no distingue 3/3 de 4/5.

## Licencia

Heredado de la ficha del 3.7B (misma familia y mismo publicador); **pendiente
verificarlo en el repo del 7B**:

| Campo | Valor |
| --- | --- |
| id | `apache-2.0` |
| comercial | sí |
| redistribución | sí |
| gating | no |
| fichero LICENSE | **NO** en el 3.7B — sólo `APPENDIX.md` |
| source | `https://huggingface.co/IFM/K2-Horizon-7B` |

Apache-2.0 §4(a) obliga a entregar copia de la licencia al redistribuir. La
advertencia del fabricante del 3.7B aplica igual aquí: *«not optimized for
moderation, refusal behavior, or production assistant safety»*.
