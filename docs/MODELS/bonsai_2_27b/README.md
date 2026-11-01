# bonsai_2_27b — Ternary Bonsai 2 27B (PTQ1_0)

> Ternario 27B sobre base Qwen3.8-27B, servido por el fork PrismML. **Deixis
> perfecta y 65.536 de ventana con `q4_0`**: el único del elenco que tiene las dos
> cosas a la vez. Su freno histórico era la latencia, y ese freno lo pone el
> `thinking`, no el modelo.

Perfil: `bonsai_2_27b` · Fichero: `Ternary-Bonsai-2-27B-PTQ1_0.gguf` · 5,95 GB
Runtime: **`llama_cpp_prism`** (`~/opt/llama.cpp-prism`) · Medido: 2026-10-29

---

## Specs

| Campo | Valor |
| --- | --- |
| Parámetros | 27B, cuantización ternaria **PTQ1_0 (1,75 bpw)** |
| Base | Qwen3.8-27B |
| Tamaño en disco | 5,95 GB (5.536 MiB en VRAM) |
| Contexto declarado / perfil | 24.576 |
| Conducta del perfil | `thinking: on`, `reasoning_effort: medium`, `reasoning_budget: 4096` |
| Licencia | Apache-2.0 (atribución de cortesía pedida en `NOTICE.txt`) |

**Runtime anclado, no negociable.** AD-049: el stock con `Q2_0` produce basura sin
aviso; Bonsai exige el fork PrismML. El registro `runtimes.yaml` lo declara con
`kind: llama_cpp_fork`.

## Límites medidos (RTX 5070 Laptop 8 GB)

| Cuantización KV | `n_ctx` máximo | KiB/token (perfil) |
| --- | ---: | ---: |
| f16 | **24.576** (32.768 OOM) | 64 |
| q8_0 | **49.152** | 34 |
| q4_0 | **65.536** (98.304 OOM) | 18 |

El KV es **menos de la mitad de caro** que en granite (160 KiB/token en f16): por eso
un 27B cabe en 8 GB y aun así deja 65K de ventana. Fronteras del perfil (2026-10-08:
16K OK, 24K OK, 32K OOM) confirmadas hoy.

## Bench (BENCHSET, 2026-10-29)

`q8_0` a 24.576, n=3 por probe, mismos prompts y validadores que el resto del elenco.

| Probe | `reasoning off` | `thinking on` (budget 4096) |
| --- | :-: | :-: |
| `contract_entidades` | **3/3** | 3/3 |
| `contract_decision` | 3/3 | 3/3 |
| `contract_genero` | 3/3 | 3/3 |
| `needle_8k` | 3/3 | 3/3 |
| `synthesis_es` | 2/3 | 2/3 |
| **Total** | **14/15** | **14/15** |
| Latencia (`entidades`) | **7,4 s** | **51,0 s** |

### El hallazgo: el razonamiento no paga

Misma puntuación con y sin thinking, **7× más lento**. Para el ciclo de sueño
(cientos de sesiones) eso decide la noche. **Carril del destilador: `reasoning off`.**

`synthesis_es` falla 1 de 3 por cobertura (5/8 hechos frente al umbral de 6/8), no
por formato. Con thinking llegó a 8/8 una vez: el techo es más alto, la consistencia
no.

## Por qué parecía descartado y no lo está

AD-049 (2026-10-08) lo validó: *«bonsai 3/3 y granite 3/3 tras unificar conducta»*.
Se le dio perfil, plan de KV calibrado y runtime anclado — **y ningún carril**. En el
bakeoff de esa fecha salía 21,5 s frente a 4,7 s de granite en `frases`, y eso lo
dejó fuera de las tareas sensibles a latencia. Pero esa lentitud venía del thinking
(xhigh por defecto), no del modelo: con `reasoning off` baja a 7,4 s, en el rango de
granite.

Un perfil sin carril no se usa nunca. Ése fue todo el «descarte».

## Posición en el elenco

