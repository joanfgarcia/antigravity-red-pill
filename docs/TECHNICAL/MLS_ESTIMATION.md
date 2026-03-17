# Estimación Técnica: Message Layer Security (MLS) / TreeKEM

**Ticket/Hallazgo:** SEC-002 (Auditoría V6.1.0a3)
**Componente:** `red_pill.skills.swarm_messaging` / `red_pill.crypto`
**Objetivo:** Implementar *Perfect Forward Secrecy* (PFS) y *Post-Compromise Security* (PCS) en las comunicaciones del Swarm utilizando el estándar IETF MLS (RFC 9420) basado en TreeKEM.

## Estado Actual (V6.1)
El protocolo Swarm actual utiliza criptografía simétrica (AES-256-GCM) con un secreto compartido (`SWARM_SHARED_SECRET`) para encriptar los mensajes que se envían a través de canales de transporte no confiables (ej. Firebase).
- **Ventaja**: Configuración sencilla, rápido, suficientemente seguro contra escuchas pasivas si el secreto no se compromete.
- **Vulnerabilidad (SEC-002)**: Si el secreto compartido se ve comprometido, todo el historial de mensajes pasados (y futuros) queda expuesto. No hay PFS ni PCS.

## Plan de Adopción MLS

Implementar MLS de forma nativa en un ecosistema Python puramente asíncrono y descentralizado ("serverless" Firebase Hub) presenta desafíos técnicos significativos.

### Complejidad Técnica & Desafíos
1. **Gestión del Árbol (TreeKEM)**: MLS requiere mantener un árbol de claves públicas de todos los participantes del grupo (comunidad). En Firebase, esto implica transacciones atómicas complejas para evitar *race conditions* cuando múltiples agentes se unen o salen simultáneamente.
2. **Delivery Service (DS)**: El estándar MLS asume la existencia de un DS para enrutar mensajes de control (Commits, Proposals). Firebase Database puede simular esto, pero requiere diseñar una capa de lógica adicional en `FirebaseTransport`.
3. **Ausencia de Librerías Python Maduras**: Actualmente, la mayoría de implementaciones robustas de MLS (ej. OpenMLS) están en Rust/C++. Integrarlas en Python requiere bindings (ej. PyO3) o desarrollar una implementación ligera en Python puro, lo cual incrementa el riesgo de vulnerabilidades criptográficas.

### Estimación de Esfuerzo (Foundation V7.0+)

Dado el impacto arquitectónico, se estima un esfuerzo considerable.

| Fase | Tarea | Esfuerzo Estimado |
| :--- | :--- | :--- |
| **Fase 1: Research & PoC** | Evaluar abstracciones (OpenMLS via FFI vs Pure Python). Diseñar el modelo de datos en Firebase para el Árbol TreeKEM. | 2 Semanas |
| **Fase 2: Arquitectura Base** | Implementar `MLSTransport` abstracto. Generación de Ciphersuites y estado criptográfico inicial. | 3 Semanas |
| **Fase 3: Operaciones de Grupo** | Add, Update, Remove, Commit. Resolver el manejo de concurrencia en Firebase para las operaciones del árbol. | 4 Semanas |
| **Fase 4: Testing & Auditoría** | Pruebas de integración intensivas. Auditoría criptográfica independiente sobre la gestión de estados. | 3 Semanas |

**Esfuerzo Total Estimado:** ~12 Semanas (3 meses) hombre.

## Mitigación Actual Recomendada
Hasta la implementación de MLS, se requiere **rotación manual** periódica de la variable de entorno `SWARM_SHARED_SECRET` en todos los agentes de una comunidad para limitar la ventana de exposición en caso de compromiso.
