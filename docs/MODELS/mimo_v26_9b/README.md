# MiMo-V2.6-Distill-Qwen-9B — ficha y medidas

Modelo de Xiaomi MiMo: SFT sobre **Qwen3.5-9B** con datos generados por MiMo,
publicado como punto de partida para RL agéntico. **MIT** (el aviso de uso del
README no añade condiciones a la licencia, según el propio autor).

- Repo: <https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B>
- Quant usada: `bartowski/…-GGUF` → `MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf` (5,84 GB)
- Visión: `mmproj-…-f16.gguf` (0,88 GB) descargado, **sin probar**
- Arquitectura: `qwen35` (32 capas, GQA 4 KV, 262.144 de contexto nativo,
  multimodal image/audio/video en el template)
- Perfil: `mimo_v26_9b` · catálogo: `local/mimo-v26-9b` (prioridad 11, candidato)

## Coste en este puesto (RTX 5070 Laptop 8 GB)

| Métrica | Valor | Cómo |
|---|---|---|
| VRAM a 8K ctx | **6.326 MiB** | `llama-server -ngl 999 -c 8192` |
| Decode | **56,8 tok/s** | mismo run, 53 tokens |
| Prefill | **107 tok/s** | mismo run |
| Carga en frío | 2,9–8,7 s | `llama-cpp-python`, ngl=-1 |
| KV f16 | ≈64 KiB/token (GQA 4) | `config.json` |

Cabe con margen: con 8 GB libres el techo práctico ronda 12–16K de contexto.

## Herramientas — bucle REAL (`scripts/tool_loop_probe.py`)

Llamada → `role: tool` con el resultado → repetir. **3/3**.

| Escenario | Pasos | Responde | ¿Usa el resultado devuelto? |
|---|:-:|:-:|:-:|
| A · buscar los `async` de `src/` | 2 (`list_dir` → `grep`) | sí | **sí** |
| B · ¿cuántas hay? | 2 (`list_dir` → `grep`) | sí | **sí** (`foo`, `bar`) |
| C · mirar `src/a.py` | 1 (`read_file`) | sí | **sí** |

0,4–1,9 s por vuelta. Encadena, no se queda en el primer paso y cierra con el
dato que le devolvió la herramienta.

Comparación: `granite-4.2-8b` hace 2/3 en el mismo bucle — en A responde sin
usar el contenido devuelto, y a 1,3–4,8 s por vuelta.

## Herramientas — 5 probes (arnés ya corregido)

| Probe | mimo | qwen3.5-9b | granite-4.2-8b |
|---|:-:|:-:|:-:|
| `simple` | ✅ 1,0 s | ✅ 2,8 s | ✅ 3,9 s |
| `multi_sel` | ✅ 0,8 s | ✅ 2,5 s | ✅ 2,4 s |
| `json_args` | ✅ 2,8 s | ✅ 6,3 s | ✅ 14,6 s |
| `no_tool` | ✅ 13,9 s | ✅ 12,4 s | ❌ **llamó `search_files` sin venir a cuento** |
| `multi_step` (primer paso) | ✅ 0,6 s | ✅ 2,0 s | ✅ 5,3 s |
| **total** | **5/5** | **5/5** | **4/5** |

Antes de corregir el arnés esta tabla daba 3/5 · 4/5 · 3/5. El cambio no es del
modelo: era el banco de pruebas (ver abajo).

## Síntesis / destilado (carril `distill`, `thinking: off`)

Con la conducta de producción aplicada (`--task distill`), **todos** los
candidatos aprueban; la diferencia es el precio.

| Modelo | Fidelidad (base/tuned) | Bake-off (JSON/ES) | s/probe |
|---|---|---|---|
| **mimo_v26_9b** | **3/3 · 3/3** | **4/4** | **0,77–0,99** |
| granite-4.1-8b | 3/3 · 3/3 | 4/4 | 1,05–1,36 |
| granite-4.2-8b | 3/3 · 3/3 | 4/4 | 0,89–1,22 |
| qwen3.5-9b | 3/3 · 3/3 | 4/4 | 1,10–1,33 |

