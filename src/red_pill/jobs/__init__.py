"""Centralized Job Manager (plan: Aleth_Core/IMPLEMENTATION_PLAN_UNIFIED_JOB_MANAGER.md).

Centraliza — no duplica — la ejecución de trabajos sobre las piezas vivas del kernel:
la cola persistente es `CognitiveQueueManager` (bunker_queue.db), el runner es
`core/queue_worker.py` (shot-and-forget) y la notificación es MinionInbox + SAS.
Este paquete solo aporta el contrato `ResumableJobDriver` y su registro.
"""
