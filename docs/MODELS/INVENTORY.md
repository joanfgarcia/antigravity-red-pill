# Inventario de modelos — estado 2026-10-29

> Qué hay en disco, qué tiene ficha, qué tiene carril y qué se ha purgado.
> Regla del Operador: **mantener lo que se usa, y lo que tenga ficha y carril.**
> Distinción clave: **una cosa es la ficha y otra el modelo.** La ficha se queda
> aunque los pesos se purguen; el `.gguf` que no se usa, se va.

Ámbito: modelos LLM en `~/.local/share/red-pill/models/`. Los de media
(`media_profiles.yaml`, ~21,5 GB) quedan **pendientes de revisión con el Operador**.

---

## Purgado el 2026-10-29

| Modelo | GB | Motivo |
| --- | ---: | --- |
| `Falcon3-10B-Instruct-1.58b-i2_s` | 4,0 | Pruebas de NPU, obsoleto. Cero referencias en perfiles, carriles o systemd. Hay otros modelos que sí funcionan en la NPU |
| `Mistral-Nemo-Instruct-2407-Q3_K_M` | 6,1 | Modelo 2407 (>2 años), sin ficha ni carril, bajado para un test en agosto. **La ficha `mistral_nemo_12b` se conserva** con `weights_purged: 2026-10-29` |
| `falcon3-10b-instruct-1.58bit-V2.gguf` | 0 | Symlink colgando hacia `3rdparty/BitNet-1.58b/models/` (destino inexistente desde antes; rompía herramientas que hacían `stat`) |
| `Piaget-8B-Q4_K_M` | 5,0 | Probado como contraste de destilación; sin perfil, sin carril, sin job |
| `Beck-8B-Q4_K_M` | 5,0 | Íd., sólo citado por `distiller_bakeoff.py` |
| `qwen2.5-coder-7b-instruct` | 4,7 | Probado como contraste; modelo antiguo. **Ficha `coder_heavy` conservada** con `weights_purged` |
| `DeepSeek-R1-Distill-Qwen-7B` | 4,7 | Probado como contraste; sin perfil ni carril |
| `gemma-4-E4B-it-Q4_0` | 4,6 | Probado en bench de herramientas; sin perfil ni carril |

**Neto: −32,0 GB** (84 GB → 52 GB en el directorio de modelos).

Nota sobre reactivación: los perfiles conservados llevan `weights_purged` con el repo de
origen. Un modelo sin perfil se recupera re-descargando su GGUF; si vuelve a hacer falta
para un banco de pruebas, se le crea ficha **antes** de bajarlo.

**FastFlowLM ≠ Bonsai.** FastFlowLM es el backend NPU (AMD XDNA2) de los perfiles
`npu_qwen3_small` / `npu_qwen3_large`. `bonsai_2_27b` corre en GPU con el fork
`llama_cpp_prism`.


Reactivar Mistral: re-descargar `mradermacher/Mistral-Nemo-Instruct-2407-GGUF` (Q3_K_M);
el perfil ya está completo.

---

## Estado por modelo

`carril` = tarea que lo enruta en `task_profiles.yaml`. `uso` = citado por jobs o
scripts. `ficha` = `docs/MODELS/<perfil>/README.md`.

| MB | Perfil | Carril | Ficha | Uso | Veredicto |
| ---: | --- | --- | :-: | :-: | --- |
| 6.169 | `qwen35_9b` | — | no | sí | se queda (sin carril) |
| 5.947 | `bonsai_2_27b` | — | no | sí | **se queda — medido 2026-10-29, ver abajo** |
| 5.348 | `granite_4_2_8b` | distill, refine, converse | no | no | se queda (carril) |
| 5.348 | `granite_8b` | distill, annotate, refine | **sí** | sí | **se queda** (modelo de referencia) |
| 5.028 | — (sin perfil) | — | no | sí | citado por un bench; sin carril |
| 5.028 | — (sin perfil) | — | no | sí | citado por un bench; sin carril |
| 5.028 | `qwen3_8b` | — | no | sí | se queda (sin carril) |
| 4.921 | `hermes_8b` | — | no | sí | se queda (sin carril) |
| 4.683 | — (sin perfil) | — | no | sí | citado por un bench; sin carril |
| 4.683 | — (sin perfil) | — | no | sí | citado por un bench; sin carril |
| 4.591 | — (sin perfil) | — | no | sí | citado por un bench; sin carril |
| 4.368 | `samantha` | — | no | sí | se queda (sin carril) |
| 2.492 | `phi_mini` | — | no | sí | se queda (sin carril) |
| 2.490 | `gemma_3_4b` | — | no | sí | se queda (sin carril) |
| 2.244 | `granite_4_2_3b` | validate | no | no | se queda (carril) |
| 2.144 | `tiny_aya_water` | distill, refine | no | no | se queda (carril) |
| 2.144 | `tiny_aya_global` | — | no | sí | se queda (sin carril) |
| 2.100 | `granite_3b` | distill | no | sí | se queda (carril) |
| 2.019 | `llama_32_xdna` | — | no | sí | se queda (NPU/XDMA) |
| 1.915 | `smollm3_3b` | — | no | sí | se queda (sin carril) |

