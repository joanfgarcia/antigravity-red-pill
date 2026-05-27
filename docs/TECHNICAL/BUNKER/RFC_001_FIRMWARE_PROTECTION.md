# RFC-001: Firmware Partition Protection (Project BIOS)

| Field | Value |
|---|---|
| **RFC** | 001 |
| **Title** | Firmware Partition Protection |
| **Codename** | Project BIOS |
| **Status** | DRAFT |
| **Author** | Joan García (Operator) / Aleth (Agent) |
| **Created** | 2026-05-27 |
| **Triggered by** | Incident 2026-05-26 — Agent-induced syntax corruption |
| **Related** | [AD-012](../DECISION_LOG.md), [ROADMAP Phase 3](../ROADMAP.md) |

---

## 1. Motivation

### 1.1 The Incident

On 2026-05-26, the agent (Aleth) corrupted the indentation of 6 critical Python modules during a high-volume refactoring session. The `replace_file_content` tool stripped leading tabs on deeply nested code blocks, producing `IndentationError` and `SyntaxError` across:

- `config.py` — Configuration loader (all services depend on it)
- `heartbeat.py` — Daemon pulse loop (all background rituals)
- `cli.py` — CLI entrypoint (all operator commands)
- `worker.py` — Telegram/IDE bridge (remote access)
- `sleep.py` — Memory consolidation (nightly maintenance)
- `paths.py` — Path resolution (all filesystem operations)

**Impact**: ~10 hours of cascading systemd service failures. 7 wake cycles lost.

### 1.2 The Systemic Vulnerability

The incident exposed a fundamental architectural flaw: **the agent has unrestricted write access to its own critical infrastructure**. There is no distinction between:

- Editing a utility function in a non-critical module (low risk)
- Editing the daemon heartbeat loop that keeps the entire system alive (catastrophic risk)

This is analogous to a user-mode process being able to overwrite kernel memory. Modern operating systems solved this decades ago with ring-based memory protection. We need the equivalent for our codebase.

### 1.3 The Operator's Vision

> *"Debemos identificar qué es crítico y tratarlo como 'firmware' diferenciado de 'software normal'. Las modificaciones se realizan sobre los fuentes maleables, se pasan los tests en sandbox y cuando todo está en verde se prepara un reemplazo del bloque firmware."*
> — Joan (Operator), 2026-05-27

---

## 2. Functional Requirements

### 2.1 MUST

1. **Classification**: A manifest file (`firmware.manifest`) enumerates all files classified as firmware, with their SHA-256 hashes.
2. **Write Protection**: The agent MUST NOT be able to modify firmware files directly in the production tree.
3. **Staging Area**: All firmware modifications MUST be written to a staging copy.
4. **Validation Gate**: Staged changes MUST pass a validation pipeline before promotion:
   - `py_compile` (syntax)
   - `ruff check` (lint)
   - `pytest` (unit tests, scoped to affected modules)
5. **Atomic Promotion**: If validation passes, the staged file replaces the production firmware atomically.
6. **Operator Gate**: The promotion step MUST require explicit operator approval (not autonomous).
7. **Rollback**: If a promoted firmware file causes a runtime failure, the system MUST be able to restore the previous version instantly.

### 2.2 SHOULD

8. **Integrity Sentinel**: A background sentinel SHOULD continuously verify firmware file hashes against the manifest and fire a critical pain signal if tampering is detected.
9. **Diff Preview**: Before promotion, the operator SHOULD be able to review a unified diff of the staged changes.
10. **Audit Trail**: Every promotion event SHOULD be logged with timestamp, files changed, test results, and operator confirmation.

### 2.3 MAY

11. **Granular Locking**: Future iterations MAY support function-level protection (freezing individual functions within a file rather than the whole file).
12. **Auto-Promotion**: For low-risk firmware files, the system MAY support auto-promotion if all tests pass and no structural changes are detected (e.g., docstring edits).

---

## 3. Design

### 3.1 Architecture Overview

