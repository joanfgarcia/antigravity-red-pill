# Known Security Exceptions (WONTFIX)

The **Red Pill Protocol** embraces a Sovereign/Nomad threat model. This means that we explicitly delineate between the Protocol's responsibilities and the Operator's OS-level responsibilities. The following security traits have been audited, acknowledged, and formally tagged as `WONTFIX`.

## SEC-W01: Qdrant Memory Cleartext Storage
- **Description**: All vector memories (engrams) and their payloads are stored in plaintext within the Qdrant database files on disk. The Red Pill Protocol does not encrypt individual database records.
- **Risk Level**: High (if physical access is compromised).
- **Threat Model Scope**: The threat model explicitly targets unauthorized *network* exfiltration or application-level agent attacks. It assumes the host operating system is secure.
- **Accepted Rationale**: Encrypting vector embeddings and filtering properties on-the-fly destroys the O(1) retrieval performance required for real-time Agentic loops.
- **Operator Requirement**: Operators **MUST** utilize OS-level full disk encryption (LUKS on Linux, FileVault on macOS, BitLocker on Windows) to protect data at rest.

## SEC-W02: Localhost Daemon Authentication
- **Description**: Local API services (such as the LM Studio, llama.cpp, or MLX inference daemons) running on `localhost` without API keys or JWT tokens.
- **Risk Level**: Low.
- **Threat Model Scope**: Single-user workstation environment.
- **Accepted Rationale**: Since the services are bound exclusively to `127.0.0.1`, they are unreachable from the external network. Adding token authentication layer to local IPC overhead slows down synaptic loops unnecessarily.

## SEC-W03: Symmetric GPG Encryption (Nomad Backup)
- **Description**: The Cloud Vault uses symmetric AES-256 via GPG passphrases rather than asymmetric public-key recipient encryption.
- **Risk Level**: Medium (If the passphrase entropy is low).
- **Threat Model Scope**: Personal backup (Nomad model).
- **Accepted Rationale**: Symmetric passphrase encryption allows an operator to restore their Bünker on any new machine instantly, without needing to transport or recover a private GPG master key pair first. It optimizes for disaster recovery friction. (Hardened with `--s2k-digest-algo SHA512` in v6.1).
