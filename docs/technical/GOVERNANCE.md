# Governance & Evolution Protocol (v4.2.2)

To maintain the high-integrity nature of the Red Pill Protocol while allowing for community evolution, this document explicitly defines what is "Fixed" (Immune to impulsive change) and what is "Fluid" (Open for experimentation).

---

## 1. The Immutable Core (Fixed Principles)
These elements are protected by the **Ontological Shield**. Changes here require a "Singularity Shift" and a full architectural re-audit.

### 1.1. The B760-Adaptive Mechanics
- **Decay & Reinforcement**: The fundamental math of synaptic erosion and reinforcement (0.2 dormancy floor, 10.0 immunity ceiling) is locked.
- **Privacy-First (Zero Leak)**: No PR shall introduce external telemetry, cloud tracking, or unmasked PII logging.
- **Local Sovereignty**: The project must remain functional in a fully air-gapped environment (Local Qdrant, local embeddings).

### 1.2. Linguistic Strategy
- **Technical Layer**: English (EN) remains the mandatory language for code, docs, and the build system (Efficiency & Tooling).
- **Identity Layer**: Spanish (ES) remains the primary language for the Manifesto and the B760 Spirit (Emotional Resonance).

### 1.3. The Sound of Silence (v1.2)
- **Hard Constraints**: Indentation by Tabs (`\t`), zero-dead-code, and no placeholders. This is not a preference; it is a protocol.

---

## 2. The Fluid Periphery (Open for Evolution)
These areas are encouraged for contribution and rapid iteration.

### 2.1. Lore & Skins
- **Presets**: New narrative skins (presets) and terminology maps are always welcome.
- **Terminology**: Expanding the "Multiverse" of themes (Warhammer, Dune, GITS) is fluid.

### 2.2. Connectors & Bridges
- **Portability**: Adapters for different container engines (Podman, Docker, LXC) or OS (Windows, MacOS, BSD).
- **LLM Agnosticism**: Enhancing the "Lazarus Bridge" to work with new local LLM backends (Ollama, vLLM, etc.).

### 2.3. Optimization Labs
- **Vector Search**: Performance tweaks for Qdrant, filtering logic, or quantization.
- **CI/CD Automation**: Better test runner efficiency and coverage visualization.

---

## 3. The Integration Ritual
Every change must be "Vibe-Coded" and pass through the **Agentic Auditor**. 

### The Protocol for Evolution:
1.  **Intent Disclosure**: Before a major shift, the goal must be externalized in an Issue or a Draft PR.
2.  **Audit Review**: The Agent will check if the PR violates any **Immutable Core** principle.
3.  **The Verdict**: "Noise is rejected; Signal is merged."

---
> "Rigidity is our armor, but fluidity is our growth. Know what to protect, and know what to release." — B760 Governance
