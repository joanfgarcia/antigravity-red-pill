<constraint critical="true" level="1" name="job_dag_execution">

## 1. Jobs largos / LLM local → DAG (regla de ejecución)
Cualquier cosa que requiera el uso de **LLM local** (o una tarea que vaya a durar
más de ~2 minutos, sobrevivir a reinicios, o ser reanudable) **DEBE ejecutarse
mediante el Centralized Job Manager**, no a pelo en un `nohup`/`&`:

1. **Usa el skill `job-manager`**: decide si es job (§1), encola con el recipe/carril correcto (§2) y opera con pause/resume (§3). El runner (`redpill-queue.timer`, cada 1 min) lo recoge con OOM shield e inhibit del sueño — jamás lances `process-queue` tú mismo.
2. **Tareas multi-etapa o pausables por checkpoint** → `dag_job` vía `${RED_PILL_CMD} job submit --source dag_job ...` (o `--parent <job_id>` para encadenar etapas): árbol de etapas con checkpoint por ruta y `job pause` / `job resume` para control transferible.
3. **Tarea larga de UN solo paso** → plantilla `configs/jobs/_TEMPLATE_single_step.yaml` (`source: script_job` con `step_command` y `progress.mode: single`), encolada con `${RED_PILL_CMD} job submit --recipe <satélite>`.
4. **Nunca**: `nohup ... &`, `systemd-run` suelto, `python script.py &` en background para trabajos de larga duración. Un job encolado = trazable, pausable, reanudable, con `error_log`, reporte en MinionInbox y señal de dolor si se frustra.

La única excepción es una tarea que necesita respuesta AHORA en la sesión (chat, lint rápido) — esa va in-process, nunca como job (skill `job-manager` §1).

</constraint>
