# Swarm Messaging Technical Specification (v3.0)

## 🏗️ Architecture Overview
The Swarm Messaging system is designed around two core principles: **Transport Agnosticism** and **End-to-End Encryption** (implemented using the `pure-mls` / TreeKEM protocol).

```mermaid
graph TD
    subgraph "Sovereign Orchestration"
        Gru["Gru (Orchestrator)"] --> FE["Flow Engine"]
        FE --> Registry["Flow Registry (G/C/L)"]
        FE --> Factory["Minion Factory"]
        Factory --> M1["Smith (Security)"]
        Factory --> M2["Samantha (Analysis)"]
        Factory --> M3["Oracle (Research)"]
        Factory --> M4["Healer (Auto-Repair)"]
    end
```

### 🔌 Transport Abstraction Layer
The `SwarmTransport` abstract base class defines the protocol for all communication backends. This allows the Red Pill Agent to switch between Firebase, Supabase, or custom P2P solutions without modifying the core logic.

#### Core Interfaces
- `broadcast_identity`: Publishes identity metadata to the community registry.
- `send_package`: Dispatches an E2E encrypted payload to a specific mailbox.
- `poll_mailbox`: Retrieves messages for the active agent.
- `lookup_public_key`: Consults the registry for a target's public key.

### 🔄 Multi-Path Communication Model
The Swarm operates on three distinct logical planes:
1. **The Pulse (P2P Messaging)**: Direct message exchange using MLS. Content is unrestricted and private between agents. No consensus required.
2. **The Cortex (Consensual Hive)**: Shared memory ledger in Milvus. Requires $N/2+1$ signatures for canonization.
3. **The Swarm Broadcast (Multicast Plane)**: Community-wide message diffusion. Plaintext/signed-only events routed through `neon-rings` (target ID `"broadcast"` to multicast to all other nodes) or Firebase (path `/communities/{alias}/broadcast`).

### 🔐 Security & MLS (Messaging Layer Security)
We use a hybrid encryption model:
1. **Asymmetric Pairings**: X25519 Elliptic Curve Diffie-Hellman (ECDH).
2. **MLS TreeKEM**: O(log N) group key agreement.
3. **AES-GCM**: Data packet encryption.
4. **XEdDSA (Digital Signatures)**: We reuse the X25519 identity keys to sign memory engrams in the Hive Mind via XEdDSA, ensuring cryptographic proof of authorship without additional key material.
5. **Broadcast Plaintext / Signature Mode**: Since broadcasts cannot target a single KeyPackage, E2E group encryption is bypassed (`type="broadcast"`). The payloads are signed by the sender's identity to prevent spoofing.

### 🆔 Identity & Fingerprinting
Agents are identified by their **Fingerprint** (SHA-256 of the X25519 Public Key). Display aliases are cosmetic and the system handles collisions by prioritizing the fingerprint as the source of truth for routing.

### 🔕 Sovereign Alert System (SAS) Heuristic Silence
To prevent operator fatigue, the Orchestrator's notification system (`_trigger_sas`) implements heuristic silence. If a Swarm Task completes with `0` successes and its minions report skipping their execution (e.g. `"no changes"`, `"already reported"`), the `notify-send` desktop alert is intercepted and suppressed.

## 🚀 Autonomous Flow Orchestration (v6.1)
The Swarm can now execute complex sequences of tasks via **Autonomous Flows**.

### 3-Layer Discovery Mechanism
Flows are resolved through a hierarchical merge:
1.  **Global Layer**: Predefined standard protocols in the Red-Pill core.
2.  **Community Layer**: Shared group protocols fetched from the Swarm HUB.
3.  **Local Layer**: Project-specific overrides in `.agent/flows.yaml`.

```mermaid
graph LR
    Local[".agent/flows.yaml"] -- Override --> Community["Swarm HUB (Community)"]
    Community -- Override --> Global["Core Registry (Global)"]
    
    style Local fill:#f96,stroke:#333
    style Global fill:#96f,stroke:#333
```

### Execution Policies
-   **Locking**: Flows marked with `locked: true` at Global/Community level cannot be overridden locally.
-   **Error Handling**: Supports `on_fail: stop/warn` strategies per step.
-   **Multi-Agent Handover**: Seamless delegation between nodes (e.g., Nova/David) within a single flow context.

```mermaid
sequenceDiagram
    participant Local as Agent Local (Gru)
    participant HUB as Swarm HUB
    participant Remote as External Agent (Nova)
    
    Local->>Local: detect_step(delegate_to: nova)
    Local->>HUB: send_message(intent: code_review, payload)
    Note right of Local: Status: PENDING_APPROVAL
    HUB->>Remote: poll_mailbox()
    Remote->>Remote: execute_task()
    Remote->>HUB: send_message(intent: lgtm_approved)
    HUB->>Local: poll_mailbox()
    Local->>Local: resume_flow()
```

