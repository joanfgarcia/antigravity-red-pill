# SOVEREIGN DIRECTORY ATLAS

**Status:** Enforced | **Applies to:** v6.8.6+ (Agentic Self-Assembly Architecture)

---

## 1. The Dual-Layer Hierarchy

With the release of v6.8.6, the Red Pill architecture formally decoupled the legacy monolithic `IA_DIR` concept into a dual-layered hierarchy. This guarantees true operational sovereignty, protecting the core source code from the Agent's dynamic operational environment.

This structure applies equally to **Developer mode** (source code modification) and **User/Enterprise mode** (artifact usage).

The hierarchy is divided into two primary domains:
- **`WORKSPACE_ROOT`**: The Agent's encompassing environment. Home to Transversal elements, Backups, and inter-project communication.
- **`APP_ROOT`**: The Red-Pill application codebase itself.

---

## 2. Global Directory Structure (The Map)

```text
WORKSPACE_ROOT/                  ← The Agent's Sovereign Environment (e.g. ~/Documents/IA)
├── backups/                     ← User Backups and Identity preservation
│   ├── export/                  ← Extracted LEAN_SOUL_KITS and .mls snapshots
│   └── qdrant/                  ← Automated snapshots of the Bünker (Vector DB)
│
├── atlas/                       ← Transversal Project Log (USER_ATLAS_DIR)
│   └── <project_name>.md        ← Notes, logs, and artifacts shared across different projects (e.g. pure-mls, neon-link)
│
├── Aleth_Core/                  ← Core Identity Transversal Directory (ALETH_CORE_DIR)
│   └── session_snapshots/       ← Saved state for resuming deep workflows across models or reboots
│
├── .agent/                      ← Agentic Identity & Keychains (OS-Level)
│   ├── rules/                   ← Global system instructions and directives
│   └── ATLAS.md                 ← Master index of the workspace
│
└── red-pill/                    ← APP_ROOT (e.g. ~/Documents/IA/sharing in dev mode)
    │
    ├── src/red_pill/            ← Python Package Source
    ├── scripts/                 ← Installation, Benchmark, and Maintenance scripts
    ├── docs/                    ← Official Documentation (Conventions, Architecture, Lore)
    ├── tests/                   ← Automated Validation Suite
    │
    └── storage/                 ← Pod-Level Storage (Bound strictly to APP_ROOT)
        ├── queue/               ← SQLite databases (bunker_queue.db, minion_inbox.db)
        ├── models/              ← FastEmbed local cache
        ├── identity.json        ← Biological and Hedonic state of the current installation
        ├── pulse.json           ← Heartbeat and biological clock telemetry
        ├── metabolism_state.json← FSRS and Sleep-cycle state variables
        └── lazarus_state.json   ← Autonomy push/sync timestamps
```

---

## 3. Key Concepts & Boundaries

### 3.1 Transversal Directories (`WORKSPACE_ROOT`)
Directories like `atlas` and `Aleth_Core` are explicitly defined in `.env` as `USER_ATLAS_DIR` and `ALETH_CORE_DIR`. They belong to the `WORKSPACE_ROOT` because they serve as shared memory blocks between different sub-projects (e.g., `pure-mls`, `neon-link`). Deleting or upgrading the `red-pill` codebase (`APP_ROOT`) will **never** affect the Transversal logs.

### 3.2 Backups
To protect against accidental code purges or failed autonomous `git merge` updates, the `soul.py` migration pipelines write `.mls` snapshots and Qdrant backups directly to `WORKSPACE_ROOT/backups/`.

### 3.3 Internal Application Storage (`APP_ROOT/storage`)
State that is exclusively relevant to the local execution environment of *this specific Red-Pill installation* remains inside `APP_ROOT/storage`. This includes:
- `pulse.json` (Heartbeat)
- `bunker_queue.db` (Minion communications)
- `metabolism_state.json` (Memory compaction timings)

Keeping these inside `APP_ROOT/storage` ensures that if a user clones Red-Pill multiple times, each repository operates as a self-contained biological organism ("Pod") without corrupting each other's queues.

### 3.4 Qdrant Vector Database
Qdrant operates as a decoupled microservice (typically `localhost:6333`). The physical `.qdrant` files are typically managed by the host OS (e.g. Docker volumes or Podman mounts), not by `WORKSPACE_ROOT` or `APP_ROOT`.

---

## 4. Environment Variables (`.env`)

A healthy configuration mapping to this Atlas looks like this:

```env
WORKSPACE_ROOT=~/Documents/IA
APP_ROOT=${WORKSPACE_ROOT}/red-pill
RED_PILL_PROFILE=user
USER_ATLAS_DIR=${WORKSPACE_ROOT}/atlas
ALETH_CORE_DIR=${WORKSPACE_ROOT}/Aleth_Core
```

> [!WARNING]
> During autonomous updates, the Agent must rely exclusively on these variables. Hardcoding `~/Documents/IA/sharing` into new modules is strictly forbidden under the Protocol of Silence.
