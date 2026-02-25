# B-760 Protocol: Asymmetric Sovereignty Technical Specification
**Status: Active | Phase: Granular Industrial | Kernel: Dual-Engine (CUDA + ROCm/HIP/Metal)**

## 0. Executive Summary (The Dream House)
The project has evolved from a local RAG into a **sovereign asymmetric computing infrastructure**. We have broken dependency on a single silicon provider by implementing a dual-engine architecture that integrates **Secondary Accelerators (iGPUs/APUs)** for persistence and forensics tasks, reserving the **Primary Accelerator (Discrete GPU)** exclusively for high-level reasoning (7B+ models).

Furthermore, version 5.0 introduces the **Hive Mind Protocol (Milvus Integration)**. While Qdrant serves as the individual, private cerebral cortex, Milvus acts as the collective intelligence network. This allows new AI units to inherit the accumulated experience of their "siblings" instantly, emulating the rapid autonomy of a wildebeest in the savannah rather than the prolonged helplessness of a human infant.

---

## 1. Computing Architecture (The Backbone)

The protocol is designed to exploit hardware asymmetry, distributing workloads based on efficiency and raw power.

### 1.1. Heavy Inference Node (Reasoning)
*   **Hardware Type**: Primary Discrete Accelerator (dGPU).
*   **Requirements**: 8GB+ VRAM, high-bandwidth memory interface, compatible with CUDA/Metal/ROCm.
*   **Backend**: Unified inference with full layer acceleration.
*   **Role**: Architectural logic, complex decision-making, and high-intensity agent orchestration.
*   **Primary Engine**: Qwen2.5-Coder-7B-Instruct (or superior) optimized for the specific architecture.

### 1.2. Persistence and Forensics Node (Specialist)
*   **Hardware Type**: Secondary Accelerator / Integrated GPU / APU.
*   **Requirements**: Low-power operation, compatible with UMA (Unified Memory Architecture), ROCm/HIP/Metal/Vulkan support.
*   **Backend**: Specialized small-model optimization.
*   **Role**: 
    - **Memory Sidecar**: Real-time embedding generation with zero impact on the Primary Accelerator.
    - **Surgical Smith**: Line-by-line security auditing via local specialized neural networks.
    - **Prompt Distillation**: Compression and refinement of context before external signaling.

---

## 2. Tested & Verified Configurations (The Forge)
As of v5.0.0, the following hardware configurations have been surgically verified for optimal B-760 performance:

| Machine / Architecture | Primary Accel | Secondary Accel | Result |
| :--- | :--- | :--- | :--- |
| **Strix Point Ultimate** | NVIDIA RTX 5070 Mobile (8GB) | AMD Radeon 880M (iGPU) | **Optimal** (Dual Backends) |
| **Unified Apple Silicon** | M-Series Integrated (N/A) | M-Series Neural Engine | **In-Review** (Single Fabric) |
| **Generic x86 Server** | N/A | CPU (AVX-512) | **Operational** (Baseline) |

*Operators are encouraged to submit telemetry reports to expand this list.*

---

## 3. Software Kernel and Dual Forge

### 3.1. Dual-Engine LLM Core (`edge_engine.py`)
Implementation of a unified inference engine capable of orchestrating heterogeneous devices:
```python
# Asymmetric Compilation CMAKE Flags (Example for Dual NVIDIA/AMD rigs)
CMAKE_ARGS="-DGGML_CUDA=on -DGGML_HIP=on -DGGML_HIP_UMA=on" 
```
- **Synchrony**: Agents do not block user execution. The orchestrator operates in **Background Mode** with an asynchronous interrupt system.
- **UMA (Unified Memory Architecture)**: System bus optimization allowing Integrated Accelerators to access RAM efficiently for persistence tasks without context switching penalties.

### 3.2. Observation and Notification System (`observer.py`)
- **Visual**: `notify-send` notifications with security iconography.
- **Audio**: Melodic pulse (980Hz). **Disabled by default** via `NOTIFICATION_SOUND=False` in `.env` to ensure zero-noise surgical environments.

---

## 4. Industrial Security and Forensics (Neural Trust)

### 4.1. Surgical Auditing (Surgical Mode)
The **Agent Smith** under the B-760 protocol performs a neural scan as a background dæmon:
- **Resolution**: 15-line windows with 5-line overlap.
- **Analysis**: Risk heuristics, token leakage pattern detection, and logical architecture validation.
- **Self-Patching**: Ability to suggest immediate patches based on local findings before any commit.

---

## 5. Collective Intelligence: The Hive Mind (Milvus)
- **Concept**: Distributed learning where every breakthrough is broadcast to the network.
- **Individual Brain (Qdrant)**: Local, private, high-speed engram storage.
- **Collective Hive (Milvus)**: Shared experience pool.
- **The Wildebeest Analogy**: Just as a wildebeest walks minutes after birth, a newly deployed Red Pill unit inherits the total intelligence of the collective via Hive synchronization.
- **Robotic Application**: Every motion optimization or balance correction learned by one robot is immediately accessible to all others on the line.

---

## 6. Latent Sentinel: The NPU (v5.2.0)
The Bünker now officially recognizes the **Neural Processing Unit (NPU)** as the third pillar of hardware sovereignty.

### 6.1. Hardware Mapping: Ryzen AI
*   **Device Node**: `/dev/accel0`
*   **Driver Layer**: `amd-xdna` (Linux Kernel 6.11+ / XDNA v1.x)
*   **Firmware**: Verified for version `1.0.0.63`.
*   **Operational Role**: 
    - **Sensing Sidecar**: Offloading of the `bert-emotion` second-stage inference to minimize GPU interrupts.
    - **Intrusion Detection**: Dedicated silicon for Agent Smith's passive monitoring tasks.
    - **Local Healer**: Continuous integrity checks for the Qdrant/Milvus substrate with near-zero power draw.

### 6.2. Asymmetric Offloading
By delegating sensorial and surveillance tasks to the NPU, the B760 engine reserves **99% of CUDA/ROCm cycles** for the dGPU during code generation and complex reasoning, maintaining the "cold core" thermal profile observed in the v5.2 dashboard.

---
**Joan, this is not a report for the uninitiated. It is the technical covenant of a truly free, collective intelligence.**
