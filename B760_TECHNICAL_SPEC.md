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
Each engram (point) includes:
- `synaptic_strength` (float): Current weight.
- `associations` (array): List of related event IDs or tags.
- `sensory_weight` (string): Impact level (low, medium, high, critical).
- `last_access` (timestamp): Tracking for reinforcement.
