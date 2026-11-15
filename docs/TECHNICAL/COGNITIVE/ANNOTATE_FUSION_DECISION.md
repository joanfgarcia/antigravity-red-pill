# ANNOTATE FUSION — decisión GO de la fusión work+social (NB-001 F4/P7)

La fase F4 del plan NB-001 proponía fundir las dos llamadas de extracción de
annotate (work + social) en una sola con `scope` por idea. D-NB-04 fijó el
prerrequisito: **sin banco de annotate, no se adopta a ciegas**. P6 entregó el
banco (`docs/BENCHMARKS/ANNOTATE_BENCH.md`, `scripts/bench_annotate.py`). Esta
fase implementa la fusión tras el flag `MEMENTO_ANNOTATE_SINGLE_CALL_ENABLED`
(default **OFF**) y decide con los números del banco en modo real (LLM local,
Granite-4.1-8B, fixture fijo de 8 fragmentos).

## Resultado

**GO** — la fusión preserva paridad (de hecho mejora) y reduce a la mitad las
llamadas de extracción.

## Tabla antes / después (modo real, 5 corridas por rama)

Fixture: `sha256:2a10110542b6d012fc4bd3876a583b634b6adcdf676d3e547025bdc710d8798e`
(8 fragmentos sintéticos y fijos). `extract_por_fragmento` y `json_invalido` son
propiedades del pipeline medibles en seco; `notas`/`rutas` salen del modelo real.

| Métrica | Baseline (2 llamadas/split) | Fusión (1 llamada/split) | Criterio | Veredicto |
| :--- | ---: | ---: | :--- | :--- |
| `extract_por_fragmento` | 2.0 | **1.0** | — (el objetivo) | −50 % de llamadas |
| `notas/fragmento` (media) | 0.90 (7.2/8) | **1.25** (10.0/8) | ≥ baseline −5 % (0.855) | **PASS** (+39 %) |
| `notas_total` por corrida | 7, 8, 7, 7, 7 | 12, 9, 10, 9, 10 | — | sube |
| `truncados` (total) | 0 | 0 | no aumentan | **PASS** |
| `json_invalido` (total) | 22 (media 4.4) | **0** | no aumenta | **PASS** (se elimina) |
| `rutas` work (media) | 66.7 % | 66.0 % | ±5 pp | **PASS** (−0.7 pp) |
| `rutas` social (media) | 25.0 % | 22.0 % | ±5 pp | **PASS** (−3.0 pp) |
| `rutas` none (media) | 8.3 % | 12.0 % | ±5 pp | **PASS** (+3.7 pp) |
| `segundos_total` (media) | 44.8 s | 37.3 s | — | −17 % |

### Distribución de rutas por corrida

| | rep 1 | rep 2 | rep 3 | rep 4 | rep 5 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Baseline `{work,social,none}` | 6/1/0 | 5/2/1 | 4/2/1 | 4/2/1 | 5/2/0 |
| Fusión `{work,social,none}` | 8/2/2 | 6/2/1 | 5/3/2 | 7/2/0 | 7/2/1 |

## Por qué la fusión no degrada (y mejora)

- El prompt combinado exige un **ARRAY** (nunca objeto suelto ni prosa): el
  `json_invalido` cae de 4.4 a 0. Las dos llamadas separadas (sobre todo la de
  work) devolvían a menudo un objeto `{…}` suelto o prosa cuando había una idea
  o ninguna, y esas ideas se perdían — de ahí que la fusión extraiga **más**
  notas (10 vs 7.2).
- La instrucción «extrae BOTH work AND social, tag con `scope`» hace que el
  modelo no descarte la parte social cuando el fragmento mezcla ambas (la razón
  histórica por la que se separaron las llamadas era la confusión de granite/aya
  con un solo prompt; con el banco medido, esa confusión no se reproduce).
- El `scope` declarado se persiste en idea, parcial y frontmatter; el routing
  (`_route` sobre los scores duales) **no cambia** (D-NB-06: umbrales intactos).

## Cambios

- **Recurso RULE 5**: `annotate_combined_user[_v2|_v3].txt` +
  `annotate_combined_system.txt`, declarados en `prompts/manifest.yaml`.
- **Firma nueva**: `annotate_prompt_version()` y `annotate_manifest()` incluyen el
  prompt combinado (marca `annotate_extract=single`) SOLO con el flag ON; OFF deja
  la firma intacta. Fila documental en `PROMPT_VERSION_MAP.md`.
- **Flag** `MEMENTO_ANNOTATE_SINGLE_CALL_ENABLED` (RULE 4, default OFF) en
  `config.py` + `.env.example`; leído en un punto (`runtime.single_call_enabled`).
- **`scope` persistido**: `_extract` (idea) → parcial (`splits→ideas`) →
  frontmatter (`scope:`); reconstruido en `--from`/reuso (`annotation_state.py`).
- **Banco**: `scripts/bench_annotate.py --single-call` mide la fusión
  (1 extract/split); `tests/test_memento_annotate_single_call.py` cubre el
  contrato; `tests/test_annotate_bench.py` cubre el modo combinado.

## Cómo reproducir

```
PYTHONPATH=src python scripts/bench_annotate.py --repetitions 5 --out /tmp/baseline
PYTHONPATH=src python scripts/bench_annotate.py --repetitions 5 --single-call --out /tmp/fusion
```
