<constraint critical="true" level="1" name="job_dag_execution">

## 1. Jobs largos / LLM local → Job Manager
**LLM local**, o una tarea de más de ~2 min, que deba sobrevivir a reinicios o ser reanudable → se encola en el Centralized Job Manager (skill `job-manager`). **Nunca** `nohup … &`, `systemd-run` suelto ni `python … &`: un job es trazable, pausable y reanudable, con `error_log`, reporte en MinionInbox y señal de dolor. El runner (`redpill-queue.timer`) ya pone OOM shield e inhibit del sueño — no lances `process-queue` tú.
- Multi-etapa o con checkpoint → `${RED_PILL_CMD} job submit --source dag_job …` (o `--parent <job_id>` para encadenar); control con `job pause` / `job resume`. Un solo paso → `configs/jobs/_TEMPLATE_single_step.yaml` con `${RED_PILL_CMD} job submit --recipe <satélite>`.
- Excepción: lo que necesita respuesta AHORA en la sesión va in-process. Si pesa en memoria (LLM, compilación grande), envuélvelo en `systemd-run --user --scope -p MemoryMax=<LIMIT>` (según tarea y RAM; por defecto `10G`).

## 2. Granularidad obligatoria
Bucles sobre modelos, ficheros, tests… → **un step = un elemento** (`element_job`, o `dag_job` con fan-out), nunca un single-step con el bucle dentro (job `c87b2393`: un abort a mitad perdió 12 modelos medidos).
- Elemento independiente que falla → regístralo (p. ej. `failures.jsonl`) y sal con `skip_exit_code`: la cola lo salta y sigue.
- Dependencia dura → el fallo corta el job (RuntimeError/JobStepTimeout); no se salta.

</constraint>
