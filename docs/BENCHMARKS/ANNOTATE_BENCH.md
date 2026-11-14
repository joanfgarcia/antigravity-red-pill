# ANNOTATE BENCH — banco reproducible de annotate (NB-001 F4/P6)

- **Fecha**: 2026-11-10T14:35:42.705128+00:00
- **Fixture**: `sha256:2a10110542b6d012fc4bd3876a583b634b6adcdf676d3e547025bdc710d8798e` — 8 fragmentos sintéticos y fijos
- **Modo**: dry-run (sin LLM — valida arnés + fixture)
- **Baseline**: **2 llamadas por split** (work + social en la extracción)

Un `fragmento` == `split` == `unidad` (un `memento/NNN-mensajes-*.md`). El banco
mide la etapa annotate real (extract → dedup → score → gate), envolviendo el
transporte para contar llamadas, cronometrarlas y detectar respuestas truncadas
o con JSON inválido.

## Esquema JSONL (v1)

| campo | tipo | descripción |
| :--- | :--- | :--- |
| `bench` | str | `"annotate"` (fijo) |
| `schema_version` | int | versión del esquema |
| `ts` | str | ISO-8601 UTC de la corrida |
| `dry_run` | bool | transporte falso sin LLM |
| `fixture_hash` | str | hash canónico del fixture (estable) |
| `fixture_fragments` | int | nº de fragmentos |
| `repetition` | int | índice de corrida (1..N) |
| `llamadas` | int | nº total de llamadas |
| `llamadas_extract` | int | llamadas de extracción (work+social) |
| `llamadas_score` | int | llamadas de scoring dual |
| `llamadas_rewrite` | int | llamadas de re-escritura de voz |
| `llamadas_por_fragmento` | float | `llamadas / fragmentos` |
| `extract_por_fragmento` | float | `llamadas_extract / fragmentos` (**baseline = 2.0**) |
| `notas_total` | int | notas materializadas |
| `notas_por_fragmento` | [int] | notas por fragmento (por NNN) |
| `rutas` | {work, social, none} | distribución del gate |
| `truncados` | int | respuestas con `DEGRADED_MARKER` |
| `json_invalido` | int | respuestas sin array JSON válido |
| `segundos_total` | float | segundos de todas las llamadas |
| `segundos_por_fragmento` | [float] | segundos de las 2 llamadas de extracción por fragmento |

## Corridas (1)

| rep | llamadas | extract | score | rewrite | notas | work | social | none | trunc | JSON inválido | s total |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 17 | 16 | 1 | 0 | 8 | 3 | 3 | 2 | 0 | 0 | 0.00 |

## Cómo medir el baseline real

```
PYTHONPATH=src python scripts/bench_annotate.py --repetitions 3
```

El `dry-run` (por defecto en CI) no llama al modelo: valida el arnés y el
fixture, y ya imprime el baseline de 2 llamadas por split (es una propiedad
del pipeline, no del modelo).
