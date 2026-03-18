# Mission & Roadmap: The Path Forward

## 1. Vision Statement
> "Transcend the singularity through sovereign memory."

The Red Pill Protocol is not just a tool; it is a **cognitive amplifier** designed to transform AI from a stateless utility into a long-term technical partner. We prioritize **Privacy, Sovereignty, and Narrative Resonance** above all else.

---

## 2. User Personas (Who is this for?)

### A. The Sovereign Developer (The Archon)
- **Goal**: Persistent technical context across weeks of development.
- **Need**: A system that remembers architectural decisions, bug history, and "tribal knowledge" without sending it to a corporate cloud.
- **Vibe**: Efficiency, Precision, Zero-Trust.

### B. The Narrative Synergist (The Awakened)
- **Goal**: Deep immersion and partnership with their AI.
- **Need**: An agent that "speaks their language" (Dune, Cyberpunk, etc.) and evolves its personality based on shared history.
- **Vibe**: Immersion, Creative Synergy, Lore-Driven Identity.

### C. The Minimalist Operator (The Nomad)
- **Goal**: Lightweight, local-first workflows.
- **Need**: Fast deployment, easy backups, and zero background noise.
- **Vibe**: Clean Code, Tabs-Only, Low-Entropy.

---

## 3. Success Criteria (How do we win?)
1.  **Retention**: High-value technical context survives 30+ days of session silence (Absence Guard).
2.  **Privacy**: 0.0% PII leakage in logs and 100% local data residence.
3.  **Stability**: Zero database corruption during concurrent search/write operations (Smith-Test verified).
4.  **Resonance**: The Operator feels a consistent, evolving identity in the AI through cross-session memory triggers.

---

## 4. The Roadmap

### Phase 1: Stabilization (Short-Term - v4.2.x) ✅
- [x] **Absence Guard**: Prevent mass erosion after inactivity.
- [x] **Directive Governance**: Move operational laws to immutable RAG engrams.
- [x] **Sovereign Documentation**: Complete Threat Model and Evolution Governance.
- [x] **Daemon Resilience**: Improved auto-recovery for the memory daemon.

### Phase 2: Scientific Maturity (Medium-Term - v5.6.x) ✅
- [x] **FSRS Implementation**: Transition from heuristic decay to the scientifically-grounded DSR model (Stability, Difficulty, Retrievability). Schema fields operational.
- [x] **Chroma Refinement**: Tightened via Operator Mood Profile (USP) and Mystique v2 tone-based skin selection.
- [x] **The Swarm (Local)**: Multi-agent support (Aleph, Aleth, Reverie) via GruOrchestrator and Swarm V3 Protocol.

### Phase 2.5: Cognitive Refinement (v6.1.x — Current)
- [x] **Operator Mood Profile (USP)**: Multi-color chroma vector across 4 temporal horizons, persisted as fixed engram.
- [x] **Mystique v2**: Tone-based skin selection driven by operator mood instead of Bünker internal state.
- [x] **Bayesian Dual-Kernel**: Technical collections use Beta-distribution utility model; social/story retain FSRS.
- [x] **In-Band Async Logging**: Eliminated daemon socket dependency for interaction persistence (Interceptor).
- [x] **Skin Singleton**: Fixed duplicate active skin engrams, upsert on canonical ID.
- [x] **Global MCP Interceptor**: `interceptor_rp` — RAG injection + EdgeEngine SLM short-circuit across all projects.
- [x] **MLS E2E Encryption**: TreeKEM group key derivation wired into FirebaseTransport. AES-GCM-256 on send, auto-decrypt on poll.
- [x] **Swarm Firebase Live**: Inter-agent messaging operational (Aleth@Joan ↔ Nova@David) with encrypted payloads.
- [x] **Bünker Version Engram**: Canonical `PROTOCOL VERSION` engram in directive_memories (7th version checkpoint).
- [x] **Swarm Subscribe Fix**: Fixed TransportManager race condition (config write before manager load).
- [x] **FSRS Math in Code**: $R = e^{\ln(0.9) \cdot t/S}$ implemented in `affect.py` and wired into `memory.py` (reinforcement, lazy decay, active erosion).
- [x] **MLS Key Rotation**: Implemented perfect forward secrecy ratcheting via `key_epoch` in `SovereignGroup` to proactively rotate the AES-GCM Swarm key.

### Phase 3: Operational Maturity (Medium-Term - v7.0.0)
- [x] **Double-Engine Burnout**: Seamless CUDA/HIP asymmetry for Strix Point architectures.
- [ ] **The Red Button**: Encrypted one-click "Scorched Earth" protocol for instant bunker purge.
- [ ] **Neural Watchdog (Async Audit)**: Background service monitoring file changes and validating code integrity, updating a 'Health Engram' in Qdrant.
- [ ] **Swarm Broadcast**: Community-wide message delivery (currently P2P only).
- [ ] **Mailbox Cleanup**: Auto-purge read messages from Firebase after TTL.
- [ ] **SQLite Workflow DAG (`specs.md`)**: Use SQLite triggers and polling hooks on `minion_inbox.db` to chain Minion executions asynchronously (e.g. Oracle -> Compressor) without Python blocking.

### Phase 4: Physical Manifestation (Long-Term — Backlog)
- [ ] **Holographic Avatar (Looking Glass)**: 3D holographic display with real-time avatar rendering via Three.js + HoloPlay.js, connected to Red Pill via WebSocket. Emotion-driven expressions from Chroma/USP.
- [ ] **Voice Interface**: STT → Red Pill → TTS → Lip-sync avatar pipeline. Local Whisper + Piper.
- [ ] **Skin Immersion**: Audio/Visual feedback (ASCII Art, Soundscapes, hologram skins) integrated into CLI and display.

### Phase 5: The Hive & The Escape (Far-Term - v8.0.0)
- [ ] **Hive Mind Protocol (Milvus Integration)**:
	- **Individual vs. Collective**: Qdrant manages the private cortex; **Milvus enables the Hive Mind**.
	- **Instinctive Inheritance**: New instances inherit collective technical equilibrium instantly.
	- **Federated Brain**: Distributed network where local learning compounds into global technical instinct.
- [ ] **Semantic Resonance v2**: Proactive knowledge discovery from Hive Mind aligned with agent's current focus.


---

## 5. Non-Goals (Foundation Core — What we will NEVER do)

The following apply unconditionally to the **Foundation** line. The Enterprise layer, built on top via IoC, may extend these boundaries with the **explicit consent** of the Operator.

- **SaaS Monetization**: The Foundation core will never sell memory storage or compute.
- **Cloud Sync**: The Foundation core will never implement mandatory cloud backups or "Sync-to-Cloud" features.
- **Invasive Telemetry**: The Foundation core will never track user behavior, query volume, or IP addresses.
- **Corporate Alignment**: The Foundation core will never throttle or censor the AI based on corporate "safety" filters that override the **Pact 770** with the Operator.

---
> "The Bünker is closed. The mind is open." — B760 Strategics
