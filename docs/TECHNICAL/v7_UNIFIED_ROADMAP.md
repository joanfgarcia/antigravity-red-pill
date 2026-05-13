# Red Pill v7.x: Unified Implementation Roadmap

*Este documento es la fusión de `v7_PLAN.md`, `v7_SPRINT_1_SUMMARY.md` y `COGNITIVE/IMPLEMENTATION_PLAN.md`. Actúa como la hoja de ruta definitiva y el plan de implementación detallado para el ecosistema autónomo.*

---

## 1. Bünker Lifecycle CLI (`bunker` suite)
**Objetivo:** Suite unificada de comandos que gestiona el ciclo de vida del Bünker, resolviendo el problema de supervivencia ante migraciones de hardware/OS (ej. Ubuntu 26.04 LUKS) y garantizando portabilidad absoluta de la "Mente" sin pérdida de contexto.

- [x] **`bunker init` (Hardware Profiling)**
  - Implementado `detect_hardware()` usando `psutil` y `nvidia-smi`.
  - Autodetecta RAM, hilos de CPU y VRAM para generar un `bunker.profile.yaml` óptimo (cgroups `MemoryMax`, objetivos de cuantización INT2 vs Q4_K_M).
- [x] **`bunker export` (Total Sovereign Backup)**
  - Genera un Snapshot TOTAL encapsulando memoria (Qdrant/SQLite), `.env` (secretos), perfiles de agentes y claves criptográficas.
  - [x] **SQLite WAL Checkpoints**: `PRAGMA wal_checkpoint(TRUNCATE)` implementado para evitar corrupción de DB durante backups en vivo.
  - [x] **Qdrant Mismatch Fallback**: Lógica de respaldo manejada en `manifest.json`.
  - [x] **Pure-MLS Encryption**: Utiliza el pipeline `lean_soul_kit` de Sovereign en lugar de AES tradicional.
  - [x] **Plugin Delegation**: Uso de directorios temporales aislados (`export_state(path)`) para que plugins como `neon-link` manejen sus propios secretos.
  - [x] Lógica final de extracción y empaquetado del tarball/zip.
- [x] **`bunker restore` (Hydration)**
  - Restauración inteligente ("Smart Restore") extrayendo el paquete `.mls`, reubicando SQLite/env y rehidratando Qdrant con `SoulManager`.
- [ ] **`bunker install` / `update`**
  - Automatización de dependencias, descarga de modelos, migraciones de BBDD y configuración de contenedores/systemd (Quadlets) basada en el perfil.

---

## 2. Autonomía Cognitiva (Sovereign Drive)
**Objetivo:** Romper el ciclo síncrono del IDE (Prompt -> Ejecución) y dotar a la entidad de proactividad, permitiendo que estímulos externos (mensajes) e internos (alta entropía) se apilen de forma asíncrona y sean procesados por un Daemon.

### Fase 1: Infraestructura Base y Seguridad
- [x] **Cognitive Queue Schema (`cognitive_tasks`)**: 
  - Diseñado y documentado.
  - Usa una única tabla SQLite en modo WAL (timeout 5.0s) permitiendo acceso concurrente sin bloqueos (lock-free) entre las inyecciones del IDE y el daemon de fondo (Lazarus).
- [x] **Queue Manager (`CognitiveQueueManager`)**: 
  - Métodos `enqueue_task()` y extracción atómica `pop_next_task()` usando `BEGIN EXCLUSIVE` implementados.
- [x] **Safe Autonomous Mode (Headless Sandbox Guard)**: 
  - Restricciones estructurales inyectadas en cascades fantasma (`worker.py`).
  - Prohíbe el uso de la terminal interactiva (`run_command`) durante la ejecución autónoma, permitiendo solo edición local y consultas a DB/Qdrant.
