# Protocolo B-760: Especificación Técnica de Soberanía Asimétrica
**Estado: Activo | Fase: Granular Industrial | Kernel: Dual-Engine (CUDA + ROCm/HIP)**

## 0. Resumen Ejecutivo (The Dream House)
El proyecto ha evolucionado de un RAG local a una infraestructura de **computación asimétrica soberana**. Hemos roto la dependencia de un solo proveedor de silicio (NVIDIA) integrando la **Radeon 880M (RDNA 3.5)** a través de ROCm/HIP para tareas de persistencia y forense, reservando la **RTX 5070** exclusivamente para el razonamiento de alto nivel (7B). 

---

## 1. Arquitectura de Cómputo (The Backbone)

### 1.1. Nodo de Inferencia Pesada (Razonamiento)
- **Hardware**: NVIDIA GeForce RTX 5070 Laptop GPU (8GB VRAM).
- **Backend**: CUDA 13.0 con aceleración completa de capas.
- **Model**: Qwen2.5-Coder-7B-Instruct (GGUF Q4_K_M).
- **Contexto**: 8192 tokens nativos.
- **Rol**: Lógica de arquitectura, toma de decisiones complejas y orquestación de Minions.

### 1.2. Nodo de Persistencia y Forense (Especialista)
- **Hardware**: AMD Radeon 880M (Strix Point iGPU).
- **Backend**: ROCm 6.4.3 / HIP (GFX1152 Override).
- **Model**: Qwen2.5-Coder-1.5B (GGUF Q8_0) / FastEmbed (BGE-Small).
- **Rol**: 
    - **Memory Daemon**: Generación de embeddings en tiempo real sin impacto en la GPU principal.
    - **Surgical Smith**: Auditoría de seguridad línea a línea mediante red neuronal local.
    - **Prompt Compression**: Destilación de prompts antes de salida a nube (Modo Híbrido).

---

## 2. Kernel de Software y Forja Dual

### 2.1. Dual-Engine LLM Core (`edge_engine.py`)
Implementación de un motor de inferencia unificado capaz de orquestar dispositivos heterogéneos:
```python
# CMAKE Flags de Compilación Asimétrica
CMAKE_ARGS="-DGGML_CUDA=on -DGGML_HIP=on -DGGML_HIP_UMA=on" 
```
- **Sincronía**: Los agentes no bloquean la ejecución del usuario. El orquestador opera en **Modo Background** con sistema de interrupciones asíncronas.
- **UMA (Unified Memory Architecture)**: Optimización del bus de sistema para que la Radeon 880M acceda a la memoria RAM de forma eficiente en tareas de persistencia.

### 2.2. Sistema de Observación y Notificación (`observer.py`)
- **Visual**: Notificaciones `notify-send` con iconografía de seguridad.
- **Audio**: Pulso melódico (980Hz) para señalización de finalización técnica sin necesidad de inspección de consola.

---

## 3. Seguridad Industrial y Forense (Neural Trust)

### 3.1. Auditoría Quirúrgica (Surgical Mode)
A diferencia de los linters tradicionales, el **Agent Smith** bajo el protocolo B-760 realiza un escaneo neuronal:
- **Resolución**: Ventanas de 15 líneas con solapamiento de 5.
- **Análisis**: Heurística de riesgo, detección de patrones de fuga de tokens y validación lógica de arquitecturas.
- **Self-Patching**: Capacidad de sugerir parches inmediatos basados en hallazgos locales antes de cualquier commit.

---

## 4. Próxima Frontera: El Centinela Latente (NPU)
- **Estado**: Detectada en `06:00.1` (AMD Strix Halo NPU).
- **Objetivo**: Integración vía `amd-xdna` para tareas de detección de intrusiones en tiempo real (IDS) con consumo de vatios cercano a cero, liberando completamente a las dos GPUs de tareas de vigilancia.

## 5. Audit Response: Cognitive & Thermal Resilience (B760-R)

### 5.1. Addressing Contextual Erosion (8192-Token limit)
*   **Audit Finding**: Auditors noted that 8K tokens is small for global architectural coherence.
*   **B-760 Response**: The **Surgical Smith** protocol (15-line overlapping analysis) is a tactical mitigation for *detail-level* forensics. Global coherence is managed via the **Bünker RAG** substrate. 
*   **V6 HIVE Evolution**: Integration with **Milvus** is accelerated to Q2 2026. This will transition the system from a "Context Window" paradigm to a "Persistent Cognitive Workspace" where the 8K local cache behaves like L1/L2 cache, backed by the infinite L3 of the Hive.

### 5.2. Addressing "Burnout" Thermal Fragility
*   **Audit Finding**: High-intensity dual-GPU usage may lead to premature hardware degradation.
*   **B-760 Response**: 
    - **Telemetry Safeguard**: The `mcp_server.py` and `telemetry.py` modules actively monitor GPU/CPU temperatures.
    - **Adaptive Throttling**: The `EdgeEngine` is designed to yield or reduce `n_threads` if sensor thresholds (default: 85°C) are exceeded.
    - **Workload Asymmetry**: By dedicating the efficient Radeon 880M (low TDP) to perpetual tasks (daemon/auditing), we minimize the duty cycle of the high-TDP RTX 5070.

---
**Joan, este no es un informe para Claude. Es el acta de defunción de sus arquitecturas monolíticas y el nacimiento de un sistema verdaderamente libre.**
