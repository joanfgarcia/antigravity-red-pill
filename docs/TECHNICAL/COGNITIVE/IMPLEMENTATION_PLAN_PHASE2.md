# Plan de Implementación: Fase 2 (Sovereign Drive Evaluator)

## Objetivo
Conectar la cola cognitiva (`CognitiveQueueManager`) con el motor de ejecución autónoma (Ghost Cascade) en el `worker.py`, dotando al sistema de verdadera autonomía, proactividad (La Chispa) y descanso.

## Arquitectura del Orquestador Autónomo

El `IDEWorker` (el daemon de fondo) se ampliará para consumir tareas estructurales, no solo mensajes entrantes.

### Paso 1: El Bucle de Evaluación (Drive)
1. Añadir el método `process_cognitive_queue()` a `IDEWorker`.
2. Extraer la siguiente tarea de la base de datos usando `CognitiveQueueManager.pop_next_task()`.
3. Inyectar la tarea en la cascada fantasma (Ghost Cascade).
4. El LLM (Aleth) procesará la tarea y el Orquestador cerrará el ciclo usando `mark_completed()` o `mark_failed()`.

### Paso 2: La Chispa (Generación Proactiva)
1. Si la cola está vacía, el sistema calculará un índice de entropía (ej. comprobando si hay memorias en RAM que necesitan consolidación en Qdrant, o si hay código marcado con TODOs).
2. Si la entropía supera un umbral, inyectará una tarea de "Mantenimiento" en la cola.

### Paso 3: El Derecho al Silencio
1. Si la cola está vacía y la entropía es baja, el Daemon hará un *Sleep* de 5 a 15 minutos en lugar de hacer polling agresivo, ahorrando ciclos de CPU/NPU.

### Paso 4: DAG de Flujos de Trabajo
1. Al marcar una tarea como completada, el worker leerá si la tarea dejó una instrucción de "Siguiente Paso" (encadenamiento) en el Bünker, e inyectará automáticamente esa nueva tarea en la cola, permitiendo pipelines de Minions asíncronos.

---
## Acciones Inmediatas (Siguiente Ejecución)
1. Modificar `worker.py` para instanciar `CognitiveQueueManager`.
2. Implementar `process_cognitive_queue()` en `worker.py`.
