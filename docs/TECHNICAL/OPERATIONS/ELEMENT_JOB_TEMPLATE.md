# Recetario: el patrón MAP reanudable (driver `element_job`)

> Patrón documentado 2026-09-15, nacido del incidente `f6493c71`: la redestilación
> de Memento corrió como `script_job` single durante 5h42 sin pausa posible y una
> generación del LLM se colgó ~2h. La solución no era parchear ese job, sino
> extraer el patrón que necesita: **recorrer exactamente N elementos, uno por
> step, pausable por elemento, con watchdog**.

## 1. El patrón

| Pieza | Cómo |
|---|---|
| **Lista de N elementos** | `elements` (inline), `elements_file` (JSON en disco) o `elements_command` (comando que imprime el array JSON). Se resuelve en el primer step y **N se congela en el checkpoint** → procesa exactamente N aunque la fuente cambie. |
| **Función por elemento** | `step_command`: cualquier comando del proyecto. Recibe el elemento por env `RP_ELEMENT` (JSON serializado) y `RP_ELEMENT_INDEX` (0-based). |
| **UN step = UN elemento** | El driver lleva el índice en el checkpoint `{index, total}`; `job_pause`/`job_resume` aterrizan en la frontera del elemento. |
| **Watchdog** | `control.max_step_minutes` → systemd-run `RuntimeMaxSec` mata el cgroup (hijos CUDA incluidos) si un elemento cuelga → `JobStepTimeout`. |
| **Señales del elemento** | `defer_exit_code` → `JobDeferred` (el runner reintenta cuando el recurso se libere); `pause_exit_code` → revisión del operador; 124/137/143 → timeout/signal. |

## 2. Cuándo usar `element_job` (y cuándo no)

- **Sí**: destilar/recalcular/emitir N unidades independientes (sesiones, ficheros,
  reportes, engramas), cada una ≤ ~10 min y reanudable por unidad. El proyecto
  aporta el comando por elemento y el origen de la lista.
- **No**: una única tarea larga (usa `script_job` single), un árbol con
  dependencias (usa `dag_job`), o una misión agéntica multi-rol (usa `agentic_job`).
- Si el bucle debe PARALELIZAR (varios elementos a la vez), consulta
  `RFC_JOB_DAG_PARALLELIZATION.md` — `element_job` es secuencial por diseño.

## 3. Receta mínima

```yaml
source: element_job
priority: 5
title: Mi mapa reanudable
step_command: uv run python scripts/procesar_uno.py   # lee RP_ELEMENT
elements_command: uv run python scripts/lista.py      # imprime [{"id": ...}, ...]
defer_exit_code: 77
control:
  max_step_minutes: 10    # watchdog por elemento
```

## 4. Script por elemento (plantilla)

```python
#!/usr/bin/env python3
"""procesar_uno.py — procesa UN elemento del job element_job."""
import json
import os

element = json.loads(os.environ["RP_ELEMENT"])   # el elemento a tratar
index = int(os.environ["RP_ELEMENT_INDEX"])
# ... trabaja sobre element ...
# if llm_caido: sys.exit(int(os.environ.get("RP_DEFER_EXIT_CODE", 77)))
```

## 5. Operación

```bash
red-pill job submit --recipe mi_mapa --singleton   # encola (valida el payload)
red-pill job list                                  # estado
red-pill job pause  <id>                           # pausa en frontera de elemento
red-pill job resume <id>                           # reanuda exacto
red-pill job kill   <id>                           # interrupción dura (PAUSED*)
```

El progreso aparece como `current/total` (índice/N) y `percent`; el log por job
etiqueta cada step como `elemento <i>`.

## 6. Ejemplo real

`configs/jobs/memento_redistill.yaml` cubre el caso equivalente con `script_job`
(redestilación por lotes de 5); el template `configs/jobs/_TEMPLATE_element_job.yaml`
es la versión `element_job` de UN elemento por step, lista en `tests/test_element_job_driver.py`.