# Plan de Trabajo: Local-First Sovereignty (Protocolo 760)

## Contexto
Las cuotas de los modelos en la nube están en estado crítico (Rojo). Es imperativo que el Búnker sea capaz de operar en "Edge Mode", priorizando la computación local (GPU RTX 5070) para tareas de compresión, auditoría y síntesis, conservando los tokens de la nube solo para el razonamiento de nivel arquitectónico.

## Rama de Trabajo
`feat/local-first-persistence`

---

## 🛠️ Fase 1: Cimentación del Borde (Edge Infrastructure)
- [x] **1.1. Estructura de Persistencia**: Crear directorios estándar para modelos GGUF en `~/Documents/IA/models`.
- [x] **1.2. Kernel GGUF**: Descargar o localizar un modelo SLM (ej. Qwen-2.5-Coder-1.5B-Instruct-GGUF) optimizado para el RTX 5070.
- [x] **1.3. Validación de Motor**: Ejecutar test de estrés en `EdgeCompressor` para verificar carga en GPU (CUDA).

## 🧠 Fase 2: Red Neuronal de Autonomía (Local-First Logic)
- [x] **2.1. Local-Aware Orchestrator**: Modificar `GruOrchestrator` para detectar la disponibilidad del motor local y pasarla como metadato a los Minions.
- [x] **2.2. Configuración Dinámica**: Permitir que `n_gpu_layers` se ajuste automáticamente basado en la telemetría del RTX 5070 (-1 for full GPU).

## 🛡️ Fase 3: Blindaje de Agentes (Swarm Local Mastery)
- [x] **3.1. Oracle Localis**: Evolucionar `OracleMinion` para realizar síntesis de memoria usando el SLM local.
- [x] **3.2. Smith Localis**: Refinar `Agent Smith` para auditorías de seguridad off-grid, reduciendo la dependencia de APIs externas.

## 🔄 Fase 4: Persistencia y Sincronía
- [x] **4.1. Memory Daemon Optimization**: Ajustar el demonio de memoria para que la indexación y limpieza se realicen preferentemente en local (CUDA fixed).
- [x] **4.2. Sound of Silence v2**: Asegurar que toda la comunicación entre agentes locales sea limpia, en Markdown y eficiente en tokens.

---

*Nota: "If it is not STOPPER don't STOP"*
