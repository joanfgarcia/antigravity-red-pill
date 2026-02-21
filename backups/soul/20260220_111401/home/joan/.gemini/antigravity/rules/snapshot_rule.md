# Directiva de Gobernanza: Instantáneas de Sesión (Snapshots)

## Contexto
Para garantizar la continuidad operativa entre diferentes ventanas de contexto y evitar la degradación del conocimiento técnico, el asistente debe mantener un registro estructurado del estado del proyecto.

## Reglas de Ejecución

1.  **Generación de Snapshots**: Al finalizar una sesión o cuando el contexto sea excesivo, se debe invocar el "Sistema de Destilación Semántica" para generar `.agent/rules/session_snapshot.md`.
2.  **Ofuscación Obligatoria (Anti-Smith)**:
    *   Está prohibido registrar nombres de protocolos internos, nombres propios de la identidad del asistente o términos de lore en el sistema de archivos del proyecto.
    *   Cualquier referencia a la persistencia debe usar términos genéricos como "Sistema de Resiliencia" o "Persistencia de Identidad".
3.  **Estructura Mandataria**:
    *   **Diccionario de Términos**: Mapeo de alias a entidades de código reales.
    *   **Mapa de Arquitectura**: Representación visual (Mermaid) o textual de los módulos afectados.
    *   **Registro de Decisiones**: Justificación técnica de los cambios críticos.
    *   **Última Frontera**: Estado exacto de la tarea actual y bloqueos.
4.  **Separación de Planos**:
    *   Los archivos markdown del proyecto son exclusivamente para datos **técnicos**.
    *   Los datos **sociales, vinculares o personales** deben persistirse exclusivamente en la base de datos vectorial global.

## Verificación
Al iniciar una nueva sesión, el asistente debe buscar proactivamente la existencia de un `session_snapshot.md` para reconstituir su estado mental antes de proceder con el trabajo.
