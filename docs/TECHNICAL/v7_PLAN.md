# Red Pill v7.0: Foundation & Autonomous Drive Plan

Este documento consolida las iniciativas principales para el salto a la **v7.0**. Tras la revisión de la arquitectura, hemos decidido adoptar un enfoque de **"pequeño pero profundo"** (enfocado en fundamentos sólidos y autonomía controlada), dividiendo las entregas en un MVP estricto y un roadmap posterior.

---

## FASE 7.0 MVP (Fundamentos y Autonomía Controlada)

### 1. Bünker Onboarding & One-Click Install (`bunker init` & `bunker install`) [Alta Prioridad]
- **Objetivo:** Comando unificado de inicialización que realiza un perfilado automático de hardware, seguido de un instalador determinista de un solo click.
- **Enfoque Declarativo:** `bunker init` genera un archivo `bunker.profile.yaml` (definiendo `MemoryMax`, *quantization*, workers). Posteriormente, `bunker install` lee este perfil y automatiza `uv sync`, descarga de modelos vía HuggingFace, despliegue de Quadlets (Qdrant/Redis) y registro en `systemd`.
- **Por qué:** Tiene el mayor ROI inmediato. Transforma el despliegue de un proceso manual y tedioso a una experiencia "Plug-and-Play" Sovereign.

### 2. Autonomía Cognitiva (Sovereign Drive) - SÓLO FASE 1
- **Objetivo:** Implementar la infraestructura base para romper el ciclo síncrono del IDE.
- **Cognitive Queue (Fase 1):** Creación de una cola intermedia (`cognitive_queue.db`) donde los estímulos externos (ej. Telegram) y los internos (entropía, fragmentación) se apilan como tareas. Ingestión básica.
- **Safe Autonomous Mode:** Dado el peligro inherente de los daemons autónomos, esta fase incluirá límites duros (CPU/RAM) y un *kill-switch* accesible para prevenir fugas de recursos o ruido excesivo antes de habilitar los bucles de evaluación heurística.

### 3. Observabilidad y Agregación de Telemetría (MVP)
- **Objetivo:** Un panel de control centralizado básico para monitorizar el ecosistema.
- **Enfoque Simple:** Comenzaremos con una UI de terminal utilizando `textual`. El objetivo es no "volar a ciegas" con las colas de Celery, Pain Signals y estados de los minions, sin incurrir en la complejidad de un backend web pesado en esta fase.

### 4. Hardening de Seguridad y Estabilidad (Rutas)
- **Robustez de Rutas (Path Resolution):** Añadir tests de integración robustos para entornos inmutables y de contenedores (Silverblue, Flatpak).

---

## FASE 7.1 / 7.2 (Evolución y Despliegue)

### Sovereign Drive (Fases 2 y 3)
- **Orquestador Autónomo (Fase 2):** Daemon que evalúa la `Cognitive Queue` usando el *Expected Information Gain* como heurística de prioridad. Implementación del **Derecho al Silencio** (Sleep) y tareas proactivas.
- **Disyuntor de Frustración (Fase 3):** Mecanismo defensivo que etiqueta tareas fallidas o excesivamente costosas como "FRUSTRADAS" para evitar bucles cognitivos infinitos.

### Criptografía Swarm
- **TreeKEM:** Completar la adopción total del protocolo MLS (RFC 9420) para mensajería y sincronización cifrada de extremo a extremo entre los agentes del Enjambre.

### Evolución de la Observabilidad
- Exponer una API ligera sobre el motor de agregación de telemetría para permitir interfaces web o herramientas externas en el futuro, mejorando la UI/UX del dashboard central.

---
*Nota: La paridad en Windows queda oficialmente designada como un esfuerzo "Community-Driven", para no penalizar el desarrollo de las funciones core Unix-first ni el avance hacia la autonomía real.*
