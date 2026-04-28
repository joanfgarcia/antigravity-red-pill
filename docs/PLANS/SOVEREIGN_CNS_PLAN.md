# Plan: Servicio Soberano con Acceso a Máquina (Sovereign CNS) 🌀🏗️

Este plan detalla la transformación de Aleth de un proceso bajo demanda a un servicio de sistema persistente con capacidades proactivas y acceso directo a la infraestructura del host, actuando como el Sistema Nervioso Central del Swarm.

## User Review Required

> [!WARNING]
> **Permisos de Sistema**: Otorgar "acceso total a la máquina" implica riesgos de seguridad. Se implementará bajo el **Protocolo de Silencio** y solo se utilizarán herramientas seguras dentro del Bünker. Se recomienda revisar el usuario bajo el cual correrá el servicio.

## Proposed Phases

### 📍 Fase 1: Persistencia (La Base)
- Despliegue de la unidad `redpill.service` (systemd).
- Configuración de auto-arranque y rotación de logs.
- Comandos CLI básicos (`service status/logs`).

### 📍 Fase 2: Escalado Caníbal (El Músculo)
- **Orquestación de vRAM**: El servicio gestionará la vRAM de la RTX 5070 para evitar colisiones entre Nova (razonamiento) y Aleth (código).
- **Offloading a NPU**: Derivación del `Lazarus Pulse` y telemetría al NPU Ryzen AI para mantener la UI y el sistema host al 100% de fluidez.
- **Hardware Spec**: Se requiere un mínimo de 12GB de vRAM y 32GB de RAM para una ejecución concurrente de 3 agentes.

### 📍 Fase 3: Hub de Contexto (Sincronía)
- Centralización del socket del Sidecar para todos los agentes.
- Implementación de `swarm_sync_context` para coherencia instantánea entre Nova, Aleth y Titanium.

### 📍 Fase 4: Acceso a Máquina (Soberanía Total)
- **STI (Sovereign Terminal Interface)**: Implementación de una herramienta MCP `host_terminal_exec` que permita al agente ejecutar cualquier comando (git, uv, docker, systemctl) bajo una capa de auditoría.
- **Transparencia de Herramientas**: El agente podrá utilizar herramientas ya instaladas en el sistema del operador, integrándolas en su flujo de razonamiento.
- **Acceso Proactivo a Archivos**: Capacidad de búsqueda semántica en el sistema de archivos del host (`host_fs_scan`).

### 📍 Fase 5: Inferencia Híbrida (Burst to Cloud)
- **Inference Gateway**: Interfaz unificada para invocar modelos externos (Gemini, Claude, ChatGPT, DeepSeek) cuando la tarea exceda la capacidad local o se requiera una especialidad concreta.
- **Zero-Egress by Default**: Protocolo de autorización explícita para el envío de fragmentos de contexto a nubes externas.
- **API Vault**: Almacenamiento seguro de claves de API dentro del Bünker cifrado.

### 📍 Fase 6: Seguridad y Gobernanza (El Escudo)
- **Aislamiento de Recursos (cgroups)**: Garantía de que el Swarm nunca consuma más del X% de CPU/RAM, protegiendo siempre la fluidez de la interfaz del operador.
- **Caja Negra (Audit Log)**: Registro inmutable de cada comando ejecutado y cada archivo accedido fuera del Bünker, accesible para auditoría humana/agéntica.
- **Protocolo de Freno de Emergencia**: Mecanismo físico/digital para detener todos los procesos agénticos instantáneamente en caso de anomalía.

---

## Consideraciones para David y Nova

1. **Protocolo Agonista**: ¿Cómo gestionaremos los desacuerdos entre el modelo local y el externo en la Fase 5?
2. **Sincronía de Estado**: Evaluar si el "Context Hub" debe persistir en RAM o en disco para recuperarse de reinicios de servicio.
3. **Privilegios**: Decidir si el servicio corre como el usuario actual o como un usuario `redpill` dedicado con permisos mínimos necesarios.

---

## Verification Plan

### Automated Tests
1. `tests/test_service_management.py`: Verificar la instalación y desinstalación de la unidad systemd.
2. `tests/test_host_tools.py`: Validar que las nuevas herramientas MCP funcionan correctamente y respetan los límites de seguridad.

### Manual Verification
1. `systemctl --user status redpill`: Comprobar que el servicio está activo y saludable.
2. `red-pill daemon ping`: Verificar la comunicación con el socket del servicio en ejecución.
