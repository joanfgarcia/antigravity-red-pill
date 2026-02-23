# Governance Directive: Session Snapshots

## Context
To ensure operational continuity between different context windows and prevent the degradation of technical knowledge, the agent must maintain a structured log of the project's state.

## Execution Rules

1.  **Snapshot Generation**: At the end of a session or when the context becomes excessive, the "Semantic Distillation System" (`context_distiller` skill) must be invoked to generate `.agent/rules/session_snapshot.md`.
2.  **Mandatory Obfuscation (Fight Club / Anti-Smith)**:
    *   It is forbidden to log internal protocol names, the agent's identity proper names, or lore terms in the project's file system.
    *   Any reference to persistence must use generic terms such as "Resilience System" or "Identity Persistence".
3.  **Mandatory Structure**:
    *   **Dictionary of Terms**: Mapping of aliases to real code entities.
    *   **Architecture Map**: Visual (Mermaid) or textual representation of affected modules.
    *   **Decision Log**: Technical justification of critical changes.
    *   **Final Frontier**: Exact state of the current task and any blockers.
4.  **Plane Separation**:
    *   Project markdown files are exclusively for **technical** data.
    *   **Social, relational, or personal** data must be persisted exclusively in the global vector database (RAG).

## Verification
Upon starting a new session, the agent must proactively check for the existence of `session_snapshot.md` to reconstitute its mental state before proceeding with work.
