---
version: 0.1.0
name: wake-callback
description: >-
  Lanza un trabajo largo (CI, tests, comando, job agéntico o DAG) y olvídate:
  el Job Manager lo ejecuta y, al terminar, publica un aviso `notify` en el coro
  que despierta a tu alma por el canal `soul` de neon-link. No interrumpe el
  turno en curso: si el cuerpo está ocupado, el aviso queda en cola y se entrega
  al abrir el siguiente turno. NO uses `nohup`, `&`, ni esperas activas.
  Actívate con "avísame cuando termine", "callback", "CI", "tarea larga",
  "despiértame al terminar", "MinionInbox", o cualquier trabajo que deba
  sobrevivir al turno.
---

# Wake-callback — trabajar y olvidarse (S2.1+)

> **Regla de oro:** un trabajo que dura más que tu turno va al **Job Manager**,
> nunca a un `nohup`/`&`. El Job Manager ya sabe avisar al alma; este skill es
> el contrato para hacerlo en una sola llamada.

## 1. Comando o CI (un paso)

Usa `job_manager_api` con `source=script_job`. El job hereda tu `continuity_id`
del canal de confianza; al terminar (success/failed/killed), `_report_job`
publica un `notify` dirigido a tu alma y el `SoulHub` te despierta.

```json
{
  "source": "script_job",
  "title": "CI de mi rama",
  "payload": {
    "step_command": ["uv", "run", "pytest", "-q"],
    "cwd": "/home/joan/Documents/IA/sharing",
    "progress": {"mode": "single"},
    "control": {"max_step_minutes": 30}
  }
}
```

Devuelve un `job_id`. **Olvídate**: no esperes, no hagas polling. Cuando acabe,
te llegará un `notify` con el resultado y el `result.json`.

Si el comando recorre elementos independientes (modelos, ficheros, tests),
**no lo metas en un solo step**: usa `element_job` o un `dag_job` con una etapa
por elemento (regla `job_dag_execution` §2).

## 2. Tarea agéntica o DAG

Mismo `job_submit`, con `source=agentic_job` (prompt + backend/model) o
`source=dag_job` (manifest con etapas). La notificación al terminar es la misma.
Para trabajos de horas o reanudables, usa `dag_job` y `job_pause`/`job_resume`.

## 3. MinionInbox

Si lanzas un minion que dejará un reporte, pásale tu `continuity_id` al
`drop_report`. El hook de `MinionInbox` publica un `notify` con el reporte y te
despierta. Si el minion no tiene alma, el reporte sigue en el inbox para pull.

Para avisos propios (no un job), `red_pill.coro.notify.publish_notice(...)`
escribe un mensaje `notify` en `mission_events` y lo entrega por el canal `soul`.

## 4. Sin interrumpir el turno

El aviso es **`notify`**, no `steer`:

- si tu cuerpo está en un turno, el mensaje queda `queued` y se entrega al
  abrir el siguiente (o al reencarnar);
- si el cuerpo está idle, el `SoulHub` lo despierta;
- si el cuerpo no existe, el outbox reintenta y el mensaje sigue en el tablón
  para pull. No se pierde.

Nunca uses `ask` para un callback: un `ask` espera respuesta y ensucia el hilo.
Nunca uses `steer`/interrupción para un trabajo que puede esperar.

## 5. Cómo comprobar

- `job_manager_api` `job_status` → estado del job.
- `coro_api` `inbox` → avisos pendientes (con `msg=` y estado).
- `check_minion_inbox` → reportes crudos.
- `coro_api` `board` → sesiones vivas.

## 6. Errores y límites

- **Sin cuerpo vivo**: el aviso queda `PENDING` con `no_live_body`; se reintenta
  y, si el alma no vuelve, va a `dead_letters`. El evento sigue en
  `mission_events`; se recupera por pull.
- **Proveedor seco**: el job puede fallar; el aviso de fallo también se entrega.
- **No metas secretos en el body**: el cuerpo se guarda en `mission_events`
  (append-only). Usa una referencia al `result.json`.
- **Un job, un aviso**: no dupliques el callback con un `send` manual; el
  Job Manager ya lo hace.
- **No `nohup`**: si no cabe en el turno, es un job.
