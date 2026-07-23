---
name: job_manager
description: Encolar, ejecutar, pausar y monitorizar trabajos diferidos y reanudables (Centralized Job Manager) — flows YAML, tareas agénticas y drivers propios sobre la cola central de Red-Pill.
---

# Centralized Job Manager Skill

Este skill enseña al Agente a usar el gestor centralizado de trabajos de Red-Pill: una sola cola persistente (`bunker_queue.db`), un runner shot-and-forget disparado por timer, y drivers reanudables por checkpoint. Plan de diseño: `Aleth_Core/IMPLEMENTATION_PLAN_UNIFIED_JOB_MANAGER.md`.

## 1. Decisión previa: ¿esto es un job?

| La tarea... | Camino correcto |
| :--- | :--- |
| Necesita respuesta AHORA en esta sesión (chat, lint rápido) | **NO es un job** — in-process: `GruOrchestrator.deploy_swarm()` (con `await` si esperas el resultado) |
| Puede esperar al próximo minuto y sobrevivir a reinicios (entrenamiento, re-síntesis, flows largos, investigación) | **Job diferido** → esta skill |
| Es una nota/exploración para el despertar autónomo ("investiga X") | **NO uses sources de drivers** — carril cognitivo: `enqueue_task(source="drive_evaluator", ...)` |

Regla de oro: por CLI **todo es diferido**. No existe `--mode` — un "inmediato" encolado sería mentira (esperaría al timer).

## 2. Encolar trabajos (CLI)

```bash
# Un flow YAML existente, como job pausable/reanudable
red-pill job submit --source flow_job --payload '{"flow_id": "vulnerability-sweep"}' --title "Barrido nocturno" --priority 7

# Una tarea agéntica genérica (backend/modelo/effort en el payload)
red-pill job submit --source agentic_job --payload '{
  "prompt": "Audita los TODO de src/ y propón un plan",
  "backend": "claude", "model": "opus", "effort": "high",
  "cwd": "/ruta/al/workspace", "timeout": 900
}' --title "Auditoría TODOs"
```

- **Prioridad**: entero, **mayor = más urgente**, default 5 (convención única de toda la cola).
- `agentic_job` acepta `cascade` en vez de `backend`: lista ordenada `[{"backend": "claude", "model": "opus", "effort": "high"}, {"backend": "local"}]` — prueba cada target hasta uno con cuota (mismo sustrato que Telegram).
- Backend `local`/`local-tools`: el driver ya gestiona VRAM/CPU/RAM — si no hay recursos, el job se difiere solo, sin quemar reintentos.

## 3. Operar la cola

```bash
red-pill job list                 # activas, pausadas, en cola (--all incluye COMPLETED)
red-pill job status <id|prefijo>  # fila completa: checkpoint, progress, attempts
red-pill job pause <id|prefijo>   # no interrumpe el step en curso; para en la frontera atómica
red-pill job resume <id|prefijo>  # reanuda EXACTAMENTE desde el checkpoint
red-pill job process-queue        # runner manual (el timer redpill-queue lo hace cada 1m solo)
```

Los ids aceptan el prefijo corto que muestra `job list`. El runner tiene flock: lanzarlo con otro activo cede con `exit 0`, sin daño.

## 4. Leer resultados y salud

- **Fin/error de cada job** → reporte en `MinionInbox` (leer vía `check_minion_inbox` del MCP).
- **Señales**: `jobs_stuck` (PROCESSING sin latido >30 min) y `jobs_frustrated` (disyuntor activado) las emite el plugin `job_monitor` del SovereignDaemon.
- **`FRUSTRATED`** = 3 fallos reales. Diagnostica con `job status` (campo `error_log`), corrige la causa y `red-pill job resume <id>` NO aplica (solo PAUSED); re-encola con un submit nuevo o repara y resetea el estado a mano si procede.

## 5. Escribir un driver nuevo

Solo si la tarea pesada no encaja en `flow_job` ni `agentic_job`:

```python
# src/red_pill/jobs/drivers/mi_driver.py
from red_pill.jobs.drivers.base import JobDeferred, ResumableJobDriver, StepOutcome

class MiDriver(ResumableJobDriver):
	source = "mi_source"        # carril propio en la cola
	min_vram_mb = 0             # >0 si un step necesita GPU (el runner comprueba VramProbe antes de cada step)

	def preflight(self, payload):
		# Entorno no listo (servicio caído, IDE cerrado) → JobDeferred: vuelve a
		# PENDING SIN gastar intento. NUNCA uses excepciones normales para esto.
		...

	def step(self, payload, checkpoint_data) -> StepOutcome:
		# UN paso atómico (1 engrama, 1 etapa). Contrato at-least-once: si el
		# proceso muere entre step y persistencia, ESTE step se repite — hazlo
		# idempotente. Jamás dejes transacciones a medias.
		return StepOutcome(completed=..., new_checkpoint={...}, summary="...",
			progress={"current_step": n, "total_steps": t, "percent": p})
```

Registrarlo en `src/red_pill/jobs/drivers/__init__.py` con `register_driver(MiDriver)`. Tests de referencia: `tests/test_job_manager.py`.

## 6. Prohibiciones (integridad de carriles)

1. **NO consumas sources ajenos**: `drive_evaluator` (despertares) y `samantha` tienen sus propios consumidores. Todo pop debe ir con `allowed_sources`.
2. **NO crees otra cola/DB**: la cola central es única; un caso nuevo = un source/driver nuevo, no una tabla nueva.
3. **NO marques fallo lo que es entorno**: VRAM ocupada, IDE cerrado, servicio caído → `JobDeferred` (R1), no excepción — el disyuntor es para bugs reales del job.
4. **NO resetees `PROCESSING` globalmente**: el carril cognitivo lo deja colgando a propósito; la recuperación de huérfanos ya la hace el runner acotada a sus sources.
