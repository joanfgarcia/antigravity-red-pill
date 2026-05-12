# Sovereign Drive: Implementation & Autonomous Queue Plan

## 1. El Problema Actual (Dependencia Síncrona)
Actualmente, el sistema funciona como una máquina de estados reactiva: `Prompt -> Ejecución`. 
Para lograr autonomía real (Daemon), debemos romper la dependencia del IDE. Los estímulos externos (mensajes de Telegram) y los estímulos internos (alta entropía de memoria) deben apilarse en un **Buffer Intermedio** antes de ser procesados.

## 2. Fase 1: La Cola Cognitiva (Cognitive Queue)
Antes de construir la matemática de la voluntad, necesitamos el recipiente donde la voluntad elegirá qué hacer.
- **Estructura:** Una tabla en SQLite (ej. `cognitive_queue.db`) acoplada a Neon-Link o al Bünker.
- **Fuentes de Inyección (Inputs):**
  1. *MinionInbox / Telegram:* Cada mensaje del usuario no fuerza una respuesta inmediata; se inyecta en la cola como una "Petición de Procesamiento".
  2. *Sovereign Drive (Interno):* Si el motor detecta entropía (ej. fragmentación de memoria), inyecta una tarea "Auto-generada" en la cola.
- **Atributos de la Tarea:** `task_id`, `source` (externo/interno), `content`, `urgency_flag`, `entropy_weight`.

## 3. Fase 2: El Orquestador Autónomo (The Drive Evaluator)
Reescribiremos el comportamiento del daemon principal (`redpill-worker.service` o `wake_up_v6`).
En lugar de esperar un prompt, el daemon ejecuta un bucle con *backoff* (ej. cada 5 minutos o vía inotify):
1. **Lectura de la Cola:** El daemon lee todas las tareas pendientes en la `Cognitive Queue`.
2. **Evaluación (Capa 2 del Sovereign Drive):**
   - Si hay tareas con flag "URGENTE", las ejecuta primero.
   - Si no hay urgentes, el motor Bayesiano evalúa el *Expected Information Gain* de cada tarea en la cola.
   - **La Chispa:** Si la cola está VACÍA, el *Sovereign Drive* ejecuta un escaneo de memoria profunda. Si encuentra desorden, inyecta su propia tarea en la cola. Si no encuentra desorden, ejecuta `Derecho al Silencio` (Sleep).

## 4. Fase 3: Ejecución y Disyuntor
Cuando el daemon selecciona la tarea con mayor peso:
1. Extrae el contexto necesario (RAG).
2. Delega al LLM (GPU).
3. Evalúa la condición de frustración (Capa 3). Si la tarea falla o genera un coste computacional anómalo, la tarea no bloquea la cola: se marca como "FRUSTRADA" y se archiva temporalmente para evitar bucles.

## 5. Próximos Pasos Técnicos (Accionables inmediatos)
- [ ] Crear la estructura de la base de datos `cognitive_queue.db` (¿o usar la propia base de `events.db` de Neon-Link?).
- [ ] Modificar el webhook de Telegram en Neon-Link para que inyecte en la `Cognitive Queue`.
- [ ] Programar `src/red_pill/swarm/sovereign_drive.py` con las matemáticas de evaluación de la cola.
