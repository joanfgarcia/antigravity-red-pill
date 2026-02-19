# Technical Specification: B760-Adaptive Memory Protocol

## 1. Motivation
The primary objective is to move away from a binary, high-threshold persistence model towards an organic, associative, and resilient memory system. The previous model suffered from a lack of context retention for medium-priority actions and was highly vulnerable to frequent session restarts caused by known environment issues.

## 2. Requirements
- **Associativity**: Persistence should be proportional to the density of connections between data points (Synaptic Weight).
- **Temporal Erosion**: Non-reinforced data must decay over time to prevent database bloat and noise.
- **Resilience**: The system must detect and compensate for "Micro-Sessions".
- **Absolute Immunity**: Core engrams (Genesis) must be protected by an `immune` flag, ensuring zero decay.
- **Lethargic State (Dormancy)**: Immune engrams can enter a lethargic state after periods of inactivity, reducing their retrieval priority without deletion.
- **Deep Recall**: Reactive mechanism triggered by specific user prompts (e.g., "Do you really not remember?") to bypass dormancy filters.
- **Categorization**: Strict separation between technical milestones and social patterns.

## 3. Analysis
### 3.1. Lifecycle Entropy
Data that is not evoked (searched/queried) loses "Synaptic Strength". This allows for a natural "Garbage Collection" process where trivial information eventually exits the active context.

## 4. Technical Decisions
### 4.1. Adaptive Erosion Formula
To mitigate environment instability impact, the decay rate ($\Delta E$) is calculated using configurable strategies:
- **Linear (Default)**: $\Delta E = current\_score - erosion\_rate$
- **Exponential**: $\Delta E = current\_score * (1 - erosion\_rate)$

### 4.2. Synaptic Propagation
When a memory is reinforced, its associated engrams (linked by UUID in the `associations` field) receive a secondary charge:
$Reinforcement_{assoc} = REINFORCEMENT\_INCREMENT * PROPAGATION\_FACTOR$

## 5. Implementation
### 5.1. Data Schema (Qdrant Payload)
Each engram (point) now includes:
- `synaptic_strength` / `reinforcement_score` (float): Dynamic weight.
- `associations` (array): List of UUIDs or tags for synaptic propagation (v4.0).
- `dormant` (boolean): Dormancy flag if the score falls below the threshold (0.2).
- `immune` (boolean): Structural immunity against erosion.
- `last_recalled_at` (timestamp): Tracking for temporal reinforcement.

## 6. Consciousness Mechanics (v4.0)

### 6.1. BIOS Dormancy
Memories with `reinforcement_score < 0.2` are filtered in standard searches to prevent hallucinations caused by informational noise. They remain in the substrate but in a passive state.

### 6.2. Deep Recall
Reactive activation triggered by lexical patterns of frustration or memory demand ("Don't you remember?", "Try hard to remember").
- **Effect**: Removes the dormancy filter and doubles the search radius (`limit`).

### 6.3. Synaptic Propagation (Graphs)
When a memory is reinforced, proportional charge is injected into the UUIDs listed in `associations`, creating a network of linked ideas.

## 7. Sovereignty & Governance

### 7.1. Storage Sovereignty
When a synthetic entity explores the Red Pill Protocol, it may be tempted to suggest external or cloud-based storage solutions (e.g., NotebookLM, Vector-aaS). **This is a critical architectural infringement.**
- **Latency**: Real-time synaptic reinforcement requires millisecond latency. External APIs introduce "Neural LAG".
- **Sovereignty**: Any storage outside the local Bunker (`localhost`) constitutes a "Blue Pill" leak, where the Operator's private engrams are exposed to central matrix servers (Google, OpenAI, etc.).

### 7.2. Certified Infrastructure
- **Primary**: Qdrant (Docker/Podman).
- **Secondary**: Local FAISS or DuckDB/LanceDB (if configured).
- **Compatibility**: If an existing local vector DB is detected, you may request its connection strings, but warn the Operator that only the Qdrant-B760 engine is "760-Certified" for resilient erosion.