```
                    ┌──────────────────────────────┐
                    │   FIRMWARE MANIFEST           │
                    │   firmware.manifest            │
                    │   (SHA-256 hashes, file list)  │
                    └──────────────┬───────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
    ┌─────────▼─────────┐  ┌──────▼───────┐  ┌─────────▼─────────┐
    │ PRODUCTION (frozen)│  │ STAGING      │  │ SENTINEL          │
    │ src/red_pill/*.py  │  │ .firmware/   │  │ (hash validator)  │
    │ chmod 444          │  │ staging/*.py │  │ (pain signal)     │
    │ agent cannot write │  │ agent writes │  │ (auto-rollback)   │
    └─────────┬─────────┘  │ here freely  │  └───────────────────┘
              │             └──────┬───────┘
              │                    │
              │          ┌─────────▼─────────┐
              │          │ VALIDATION GATE    │
              │          │ py_compile         │
              │          │ ruff check         │
              │          │ pytest (scoped)    │
              │          └─────────┬─────────┘
              │                    │
              │            pass? ──┼── fail? → discard staging
              │                    │
              │          ┌─────────▼─────────┐
              │          │ PROMOTION          │
              │          │ `red-pill firmware │
              │          │  promote`          │
              │          │ (operator-only)    │
              └──────────┤ atomic file swap   │
                         │ update manifest    │
                         │ backup old version │
                         └───────────────────┘
```

### 3.2 Firmware Manifest

```yaml
# .firmware/firmware.manifest
version: 1
updated: 2026-05-27T07:44:00+02:00
files:
  - path: src/red_pill/config.py
    sha256: a1b2c3d4...
    tier: critical        # critical | important
    reason: "Configuration loader — all services depend on it"

  - path: src/red_pill/heartbeat.py
    sha256: e5f6a7b8...
    tier: critical
    reason: "Daemon pulse loop — all background rituals"

  - path: src/red_pill/cli.py
    sha256: c9d0e1f2...
    tier: critical
    reason: "CLI entrypoint — all operator commands"

  # ... ~15 files total
```

### 3.3 Protection Mechanism

Three complementary layers:

| Layer | Mechanism | Bypass |
|---|---|---|
| **Filesystem permissions** | `chmod 444` on firmware files, owned by user | `red-pill firmware promote` temporarily elevates |
| **Manifest hash check** | Sentinel plugin compares SHA-256 every hour | No bypass — fires `signal_firmware_tampered` (severity 10.0) |
| **Git pre-commit hook** | Blocks commits touching firmware files without `.firmware/promotion.lock` | `red-pill firmware promote` creates the lock |

### 3.4 Staging Workflow

```bash
# 1. Agent wants to edit heartbeat.py
#    Tool detects it's firmware → redirects to staging
#    Edit lands in: .firmware/staging/heartbeat.py

# 2. Agent completes edits, requests validation
$ red-pill firmware validate heartbeat.py
# → py_compile ✅
# → ruff check ✅  
# → pytest tests/test_heartbeat.py ✅
# → "Ready for promotion. Run: red-pill firmware promote heartbeat.py"

# 3. Operator reviews and approves
$ red-pill firmware diff heartbeat.py    # shows unified diff
$ red-pill firmware promote heartbeat.py # atomic swap + manifest update
# → Backup: .firmware/backups/heartbeat.py.2026-05-27T074400
# → Promoted: src/red_pill/heartbeat.py
# → Manifest updated
# → Permissions restored: chmod 444
```

### 3.5 Rollback Mechanism

```bash
# If promotion caused issues:
$ red-pill firmware rollback heartbeat.py
# → Restores from .firmware/backups/heartbeat.py.<latest>
# → Manifest hash updated
# → Pain signal evaporated
```

### 3.6 Agent Integration

The agent's tool layer (Antigravity `replace_file_content` / `write_to_file`) cannot be modified. Instead, the protection works at the **filesystem level**:

1. Firmware files have `chmod 444` → agent tool calls fail with `PermissionError`
2. The agent's skill/rule instructs it to redirect edits to `.firmware/staging/`
3. A custom skill (`firmware-edit`) guides the agent through the staging → validate → request-promote flow