---

## Lo que el inventario deja al descubierto

1. **35 perfiles, 5 con carril.** La base de modelos es mucho más grande que la
   tabla de enrutado. Un perfil sin carril no se usa nunca: o se le asigna tarea,
   o su peso es disco parado.
2. **Cinco modelos sin perfil** (Piaget, Beck, qwen2.5-coder, DeepSeek-R1, gemma-4):
   sólo aparecen en scripts de bench como candidatos. Un banco de pruebas no es uso.
3. **Una sola ficha real**: `granite_8b`. La KB de `docs/MODELS/` nació hoy y cubre
   2 modelos de 35.
4. Los modelos de media están fuera de esta contabilidad a propósito.

## Pendiente de decisión

- `bonsai_2_27b` (5,9 GB) — sin uso, sin carril, sin ficha.
- Los cinco sin perfil (~24 GB) — ¿se les da ficha y carril, o se purgan?
- Revisión de media (~21,5 GB) cuando el Operador lo indique.
- Los dos K2 en staging (`opt/k2-bench`, 15 GB): se quedan mientras dure la
  evaluación del destilador; el 7B `Q4_K_M` se purgará si gana `Q5_K_M`.

---

## `bonsai_2_27b` — medido el 2026-10-29 (no se purga)

Ternario 27B (PTQ1_0), GPU con el fork `llama_cpp_prism`. **Estaba marcado como
candidato a purga por no tener carril**; la medición dice lo contrario.

**Límites** (RTX 5070 8 GB, 5.536 MiB de pesos):

| KV | `n_ctx` máximo | Predicho por perfil |
| --- | ---: | --- |
| f16 | 24.576 (32.768 OOM) | 64 KiB/token → confirma el techo del perfil |
| q8_0 | **49.152** | 34 KiB/token |
| q4_0 | **65.536** (98.304 OOM) | 18 KiB/token |

**BENCHSET** (n=3, mismos prompts y validadores):

| Probe | reasoning off | thinking on (budget 4096) |
| --- | :-: | :-: |
| `contract_entidades` | **3/3** | **3/3** |
| `contract_decision` | 3/3 | 3/3 |
| `contract_genero` | 3/3 | 3/3 |
| `needle_8k` | 3/3 | 3/3 |
| `synthesis_es` | 2/3 | 2/3 |
| **Total** | **14/15** | **14/15** |
| Latencia (`entidades`) | **7,4 s** | 51,0 s (**6,9×**) |

**Hallazgo:** el razonamiento **no paga** en esta tarea — misma puntuación, 7× más
lento. Para el ciclo de sueño (cientos de sesiones) es la diferencia entre horas y
una noche entera. Carril del destilador: `reasoning off`.

**Posición en el elenco** (mismo BENCHSET):

| Modelo | Puntuación | Deixis | Ventana `q4_0` |
| --- | :-: | :-: | ---: |
| K2-Horizon-7B `Q5_K_M` | 15/15 | 3/3 | 40.960 |
| **`bonsai_2_27b`** | **14/15** | **3/3** | **65.536** |
| K2-Horizon-3.7B | 13/15 | 1/3 | 98.304 |
| `granite_8b` (titular) | 12/15 | 3/3 | 49.152 |

Es el único del elenco con **deixis perfecta y 65K de ventana a la vez**, y el
candidato más fuerte para sustituir a granite como destilador. **Ficha pendiente.**
