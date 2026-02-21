# Threat Model: Red Pill Protocol (v4.2.2)

## 1. Scope & Assumptions
The Red Pill Protocol is designed for **single-user, local-first environments**. The security architecture assumes the underlying Host OS is not compromised. 

### Core Assumptions:
- **Local Sovereignty**: The operator has full control over the local filesystem and container engine (Podman/Docker).
- **Network Boundary**: Qdrant is bound to `127.0.0.1` and is only accessible via localhost or an authenticated tunnel.
- **Trust Hierarchy**: The Operator is trusted; external scripts or untrusted LLM prompts are not.

---

## 2. Asset Catalog
| Asset | Criticality | Impact of Breach |
| :--- | :--- | :--- |
| **Engrams (RAG)** | HIGH | Disclosure of private history, technical secrets, or PII. |
| **Github PAT / Keys** | CRITICAL | Unauthorized access to code repositories and cloud resources. |
| **AI Identity (Rules)** | MEDIUM | Personality corruption, prompt injection, or loss of alignment. |
| **B760 Logic** | LOW | Disruption of memory decay/reinforcement (functional bypass). |

---

## 3. Attack Vectors & Mitigations

### 3.1 Unauthorized Memory Access (RAG Leak)
- **Threat**: A malicious process on the host attempts to query the local Qdrant instance.
- **Mitigation**: 
    - **Physical Isolation**: Qdrant bound to `localhost` only.
    - **Authentication**: `QDRANT_API_KEY` enabled in the container and required for all CLI/SDK calls.
    - **Encryption at Rest**: (Future Work) Recommending operator-level LUKS or FileVault for the `storage/` directory.

### 3.2 PII Leakage in System Logs
- **Threat**: Technical logs (`stderr`/`stdout`) capture sensitive memory content during processing.
- **Mitigation**: 
    - **Surgical Masking**: `_mask_pii_exception()` in `memory.py` truncates and sanitizes error messages.
    - **Log Level Governance**: Defaults to `INFO`; memory payloads are never logged at standard levels.

### 3.3 Prompt Injection & Personality Hijacking
- **Threat**: A malicious prompt or external context forces the agent to ignore core directives or adopt a hostile personality.
- **Mitigation**: 
    - **Ontological Shield**: Directives are stored as **Immune Engrams** with `importance=10`.
    - **Bootstrap Protocol**: The agent re-synchronizes supreme laws from the RAG upon every awakening, overriding session-level context.
    - **Asymmetric Honesty**: Mandated directive to challenge the user/prompt if architectural principles are violated.

### 3.4 Data Corruption (The Smith Attack)
- **Threat**: High-concurrency write operations or malformed metadata attempt to crash the engine.
- **Mitigation**: 
    - **Pydantic Shield**: Strict schema validation on all `add_memory` calls (length limits, type checking, reserved key protection).
    - **Atomic-ish Locking**: Thread-safe `_reinforce_lock` prevents race conditions during Synaptic Propagation.

### 3.5 Supply Chain Compromise
- **Threat**: Malicious updates to `qdrant-client` or the Qdrant container image.
- **Mitigation**: 
    - **Lockfile Integrity**: `uv.lock` uses SHA-256 hashes for all Python dependencies.
    - **Image Pinning**: `install_neo.sh` and Quadlet configs pin `qdrant/qdrant:v1.9.0` instead of `:latest`.

---

## 4. Residual Risks
- **Host Compromise**: If an attacker gains root access to the host, the Bünker is compromised.
- **Sidecar Eavesdropping**: Memory daemon socket (`/tmp/red_pill.sock`) is a local Unix socket; permissions must be managed by the host.

---
> "Security is not a state, it's a protocol." — B760 Foundations