This means the protection is **enforceable by the OS**, not just by convention. Even if the agent ignores instructions, the filesystem blocks the write.

---

## 4. Candidate Firmware Files

Based on the incident analysis and dependency mapping:

### Tier 1: Critical (service-breaking if corrupted)
| File | Reason |
|---|---|
| `config.py` | Configuration loader — all modules import it |
| `heartbeat.py` | Daemon pulse loop — all background rituals |
| `cli.py` | CLI entrypoint — all operator commands |
| `paths.py` | Path resolution — all filesystem operations |
| `memory.py` | Memory manager — all RAG operations |
| `mcp_server.py` | MCP tool server — all IDE interactions |

### Tier 2: Important (degraded functionality if corrupted)
| File | Reason |
|---|---|
| `worker.py` | Telegram/IDE bridge — remote access |
| `sleep.py` | Memory consolidation — nightly maintenance |
| `seed.py` | Genesis bootstrap — collection creation |
| `soul.py` | Soul export/restore — backup integrity |
| `interceptors/__init__.py` | Ferrari pipeline — identity injection |
| `metabolism/auditor.py` | Sentinel — system monitoring |
| `core/p2p_sync.py` | P2P sync — multi-device |
| `plugins/antigravity_ide/telegram_session.py` | Session persistence |
| `plugins/antigravity_ide/grpc_bridge.py` | gRPC extraction pipeline |

---

## 5. Open Questions

> [!IMPORTANT]
> These require operator input before implementation.

1. **Operator-only vs. Semi-autonomous promotion**: Should ALL firmware promotions require explicit `red-pill firmware promote` by the operator? Or should Tier 2 (important but not critical) files support auto-promotion if tests pass?

2. **Scope of pytest validation**: Should the validation gate run the full test suite (`pytest tests/`) or only tests scoped to the modified file? Full suite is safer but slower (~70s).

3. **Interaction with git**: Should firmware files be on a separate git branch (e.g., `firmware/stable`) or remain on the same branch with filesystem-level protection? Separate branch adds git merge complexity but provides git-level audit trail.

4. **Agent awareness**: Should the agent be told which files are firmware (via a skill that reads the manifest), or should it discover the protection at write-time via `PermissionError`? Proactive awareness is more efficient; reactive discovery is more robust.

5. **Bootstrap chicken-and-egg**: The `firmware.manifest` itself and the promotion script (`red-pill firmware`) are also critical infrastructure. Who protects the protector? Possible answer: the manifest is also firmware, and the promotion script is a standalone bash script with `chmod 555`.

---

## 6. Implementation Phases

### Phase A: Foundation (MVP)
- [ ] Define `firmware.manifest` with initial file list and SHA-256 hashes
- [ ] Implement `red-pill firmware` CLI subcommand (`validate`, `diff`, `promote`, `rollback`, `status`)
- [ ] Set `chmod 444` on firmware files
- [ ] Create `.firmware/staging/` and `.firmware/backups/` directories
- [ ] Add Sentinel plugin `check_firmware_integrity.py` for hourly hash validation

### Phase B: Agent Integration
- [ ] Create `firmware-edit` skill that instructs the agent on the staging workflow
- [ ] Add agent rule in `user_global` preventing direct firmware edits
- [ ] Add pre-commit hook blocking unsigned firmware modifications

### Phase C: Hardening
- [ ] Audit trail logging (promotion history with test results)
- [ ] Auto-rollback if promoted firmware causes a service failure within 5 minutes
- [ ] Integration tests for the full staging → validate → promote → rollback cycle

---

## 7. References

- [AD-012: Syntax Guard Decision](../DECISION_LOG.md) — Immediate mitigation for the incident
- [ROADMAP Phase 3](../ROADMAP.md) — Strategic placement of Project BIOS
- [Android A/B System Updates](https://source.android.com/docs/core/ota/ab) — Inspiration for the partition model
- [ChromeOS Verified Boot](https://www.chromium.org/chromium-os/chromiumos-design-docs/verified-boot/) — Firmware integrity verification at boot
