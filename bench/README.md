# bench/ — receta del banco (los resultados no se versionan)

Este directorio guarda **cómo se mide**, no lo que salió. Los JSON de resultados
(`bench/**/*.json`) están en `.gitignore`: son artefactos de una máquina y un día,
y versionarlos convierte el repo en un álbum de fotos en vez de una herramienta.

La receta completa —qué mide cada instrumento, cómo levantar una caja, en qué
orden se corre y cómo se lee— está en
[`docs/TECHNICAL/BENCH_RECIPE.md`](../docs/TECHNICAL/BENCH_RECIPE.md).

Los instrumentos viven en `scripts/`:

- `bench_admission.py` — ¿este modelo entra en el banco? (español + tools + multiturno)
- `bench_suite.py` — 15 tareas reales del repo
- `voice_probe.py` — la misma identidad, distintos motores
- `drift_probe.py` — identidad a lo largo de 20 turnos
- `window_probe.py` — cuántos turnos atrás conserva el hilo
- `kv_ceiling.py` — techo de ventana por cuantización del KV
- `capability_bench.py` — las 15 tools por el transporte real
- `premerge_gate.py` — la puerta: estilo, suite, capacidades, hook vivo, presupuesto