Ficheros: `docs/BENCHMARKS/2026-11-16-DISTILLER_{FIDELITY,BAKEOFF}_MIMO.md`.

## Correcciones de arnés del 2026-11-16 (leer antes de creerse un FAIL)

Medir este modelo destapó cuatro defectos del banco de pruebas. Los cuatro
inflaban o desinflaban la nota de cualquiera:

1. **`thinking: off` no se aplicaba.** Los harness de destilado montaban su
   propio `Llama` sin conducta: los modelos con thinking declarado razonaban a
   pelo, gastaban el presupuesto y no formateaban. Resultado: 0/6 en granite-4.2
   y 0/4 en qwen3.5 — **falso**. Ahora aplican `--task distill` vía
   `conduct.apply_task_profile()` (perfil ⊕ tarea, igual que el daemon).
2. **`multi_step` pedía dos llamadas en UNA respuesta** y nunca devolvía el
   resultado. Eso mide paralelismo, no multiturno: ya nos costó un FAIL falso con
   Spark-X2.6 (ver `docs/MODELS/PREFILL_2026-10-30.md`). Ahora solo evalúa el
   primer paso y lo dice (`chain_measured: False`); la cadena se mide con
   `tool_loop_probe.py`.
3. **`json_args` no llevaba la fecha de hoy** y solo comprobaba que hubiera una
   `T`: premiaba inventarse la fecha y castigaba preguntar. Ahora el system
   prompt lleva la fecha y se valida que `when` sea mañana de verdad.
4. **Argumentos en texto validados como tipos Python.** El dialecto
   `<parameter=k>v` no tiene tipos: `{"duration_min": "30"}` es lo normal en
   granite y MiMo. Ahora se coerciona antes de validar.

Y un quinto, del runtime, que no era del banco: `register_thinking_handlers`
registraba los handlers con nombre global (`granite-nothink`) y **el segundo
modelo cargado en el mismo proceso heredaba el template del primero** (o fallaba
el registro). Corregido con `overwrite=True`.

## Textura sobre fragmentos REALES vs `bonsai_2_27b` (2026-11-16)

Protocolo de casa: 9 fragmentos de archivo (2026-07/08/09, a 1/4, 1/2 y 3/4),
mismo `distiller_v3_voice.txt`, `temperature 0.3`, thinking apagado en ambos,
mismo binario (prism). KV `q4_0`, contexto 16.384.

| Modelo | JSON | Vallas | 3ª persona | Deixis mala | Escenas inventadas | Relics verbatim | s/frag |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| `bonsai_2_27b` | 9/9 | 0 | 0 | 0 | 0 | 28/30 | 8,8 |
| **`mimo_v26_9b`** | **9/9** | **0** | **0** | **0** | **0** | 16/18 | **7,1** |

Empate en lo objetivo; mimo algo más rápido. **El veredicto no es mío**: en este
protocolo la voz la firma el Operador leyendo los pares ciegos
(`docs/BENCHMARKS/2026-11-16-TEXTURE_MIMO_VS_BONSAI.md`, mapa en `.map.json`).

Aviso de método: la primera pasada se lanzó con `--max-tokens 600` y mimo salió
5/9 por truncamiento (2.1k caracteres cortados a media clave). Con los 2048 del
carril `distill`, 9/9. Un probe con menos presupuesto que producción mide al
probe.

## Lo que NO está medido

- **e2e de minion** con perfil real (`local_minion`, varias vueltas, herramientas
  del repo): el paso que falta para subirle la prioridad en la cascada.
- **Visión** (mmproj): descargado, sin probar. El perfil es texto/agéntico.
- Repeticiones n≥5: 3 escenarios × 1 pasada no distingue 3/3 de 4/5, y 9
  fragmentos de textura no separan una escena inventada de una racha.

