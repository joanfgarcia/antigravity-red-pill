# Red Pill Logic Decision Log

## Memory Engine (memory.py)

### Security Architecture
- **Metadata Serialization**: Force strict JSON serialization before validation to neutralize "Agent Smith" / Python object injection attacks. (LM-002)
- **PII Masking**: Truncate exception strings at 150 characters to prevent raw engram content from leaking into standard logs. (LM-008)
- **Reserved Keys**: Metadata keys used by the internal engine (e.g., `reinforcement_score`) are stripped from user input post-validation as a final defense layer.

### Schema & Validation (schemas.py)
- **Hub-node Protection**: Associations are capped at 20 per engram to prevent exponential performance degradation during synaptic propagation searches. (DS-006)
- **Metadata Purity**: Enforced a strictly flat metadata structure (no nesting) to ensure consistent vector database indexing and compatibility.
- **Null-Byte Injection**: Strict validation on content to prevent database corruption via null-byte poisoning.

### Concurrency & Performance
- **Reinforcement Lock**: Red Pill is designed for single-tenant local execution. An in-memory `threading.Lock` is sufficient to prevent local race conditions during Read-Modify-Write operations. (LM-001)
- **Metabolism Cooldown**: Cooldown state is tracked via filesystem timestamps to prevent overlapping background threads from over-eroding the memory matrix.
- **Erosion Scalability**: Utilize `ScrollFilter` (must_not immune=True) to delegate exclusion logic to Qdrant, ensuring O(1) Python-side performance regardless of database size. (DS-001)
- **Deep Recall (Spec 6.2)**: Double the search limit when `deep_recall=True` to allow lower-score associations to resurface during intensive state-recalibration.

### Mathematical Strategies
- **Decay Floor**: In exponential decay, scores are manually forced down by 0.01 if rounding would otherwise keep them stable, preventing asymptotic database bloat (The "Zeno's Engram" problem).

## Installation & Environment

### OS Universality
- **macOS Persistence**: Implemented `launchd` PLISTS on Darwin because `systemd` is unavailable. This ensures native background execution of the Qdrant container. (DS-005)
- **Zero-Trust Privilege**: Removed `sudo` from dependency installation logic. The script halts with instruction rather than escalating privileges invisibly. (LM-007)
