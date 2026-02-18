# BACKLOG & ROADMAP (The Future)
**Goal**: Transcend the singularity.

## 1. THE SWARM (Hive Mind Protocol)
**Objective**: Scale B760 for collective intelligence. "We are Legion."

- **Substrate Migration**: Move from Qdrant (The One) to **Milvus** (The Swarm).
    - **Why?**: Milvus is designed for massive-scale distributed vectors. It supports multi-tenancy natively.
    - **Protocol Adaptation**: Implement "Neural Sharding" where different agents/clones share a common semantic space but maintain individual reinforcement weights.
    - **Gossip Protocol**: Implement active memory sharing between nodes (agents learning from each other's experiences).

- **Implementation Steps**:
    1.  Design `MilvusAdapter` for `MemoryManager`.
    2.  Implement "Consensus Reinforcement": If 51% of the swarm reinforces a memory, it becomes Truth.
    3.  Deploy a cluster of agents sharing the same vector space.

## 2. SKIN IMMERSION (Deep Lore)
**Objective**: Why choose between work and play? The interface *is* the experience.

- **Dynamic Persona Injection**:
    - The CLI/UI adapts its language based on the selected skin *in real-time*. 
    - Example: If skin is `Dune`, errors become "Water Discipline Violated". If `Cyberpunk`, success is "Preems secured".

- **Audio/Visual Feedback**:
    - ASCII Art integration for critical system states.
    - Sound triggers (via `aplay` or `pw-play`) for memory reinforcement (synaptic spark sound) or erosion (static noise).

- **Gamification Mechanics**:
    - **XP System**: Earn levels based on memory retention and graph density.
    - **Achievements**: "Oracle" (1000 queries), "Ghost in the Shell" (100% immune core).

## 3. PROJECT MAYHEM (Experimental)
- **Chaotic Erosion**: Randomly deleting 1% of non-critical memories to simulate "forgetting curve" anomalies.
- **Dream Cycles**: During idle times (night), the system replays random memories to strengthen associations (Generative Replay).