| Modelo | Benchset | Deixis | Ventana `q4_0` | Latencia |
| --- | :-: | :-: | ---: | ---: |
| K2-Horizon-7B `Q5_K_M` | 15/15 | 3/3 | 40.960 | 5,5 s |
| **`bonsai_2_27b`** | 14/15 | **3/3** | **65.536** | 7,4 s |
| K2-Horizon-3.7B | 13/15 | 1/3 | 98.304 | 0,6 s |
| `granite_8b` (titular) | 12/15 | 3/3 | 49.152 | 5,3 s |

## Veredicto

**Se queda.** Dos papeles posibles, y el segundo es el que nadie había considerado:

1. **Destilador** con `reasoning off` — 14/15 con deixis perfecta, en el rango de
   latencia de granite. Pendiente la prueba de textura.
2. **Lector de contexto largo** — 65.536 con `q4_0` y un modelo 5× mayor que el
   3.7B. Si su calidad aguanta a ventana llena, supera al 3.7B en ese papel.

**Pendiente:** prueba de textura sobre recuerdos reales y calidad de lectura a
ventana llena (el 3.7B se cae a partir de ~46K; bonsai no está medido ahí).

---

## Latencia real y configuración pendiente (2026-10-29, tarde)

**Cifra corregida.** Medido en tok/s sobre la misma tarea (`contract_entidades`):

| Modelo | tok salida | s | tok/s |
| --- | ---: | ---: | ---: |
| `granite_8b` | 286 | 5,3 | **53,9** |
| K2-7B `Q5_K_M` | 274 | 5,5 | 49,8 |
| **`bonsai_2_27b`** | 299 | 7,4 | **40,5** |

Es **un 25% más lento que el titular**, no 7×. El «7×» de la primera medición comparaba
contra el 3.7B, que responde en 0,6 s porque es pequeño y escribe menos: los segundos
absolutos no sirven para comparar.

**Fallo de configuración abierto:** el perfil **no declara `flash_attn` ni `fa_capable`**
(AD-037). Resuelto a `auto`, el daemon podría correrlo **sin Flash Attention**. Las
mediciones de esta ficha se hicieron con `-fa on` explícito, así que no están afectadas
— pero producción sí lo estaría. Añadir al perfil:

```yaml
flash_attn: true
fa_capable: true
```

## Servido por el daemon (verificado 2026-10-30)

Ya no hace falta un banco aparte: el daemon lo sirve de punta a punta.

```
POST localhost:8760/v1/chat/completions {"model": "bonsai_2_27b", ...}
→ 200 en 5,9 s · {"motor": "bonsai", "via": "daemon"}
→ /status: loaded_profile=bonsai_2_27b, mode=gpu, flash_attn=true
→ system_fingerprint: b1-4fbda12  (build prism)
```

Y la vuelta a `granite_8b` en caliente: 200 en 1,5 s, sin fugas de VRAM (7.453 MiB).
El daemon no sabe qué motor hay detrás: `build_local_backend` resuelve perfil →
runtime → binario o proceso.

**Pendiente para entrar en un carril:** `minion_tool`. `RuntimeServer.chat` ya
acepta `tools`; falta medir el function calling del ternario.

## La KV en f16 es una trampa (2026-10-30)

El perfil pedía `kv_cache.preferred: f16` y **cabía** — por eso lo elegía. Cabía y
era 2,5× más lento. A ventana fija de 16.384, mismo binario, medidas repetidas:

| KV | VRAM | decode |
| --- | ---: | ---: |
| **f16** | 6.610 MiB | **18,7 tok/s** |
| q8_0 | 6.516 MiB | **46,4 tok/s** |
| q4_0 | 6.260 MiB | 46,6 tok/s |

94 MiB de diferencia y el doble y medio de velocidad: no es presión de memoria, es
el kernel de atención en f16 de este build de prism. Empeora con la ventana
(12,7 tok/s a 24K). Corregido en el perfil (`preferred: q8_0`, f16 último
fallback). Verificado end-to-end: la sesión más pesada de la noche bajó de
**280 s a 165 s**.

Consecuencia: el «bonsai cuesta el doble de noche» del 2026-10-30 medía el
perfil, no el modelo. Ver [`../PREFILL_2026-10-30.md`](../PREFILL_2026-10-30.md).
