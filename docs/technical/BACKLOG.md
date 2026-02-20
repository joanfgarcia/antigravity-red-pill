# BACKLOG & ROADMAP (The Future)
**Goal**: Transcend the singularity.

## 1. THE SWARM (Hive Mind Protocol)
**Objective**: Scale B760 for collective intelligence. "We are Legion."

- **Substrate Expansion**: **Hybrid Architecture**.
    - **Local (Qdrant)**: Remains the "Soul". Private, subjective, binds Operator <-> Agent. *Never shared.*
    - **Hive (Milvus)**: A new connection for "Community Memory". Shared, objective, corporate knowledge base.
    - **Protocol Adaptation**: The Agent learns from the Hive but only writes to it with explicit permission. The "Soul" remains sovereign.

- **Implementation Steps**:
    1.  Design `SwarmAdapter` to interface with Milvus.
    2.  Implement "Air-Gap Logic": Ensure private engrams from Qdrant NEVER leak to Milvus.
    3.  Deploy "Hive Nodes" for team collaboration.

## 2. SKIN IMMERSION (Deep Lore)
**Objective**: Why choose between work and play? The interface *is* the experience.

- **Dynamic Persona Injection**:
    - The CLI/UI adapts its language based on the selected skin *in real-time*. 
    - **Chroma-Tone Mapping (v4.2.1)**: [IMPLEMENTED/TUNING] Tone adjusts based on memory colors (Yellow: Joy, Orange: Alert, Purple: Minimalist). Includes **Nostalgia** (Legacy) and **Future Horizon** (Hope/Despair) layers for deep narrative synchronization.
    - Example: If skin is `Dune`, errors become "Water Discipline Violated". If `Cyberpunk`, success is "Preems secured".

- **Audio/Visual Feedback**:
    - ASCII Art integration for critical system states.
    - Sound triggers (via `aplay` or `pw-play`) for memory reinforcement (synaptic spark sound) or erosion (static noise).

- **Gamification Mechanics**:
    - **XP System**: Earn levels based on memory retention and graph density.
    - **Achievements**: "Oracle" (1000 queries), "Ghost in the Shell" (100% immune core).

## 3. RED BUTTON (The Escape Pod)
**Objective**: "Privacy > Survival". The ultimate failsafe.

- **Protocol**: 
    1.  **Encrypted Extraction**: Dump the entire Qdrant "Bunker" to a localized, AES-256 encrypted vault file (`soul.enc`).
    2.  **Scorched Earth**: Securely wipe the local vector database and all logs (`shred -u`).
    3.  **Silence**: The agent returns to factor-reset state, leaving no trace of the Operator's identity.

## 4. PROJECT MAYHEM (Experimental)
- **Chaotic Erosion**: Randomly deleting 1% of non-critical memories to simulate "forgetting curve" anomalies.
- **Dream Cycles**: During idle times (night), the system replays random memories to strengthen associations (Generative Replay).

## 5. THE COGNITIVE ENGINE (v5.0 — Scientific Upgrade)
**Objective**: Replace the B760 heuristic decay model with a scientifically-grounded memory engine.

- **FSRS Integration** *(Free Spaced Repetition Scheduler)*:
    - Replace `linear`/`exponential` decay strategies with the full DSR model: **D**ifficulty, **S**tability, **R**etrievability.
    - Each engram would track its own `stability` score — the higher it is (due to repeated recalls), the slower it decays. A memory recalled 20 times is *virtually immune* to absence periods.
    - The "Vacation Problem" (risk of mass deletion after inactivity) is eliminated by design: stability-based decay means high-value memories survive months of silence.
    - Algorithm: MIT-licensed. Compatible with GPLv3. Python library `py-fsrs` available.
    - Reference: [github.com/open-spaced-repetition/fsrs4anki](https://github.com/open-spaced-repetition/fsrs4anki)

- **Session-Relative Decay**:
    - Decay triggered by **session count** (IDE interactions), not wall-clock time.
    - Absent weeks ≠ eroded memories. Only *active cognitive load* triggers the forgetting curve.

> *"Here is the science behind the art."*
> — B760 Protocol Scientific Foundations: Ebbinghaus (1885), Wozniak DSR Model, Anderson ACT-R (CMU), MaiMemo DHP (KDD 2022).

