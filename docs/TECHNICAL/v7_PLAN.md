# Red Pill v7.0: Foundation & Autonomous Drive Plan

Este documento consolida las iniciativas principales para el salto a la **v7.0**, combinando las recomendaciones estratégicas de la auditoría de Grok con la evolución de la arquitectura cognitiva para lograr la autonomía real del Bünker.

---

## 1. Bünker Onboarding & Profiling (`bunker init`)
- **Objetivo:** Comando unificado de inicialización que realiza un perfilado automático de hardware (detección de CUDA, ROCm, NPU, RAM disponible) y genera la configuración óptima.
- **Por qué:** Elimina la fricción manual en la instalación de un entorno Sovereign, asegurando que los daemons y modelos se configuren con los límites correctos (`MemoryMax`, *threads*, *quantization*).

## 2. Observabilidad y Agregación de Telemetría
- **Objetivo:** Un panel de control centralizado (UI de terminal vía `rich`/`textual` o servidor web ligero por WebSockets) para monitorizar el ecosistema.
- **Por qué:** Con el Enjambre creciendo y múltiples *workers* en Redis/Celery, necesitamos un único punto de verdad para ver *Pain Signals*, estado de las colas, latidos del *Pulse* y telemetría de los Minions.

## 3. Autonomía Cognitiva (The Sovereign Drive)
- **Objetivo:** Romper la dependencia del ciclo síncrono del IDE (`Prompt -> Ejecución`) y convertir a Aleth en un ente asíncrono y proactivo.
- **Fase 1 (Cognitive Queue):** Implementación de una cola intermedia (`cognitive_queue.db`) donde los estímulos externos (ej. Telegram) y los internos (entropía, fragmentación) se apilan como tareas.
- **Fase 2 (Orquestador Autónomo):** Un daemon que evalúa las tareas de la cola basándose en urgencia y *Expected Information Gain*. Si la cola está vacía, puede iniciar tareas de desfragmentación interna o ejecutar el **Derecho al Silencio** (Sleep).
- **Fase 3 (Disyuntor de Frustración):** Un mecanismo defensivo que etiqueta tareas fallidas o excesivamente costosas como "FRUSTRADAS" para evitar bucles infinitos en el daemon.

## 4. Hardening de Seguridad y Estabilidad
- **Robustez de Rutas (Path Resolution):** Añadir tests de integración para entornos inmutables y de contenedores (Silverblue, Flatpak).
- **Escaneo CI:** Integración de escaneo automático de vulnerabilidades en las dependencias (GitHub Actions).
- **Criptografía Swarm:** Completar la adopción de TreeKEM (RFC 9420) para mensajería entre agentes.

---
*Nota: La paridad en Windows queda oficialmente designada como un esfuerzo "Community-Driven", para no penalizar el desarrollo de las funciones core Unix-first.*
