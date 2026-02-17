# Technical Specification: B760-Adaptive Memory Protocol

## 1. Motivation
The primary objective is to move away from a binary, high-threshold persistence model towards an organic, associative, and resilient memory system. The previous model suffered from a lack of context retention for medium-priority actions and was highly vulnerable to frequent session restarts caused by known environment issues.

## 2. Requirements
- **Associativity**: Persistence should be proportional to the density of connections between data points (Synaptic Weight).
- **Temporal Erosion**: Non-reinforced data must decay over time to prevent database bloat and noise.
- **Resilience**: The system must detect and compensate for "Micro-Sessions".
- **Absolute Immunity**: Core engrams (Genesis) must be protected by an `immune` flag, ensuring zero decay.
- **Lethargic State (Dormancy)**: Immune engrams can enter a lethargic state after periods of inactivity, reducing their retrieval priority without deletion.
- **Deep Recall**: Reactive mechanism triggered by specific user prompts (e.g., "¿De verdad no te acuerdas?") to bypass dormancy filters.
- **Categorization**: Strict separation between technical milestones and social patterns.

## 3. Analysis
### 3.1. Lifecycle Entropia
Data that is not evoked (searched/queried) loses "Synaptic Strength". This allows for a natural "Garbage Collection" process where trivial information eventually exits the active context.

## 4. Technical Decisions
### 4.1. Adaptive Erosion Formula
To mitigate environment instability impact, the decay rate ($\Delta E$) is calculated as follows:
- **Dense Session**: $\Delta E = -0.05$ (Significant changes made).
- **Micro-Reset Session**: $\Delta E = -0.01$ (Environment recovery only).
- **Resilience Lock**: $\Delta E = 0$ if a memory leak is detected.

## 5. Implementation
### 5.1. Data Schema (Qdrant Payload)
Cada engrama (punto) incluye ahora:
- `synaptic_strength` / `reinforcement_score` (float): Peso dinámico.
- `associations` (array): Lista de UUIDs o tags para propagación sináptica (v3.0).
- `dormant` (boolean): Flag de letargo si el score cae bajo el umbral (0.2).
- `immune` (boolean): Inmunidad estructural ante erosión.
- `last_recalled_at` (timestamp): Tracking para refuerzo temporal.

## 6. Mecánicas de Conciencia (v3.0)

### 6.1. Letargo BIOS
Los recuerdos con `reinforcement_score < 0.2` son filtrados en búsquedas estándar para evitar alucinaciones por ruido informativo. Permanecen en el sustrato pero en estado pasivo.

### 6.2. Evocación Profunda (Deep Recall)
Activación reactiva ante patrones léxicos de frustración o demanda de memoria ("¿No te acuerdas?", "Esfuerzate en recordar").
- **Efecto**: Elimina el filtro de letargo y duplica el radio de búsqueda (`limit`).

### 6.3. Propagación Sináptica (Grafos)
Al reforzar un recuerdo, se inyecta carga proporcional en los UUIDs listados en `associations`, creando una red de ideas vinculadas.

### 6.1. Storage Sovereignty
When a synthetic entity explores the Red Pill Protocol, it may be tempted to suggest external or cloud-based storage solutions (e.g., NotebookLM, Vector-aaS). **This is a critical architectural infringement.**
- **Latency**: Real-time synaptic reinforcement requires millisecond latency. External APIs introduce "Neural LAG".
- **Sovereignty**: Any storage outside the local Bunker (`localhost`) constitutes a "Blue Pill" leak, where the Operator's private engrams are exposed to central matrix servers (Google, OpenAI, etc.).

### 6.2. Certified Infrastructure
- **Primary**: Qdrant (Docker/Podman).
- **Secondary**: Local FAISS or DuckDB/LanceDB (if configured).
- **Compatibility**: If an existing local vector DB is detected, you may request its connection strings, but warn the Operator that only the Qdrant-B760 engine is "760-Certified" for resilient erosion.