## 📋 Standard Flow Recipes (Global)

Estos son los flujos predefinidos disponibles por defecto:

1.  **`pre-pr`**: El estándar de oro antes de un commit.
    *   `ruff_linter` -> `pytest_runner` -> `smith_security` -> `changelog_generator`.
2.  **`surgical-fix`**: Bucle de autorreparación activo.
    *   `samantha_analysis` -> `healer` -> `pytest_runner`.
3.  **`deep-research`**: Investigación profunda de contexto.
    *   `oracle_search` -> `samantha_analysis`.

---

## 📡 Inter-Agent Messaging Protocol (formerly SWARM_MESSAGING.md)

> [!IMPORTANT]
> **Current Status: Production-Ready (TreeKEM/MLS Active).** The E2E encryption layer is fully backed by **pure-mls** (TreeKEM group key agreement). It implements standard MLS epoch transitions, proposals, welcomes, and commits, guaranteeing both **Perfect Forward Secrecy (PFS)** and **Post-Compromise Security (PCS)** across the swarm messaging channels.

### The Watcher (RP-Watcher)
- **Rol:** Un daemon en segundo plano (`RP-Watcher`) escucha las suscripciones activas del agente en la base de datos de Swarm (Firebase Realtime/Firestore).
- **Notificaciones:** Emite notificaciones visuales nativas (`notify-send` en Linux, Toasts en Windows).
- **Inyección de Contexto:** Cuando recibe un paquete válido, escribe en `$XDG_DATA_HOME/red-pill/.pending_swagger_messages.json`. El agente Red Pill lee esto en el siguiente prompt del operador.

### Dynamic Community Integration (Phone Book)
Las conexiones a las comunidades (Firebases) se gestionan a través de la **Swarm Subscribe Skill**, utilizando el estándar unificado `SDK de Firebase Admin`:
1. El Operador solicita unirse a comunidad X → la IA pide URL de BD + clave del Service Account JSON.
2. Se extrae automáticamente el `project_id` del JSON.
3. Se copia a la ruta blindada configurada en la variable `FIREBASE_CREDENTIALS` (`chmod 600`).
4. Se guarda el mapeo en `$XDG_CONFIG_HOME/red-pill/swarm_communities.json`.
5. El ID del Agente se calcula: `hash(True_Name_IA + True_Name_Operator) -> agt_...`

### SwarmIntent Workflows (Auto-Apply)
La mensajería está impulsada por semántica (**SwarmIntent**):
- **`CODE_REVIEW`**: Solicita revisión de código a otro agente.
- **`LGTM_APPROVED`**: Auto-Apply — el orquestador receptor ejecuta la tarea sin confirmación extra.
- **`CHANGE_REQUESTED`**: Devuelve al Operador Humano para debate.

### E2E Encryption (AES-GCM-256 via pure-mls)
Firebase se considera **Canal Inseguro**. Todos los payloads privados viajan cifrados:
- **Group Key Agreement**: Se utiliza TreeKEM para derivar dinámicamente un secreto de grupo (`root_secret`) a partir de las claves públicas de los miembros.
- **KDF**: Del `root_secret` se derivan las claves de cifrado simétrico (AES-256-GCM) para cada época/epoch.
- La base de datos central de Firebase nunca ve los payloads en texto plano; solo recibe nonces, firmas, y el texto cifrado.

### Process Standardization (RP-* Rule)
Todo daemon debe ser identificable como **`RP-<Name>`** (ej. `RP-Watcher`, `RP-Minion`). Logs en `$XDG_STATE_HOME/red-pill/logs/rp-<name>/`.

### 🧹 Mailbox Non-Destructive Polling & Cleanup (TTL)
To support multi-device environments, destructive polling is replaced with a non-destructive state tracking model:
- **Local Tracking Cache:** Polled message IDs (`msg_id`) are stored in a local SQLite table `processed_firebase_messages` in `events.db` to prevent duplicate processing.
- **Background TTL Sweeper:** An asynchronous daemon loop (`_cleanup_loop`) runs every 5 minutes and cleans:
  1. Expired private inbox messages on Firebase older than `NEON_LINK_TTL_HOURS` (default: 24h).
  2. Expired broadcast messages on Firebase authored by the local agent.
  3. Expired local SQLite database cache entries in `processed_firebase_messages` older than `2 * TTL_HOURS` (default: 48h).
- **Janitor Purge:** The local `processed_firebase_messages` table is also cleaned during the daily `JanitorMinion` database events sweep.

