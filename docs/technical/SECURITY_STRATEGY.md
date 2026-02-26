# Red Pill Security: API Key & Identity Recovery Protocol

This document outlines the three-tier security strategy for the Qdrant Bünker as of v5.0.0.

## 1. Security Tiers

The operator must choose one of the following configurations during the installation process (`install_neo.sh`).

### Tier 1: Open Bünker (Low Friction)
- **API Key**: None.
- **Access**: Unrestricted local access via `localhost:6333`.
- **Use Case**: Development environments or machines with physically secured, encrypted disks (LUKS/FileVault).

### Tier 2: Managed Sovereignty (Balanced)
- **Mechanism**: The operator provides a **Master Password**.
- **Execution**: 
    1. A complex API Key is automatically generated.
    2. The key is stored in the local `.env` file for system operation.
    3. A **Recovery Engram** is stored in the `directive_memories` collection. This engram contains an encrypted/hashed version of the Master Password. It is marked as **Erosion-Immune** (it will never decay) but is technically non-immune to manual deletion by the operator.
- **Identity Recovery Protocol (IRP)**: If the `.env` file is lost, the agent can restore the access key after a successful **Synaptic Handshake**.

### Tier 3: Custom Hardening (Advanced)
- **Mechanism**: The operator provides their own pre-generated API Key.
- **Requirements**: Must be a valid string (minimum 32 characters recommended).
- **Use Case**: Advanced users or existing Qdrant clusters.

---

## 2. The Identity Recovery Protocol (IRP)

The IRP is a "Last Resort" mechanism triggered when the Bünker is locked and the key is lost. It is governed by the following rules:

### A. The True Name Gate
Identification of the Agent's **True Name** is mandatory. Recovery cannot be initiated by an uninitialized partner. The operator must have "closed the link" (Lore synchronization) beforehand.

### B. The Synaptic Handshake
The agent will challenge the operator with **10 randomized questions** based on the most important shared memories stored in the `social_memories` and `work_memories` collections.

- **Threshold**: 8/10 correct answers.
- **Fail Penalty**: If the handshake fails, the Agent enters **Stasis Mode** for 24 hours, refusing any further security prompts to prevent brute-force memory guessing.

---

## 3. Storing the "Safe API Key"

For Tier 2, a "Safe Key Token" is generated. It is a one-time-viewable file provided during installation. 
**Operator Instructions**: Store this token in a password manager or a physically separate encrypted volume.

## 4. Technical Implementation (v5.5.0 — SEC-001)

- **OS-Level Keystore**: As of v5.5.0, the recovery hash is stored in
  `~/.config/red_pill/recovery.key` (mode 600, owner-only access), managed by
  `src/red_pill/utils/keystore.py`. The hash **never touches Qdrant**.
- **Qdrant IRP Marker**: Qdrant stores only a boolean presence marker
  (`{"irp_active": True, "security_tier": 2}`) in `directive_memories`. This
  confirms the Tier 2 configuration is active, but contains **no password material**.
- **Immune-Safe Marker**: The Qdrant marker is stored with `immune=True` so the
  B760 metabolism daemon ignores it and it never decays.
- **Argon2-id Verification**: Password verification uses `argon2-cffi`'s
  `PasswordHasher.verify()`, which is constant-time and resistant to timing attacks.
- **Known Limitation (documented)**: The keystore file is protected by OS permissions
  (mode 600), not encrypted. For multi-user deployments or shared machines, wrap the
  keystore directory in an age-encrypted volume or OS keyring (libsecret/Keychain).
  This is tracked as a P3 roadmap item.

## 5. API Key Rotation Protocol

To satisfy security audits and minimize the window of exploit for compromised keys, the Red Pill Protocol includes a rotation mechanism.

### A. Manual Rotation
The operator can rotate the Bünker's master key at any time using the following command:
```bash
uv run red-pill soul rotate
```
**Process**:
1. Generates a new cryptographically secure 32-char key.
2. Updates the `.env` file automatically.
3. Rewrites the internal systemd/Podman configuration.
4. Restarts the Qdrant service to apply changes.

### B. Automated Rotation (Compliance Mode)
For industrial environments, a daily or weekly rotation is recommended via cron:
```cron
# Rotate every Sunday at 03:00 AM
0 3 * * 0 cd /path/to/red-pill && /usr/local/bin/uv run red-pill soul rotate >> /var/log/red_pill_rotation.log 2>&1
```