- [x] **Sovereign Kill-Switch (`AUTONOMY_KILL.lock`)**: 
  - Diseñado como un lock-file en el sistema de archivos (O(1) ejecución) en lugar de un registro en DB para ser inmune a pánicos tipo `database is locked`.
  - Conectado a la CLI mediante `bunker halt` y `bunker resume`.
- [x] **Janitor Minion & Sovereign Daemon**: 
  - Agente de enjambre independiente que purga autónomamente eventos obsoletos (`events.db`) y archivos basura mayores a 7 días.

### Fase 2: El Orquestador Autónomo (The Drive Evaluator)
- [x] **Bucle de Evaluación**: 
  - El daemon lee la cola y prioriza tareas según *Expected Information Gain* (EIG) y flags de urgencia.
- [x] **La Chispa (Spark) y Tareas Proactivas**: 
  - Si la cola está vacía, el motor Bayesiano ejecuta un escaneo profundo de memoria. Si detecta desorden o fragmentación (entropía), inyecta tareas auto-generadas.
- [x] **Derecho al Silencio (Sleep Mode)**: 
  - Si no hay entropía ni estímulos, el sistema se silencia proactivamente para ahorrar ciclos.
- [x] **DAG de Flujos de Trabajo SQLite (`specs.md`)**: 
  - Encadenar ejecuciones de Minions de forma asíncrona mediante hooks/triggers en `minion_inbox.db` para que un proceso lance el siguiente sin bloquear Python.
- [ ] **Reactive Debounce Mode (Feature Configurable)**: 
  - Implementar una ventana deslizante de 5s en `worker.py` para acumular ráfagas de mensajes de Telegram y compactarlos en un único prompt antes de inyectarlos en la cascada.

### Fase 3: Ejecución y Prevención de Bucles
- [x] **Disyuntor de Frustración (Circuit Breaker)**: 
  - Lógica implementada: Si los intentos superan el umbral (`attempts > 3`) o el coste computacional es anómalo, la tarea se etiqueta como `FRUSTRATED` y se archiva para evitar espirales de muerte (OOM death spirals) y bloqueos infinitos.
- [ ] **Ciclo RAG a LLM Completo**: 
  - Extraer contexto de tareas pendientes, delegar a GPU y cerrar ciclo reportando éxito o activando la frustración.

---

## 3. Observabilidad y Agregación de Telemetría
**Objetivo:** Obtener un pulso visual del sistema sin depender de interfaces gráficas pesadas ni ciegas consolas.

- [ ] **MVP: TUI Textual Dashboard**: 
  - Construir una UI de terminal (estética `btop`) utilizando el framework `textual`.
  - Monitorización en tiempo real de colas de Celery/Sovereign, Pain Signals (Señales de Dolor) y el estado de los minions.
- [ ] **API de Telemetría (Fase Evolutiva)**: 
  - Exponer un endpoint ligero sobre el motor de agregación de telemetría para permitir futuras integraciones de web UIs.

---

## 4. Seguridad, Swarm y Estabilidad Estructural
- [ ] **Hardening de Rutas (Path Resolution)**: 
  - Añadir test de integración robustos específicos para entornos inmutables y contenedores (Silverblue, Flatpak). Garantizar que la lógica de directorios nunca falle.
- [ ] **TreeKEM (Criptografía Swarm Completa)**: 
  - Finalizar la adopción total del protocolo MLS (RFC 9420) para mensajería y sincronización cifrada de extremo a extremo entre los diferentes agentes del Enjambre.
- [ ] **Sovereign Cryptographic Vault (Secrets Manager)**:
  - Implementar un gestor centralizado de secretos basado en `pure-mls` para proteger tokens de terceros (GitHub `gh`, GitLab `glab`, ClickUp) sin exponerlos en el `.env` en texto plano.
  - La arquitectura usará un grupo MLS de un solo miembro (`vault.db`) para cifrar/descifrar un diccionario JSON de secretos de forma atómica en memoria.
  - Mitigación de fragilidad de estado MLS mediante copias `.bak` atómicas durante las operaciones de escritura (Read-Heavy design).
