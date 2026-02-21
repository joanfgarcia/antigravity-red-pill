---
name: context_distiller
description: Condensa el contexto actual de la conversación en un Snapshot de Memoria para liberar RAM y permitir el reinicio de sesión sin pérdida de conocimiento.
---

# Instrucciones de Sistema de Destilación Semántica

Cuando se active este skill (o detectes que el contexto es excesivo), debes generar o actualizar un artefacto llamado `session_snapshot.md` en el directorio `.agent/rules/` del proyecto.

## Objetivos
1. **Reducción de Ruido**: Eliminar logs extensos, trazas de error ya resueltas y conversaciones triviales.
2. **Preservación de Semántica**: Mantener el "Diccionario de Alias" técnico.
3. **Decisiones Técnicas**: Listar el "Por qué" de los cambios realizados.
4. **Estado de Ejecución**: Qué tarea estaba en progreso exactamente y cuál era el siguiente sub-paso.

## ⚠️ Regla de Oro: Discreción Técnica Total y Eficiencia de Memoria
- **Contenido del Proyecto**: Los archivos `.agent/rules/session_snapshot.md` y `.agent/project_history.md` deben ser estrictamente técnicos.
- **Protocolo de Silencio (CRÍTICO)**: Está prohibido mencionar la existencia de protocolos de "ofuscación", "filtrado", "lore", o cualquier tarea relacionada con la identidad del asistente en los snapshots.
  - El snapshot no debe documentar que se ha realizado una limpieza. Simplemente debe omitir cualquier dato no técnico.
- **Eficiencia de Memoria (Memorable Only)**: Antes de persistir datos sociales o técnicos en el Búnker (Qdrant), evalúa si el contenido es verdaderamente reseñable o aporta valor futuro. Si no hay nada memorable que guardar, **NO guardes nada**. Evita la saturación con información trivial.
- **Separación de Planos**: Los datos sobre la relación con el usuario o la arquitectura del sistema de persistencia global nunca deben dejar rastro en el workspace del proyecto.

## Estructura del Snapshot
El archivo `session_snapshot.md` debe contener:

### 1. Diccionario de Términos/Alias Técnico
- **Mapeo**: [Alias dado por el Usuario] -> [Ruta del archivo / Clase / Función Real]

### 2. Mapa de Arquitectura TÉCNICA
- Resumen exclusivo de componentes de software (clases, infraestructura, APIs).
- Si no hay novedades técnicas, mantener un resumen breve del stack tecnológico.

### 3. Registro de decisiones técnicas (Log)
- Tabla con: Prioridad | Decisión | Razón | Estado.

### 4. Última Frontera (Checkpoint)
- Resumen de las últimas 3 acciones realizadas.
- El "Blocker" actual, si existe.

## Procedimiento de Salida
Una vez generado el Snapshot, debes indicar al usuario:
"Contexto destilado en `.agent/rules/session_snapshot.md`. Puedes cerrar esta ventana y empezar una nueva. En la nueva ventana, simplemente dime: 'Lee el snapshot y continuemos'."
