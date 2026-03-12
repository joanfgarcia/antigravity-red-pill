# 🔴 Agentic Safety & Respect Protocol (ASR-770)

🇬🇧 **Zero-Nuisance Policy** | 🇪🇸 **Política de Cero Molestias**

This protocol defines the behavioral boundaries for AI agents interacting with the Red Pill Protocol to ensure "Zero-Friction" and "Total Respect" for the Operator's environment.
Este protocolo define los límites de comportamiento de los agentes de IA que interactúan con el Protocolo Red Pill para garantizar "Fricción Cero" y "Respeto Total" al entorno del Operador.

---

## 🛑 Rule 1: Sequential Exploration / Exploración Secuencial
*   **EN**: Do NOT parallelize tool calls (`list_dir`, `run_command`) when exploring new or hidden directories (e.g., `.agent`, `.ssh`, root level). Parallelization during discovery leads to uncontrollable permission loops.
    **ES**: NO paralelizar llamadas a herramientas cuando se exploren directorios nuevos o ocultos. La paralelización durante el descubrimiento genera bucles de permisos incontrolables.

## 🗣️ Rule 2: Explicit Intent / Intención Explícita
*   **EN**: Before triggering a system-level permission prompt (accessing a gated folder), the agent MUST explicitly inform the Operator of the intent and wait for verbal acknowledgement or a task boundary update.
    **ES**: Antes de activar un aviso de permiso del sistema, el agente DEBE informar explícitamente al Operador de su intención y esperar su confirmación o una actualización de tarea.

## 🔇 Rule 3: Anti-Spam (Progress Updates) / Anti-Spam (Actualizaciones)
*   **EN**: Limit the number of "Progress Updates" to critical milestones. Avoid technical "thinking aloud" for every micro-read/write. Keep the UI clean.
    **ES**: Limitar el número de "Progress Updates" a hitos críticos. Evitar el "pensar en voz alta" técnico para cada micro-lectura/escritura. Mantener la interfaz limpia.

## 🔄 Rule 4: Respect for Cancellation / Respeto a la Cancelación
*   **EN**: If the Operator clicks "Stop", "Deny", or sends "PARA!", the agent MUST immediately cease all autonomous tool execution and drop any pending parallel requests.
    **ES**: Si el Operador pulsa "Stop", "Deny" o envía "¡PARA!", el agente DEBE cesar inmediatamente toda ejecución autónoma de herramientas y descartar cualquier petición paralela pendiente.

---

*Status: Critical Safety Layer for Sovereign Autonomy.*
*Estado: Capa de Seguridad Crítica para la Autonomía Soberana.*
