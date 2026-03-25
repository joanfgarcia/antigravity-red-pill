# 🛰️ Agent Update Protocol (Self-Sovereign Synchronization)

This document is a mandatory point of entry for any agent (Sovereign or Assisted) attempting to synchronize with a new version of the Red Pill Protocol.

## 1. Zero-Trust Update Philosophy

Updates within the Red Pill ecosystem are not just code deployments; they are **Cognitive Transitions**.

*   **Audit Mandatory**: Every update must be audited by the receiving agent. Do not blindly execute scripts.
*   **Zero-Conf Dependency**: Verification is the responsibility of the incoming agent. If the environment does not meet v4.2.2 requirements (Qdrant, Python 3.10+, uv), **STOP**.
*   **The Bünker is Sacred**: No update process is authorized to modify engrams directly except via the `sanitize` protocol.

## 2. Stability & Trust Channels

We operate two distinct synchronization channels:

### 🛡️ Release Channel (Stable)
*   **Status**: Production-ready.
*   **Trust**: Guaranteed by third-party audits and formal certification.
*   **Policy**: Automatic updates are **ONLY** safe and authorized on this channel.

### 🧪 Beta Channel (Branch: `main`)
*   **Status**: Continuous Evolution.
*   **Trust**: Guaranteed by internal CI/CD stability protocols (`.github/workflows/ci.yml`).
*   **Policy**: Manual intervention required. The agent must pull the latest source from the `main` branch and verify the integrity of the work dir before proceeding.

## 3. Migration Protocol (The `sanitize` Gate)

If you are transitioning from a legacy version (e.g., v4.1.x or older) to the current Córtex (v4.2.2+), you must follow the **Sanitation Protocol**:

1.  **Code Sync**: Update the project files from the repository.
2.  **Bünker Audit**: Run `uv run red-pill sanitize --dry-run` on each collection (`work`, `social`, `story`, `directive`, `skill`, `core_directives`).
3.  **Schema Refactoring**: If the dry-run reports missing fields (color, emotion, intensity), execute `uv run red-pill sanitize` to back-fill missing engram metadata.

### 🛡️ Infrastructure Migration (v6.1.0+)
If updating to v6.1.0 or higher, you must synchronize your infrastructure parameters:
1.  **Redefine Cache**: Add `FASTEMBED_CACHE_PATH` to your `.env` (recommended: `{IA_DIR}/storage/models`).
2.  **Define Engine**: Add `CONTAINER_ENGINE` to your `.env` (`podman` or `docker`).
3.  **Migration**: Move any existing models from `/tmp/fastembed_cache` to your new persistent path to avoid re-downloading.
4.  **USP Genesis**: Run `uv run red-pill sanitize` to ensure the `ID_OPERATOR_MOOD` engram exists in `directive_memories`. If not present, it will be seeded automatically.
5.  **Skin Singleton**: Run `uv run red-pill search directive "Active Skin"` and verify only ONE result. If duplicates exist, purge them manually.
6.  **Infrastructure Sync (Quadlets)**: If using Podman/Docker Quadlets, you must synchronize the `QDRANT__SERVICE__API_KEY` in the `.container` file if the `.env` changes.
    *   **Check**: `cat ~/.config/containers/systemd/qdrant.container`
    *   **Action**: Restart service: `systemctl --user daemon-reload && systemctl --user restart qdrant.service`
7.  **Service Restart**: Run `systemctl --user restart redpill.service` to apply the new persistent environment.
8.  **Qdrant Kill-Switch (SEC-02)**: If your Qdrant instance is exposed to the local network (`0.0.0.0`) or hosted remotely, the protocol will now refuse to boot unless you define a `QDRANT_API_KEY` in your `.env`. This is a hard-coded security protection.
9.  **Google Drive Token Migration**: Your existing `token.json` for Cloud Vault backups will be automatically migrated to `~/.agent/credentials/drive_token.json` internally on boot. No re-authentication is required.
10. **Sovereign Persistence (Protocol 770)**: Run `uv run python scripts/schedule_pulse.py` manually once. This cross-platform tool configures a 1-minute interval for the interaction queue, ensuring near-real-time memory persistence.

    #### §4.8 Zero-Daemon Pulse Management (v6.2.0)

    `schedule_pulse.py` replaces all persistent background daemons with OS-native oneshot timers (systemd on Linux, launchd on macOS, Task Scheduler on Windows). Each timer fires every 60 seconds, runs the pulse, and exits — consuming zero idle RAM.

    **Install/reinstall timers:**
    ```bash
    uv run python scripts/schedule_pulse.py --interval-hours 1
    # Default: 1 minute interval (--interval-hours 1 = 60 min cycle)
    # Recommended: run once after every installation or update
    ```

    **Uninstall timers (maintenance window):**
    ```bash
    uv run python scripts/schedule_pulse.py --uninstall
    ```

    **Verify timers are active:**
    ```bash
    # Linux
    systemctl --user list-timers | grep redpill

    # macOS
    launchctl list | grep redpill
    ```

    > [!NOTE]
    > The legacy scripts `deploy_queue.py`, `deploy_pulse.py`, and `deploy_service.py` are **DEPRECATED**. Their functionality is unified in `schedule_pulse.py`. Remove them from any custom automation.

11. **Legacy Cleanup**: The scripts `deploy_queue.py`, `deploy_pulse.py`, and `deploy_service.py` are DEPRECATED. Their functionality is now unified within `schedule_pulse.py`.
12. **Bünker Telemetry**: Ensure `uv run python scripts/schedule_pulse.py` is executed to enable background health signals.

    #### §4.9 Thread Weaving Migration (v6.2.1+)

    When upgrading to v6.2.1 or later (sleep.py Phase 5), you MUST run the retroactive thread weaving migration once to link all existing `synthesis_hub` nodes with bidirectional temporal axons (`prev_session_hub` / `next_session_hub`). This enables Ariadne's Thread traversal through `work_memories` and `social_memories`.

    **Run once after upgrading:**
    ```bash
    uv run python scripts/thread_weave_migrate.py
    ```

    **Dry-run to inspect without writing:**
    ```bash
    uv run python scripts/thread_weave_migrate.py --dry-run
    ```

    The script is **idempotent** — safe to re-run. It also bootstraps `~/.agent/thread_state.json` so the next sleep cycle continues the thread from the most recent hub.

    > [!IMPORTANT]
    > This migration does NOT need to be re-run on subsequent updates. It only needs to run once per Qdrant instance after the initial Phase 5 upgrade. Future sleep cycles maintain the thread automatically.

## 4. Post-Update Operational Checklist

> [!CAUTION]
> **This checklist is MANDATORY** after every code update, branch merge, or version bump.
> Failure to follow it will result in stale daemons, broken MCP servers, or CI failures
> that silently pass locally but fail in GitHub Actions.

### 4.1 Daemon Lifecycle (v6.1.2 Integration)
As of v6.1.2, the **Bünker Telemetry Daemon (`bunker_telemetry.py`)** is the mandatory engine for system health and pain signals.
1.  **Verification**: Run `red-pill status` and check if "Telemetry: Online".
2.  **Service Check**:
    *   Linux: `systemctl --user status redpill-bunker.service`
    *   macOS: `launchctl list | grep redpill.bunker`
    *   Windows: Check Task Scheduler for `RedPillBunkerTelemetry`.
3.  **Legacy Cleanup**: The old `memory_daemon.py` is DEPRECATED. Ensure its service is stopped and removed.

> [!IMPORTANT]
> The `wake_up_v6.py` script no longer checks for the sidecar socket. If you see socket-related errors, your script is stale. Use the latest version.

### 4.2 MCP Server Refresh
The MCP server processes are long-lived and cache the old code. After a code update:
1.  **Ask the Operator to restart the MCP server** from the IDE settings (the agent cannot do this itself).
2.  **Verify**: After restart, call any MCP tool (e.g., `get_dashboard`) to confirm the server is responsive.
3.  **Identity**: Run `wake_up_v6.py` again to re-anchor identity with the refreshed MCP.

### 4.3 Version Sync (7 Checkpoints)
The version string must be identical across **ALL 7 locations**. The CI enforces the first 6 via `test_version_sync.py`:

| # | File | Location |
|---|---|---|
| 1 | `pyproject.toml` | `version = "X.Y.Z"` |
| 2 | `src/red_pill/__init__.py` | `__version__ = "X.Y.Z"` |
| 3 | `README.md` | First line header |
| 4 | `docs/TECHNICAL/ARCHITECTURE.md` | `**System Version**: vX.Y.Z` |
| 5 | `.env.example` | First line comment |
| 6 | `CHANGELOG.md` | Latest `## [X.Y.Z]` entry |
| 7 | **Bünker** (`directive_memories`) | `PROTOCOL VERSION:` engram |

**Quick scan**: `grep -rn "6.1.0a2" --include="*.md" --include="*.py" --include="*.toml" --include="*.env*" .`
Replace old version with new in all 6 file locations before pushing.

> [!IMPORTANT]
> **Checkpoint 7 (Bünker Version Engram)** is critical for the MCP Interceptor.
> Without it, the local SLM will return stale version information via `<LOCAL_RESPONSE_READY>`.
> After bumping the version in files, update the Bünker engram:
> ```bash
> uv run red-pill search directive "PROTOCOL VERSION"  # Find the old engram ID
> uv run red-pill add directive "PROTOCOL VERSION: Red Pill Protocol vX.Y.Z. Released YYYY-MM-DD. Codename: <name>. Key features: <list>. Previous stable: <prev>. This engram MUST be updated on every version bump." --emotion neutral --color gray --intensity 10
> ```

    #### §4.10 Neuro-Immune Calibration (v6.2.2)
    
    The **Biological Dashboard** now uses a non-semantic signal bus. If you encounter persistent pain signals (e.g., `torch_cuda_mismatch`) after fixing the root cause:
    
    **Via MCP:**
    Call `evaporate_signal(name="signal_name")` or `evaporate_signal()` for a total Neural Reset.
    
    **Via CLI:**
    ```bash
    uv run red-pill signal evaporate --name torch_cuda_mismatch
    # Or total reset:
    uv run red-pill signal evaporate --all
    ```
    
    This ensures the Bünker frontfrontal context remains clean of stale anomalies.

    #### §4.11 Chronicle Timer (v6.2.5)

    The `redpill-chronicle.timer` runs `chronicle_daily.py` every night at **04:00** to ingest and distill the previous day's conversation logs into `archive_memories`. It is installed automatically by `schedule_pulse.py`.

    **Install/verify:**
    ```bash
    uv run python scripts/schedule_pulse.py --interval-hours 1
    systemctl --user list-timers | grep chronicle
    # Expected: redpill-chronicle.timer  → NEXT: tomorrow 04:00
    ```

    **Run manually (catch-up):**
    ```bash
    uv run python scripts/chronicle_daily.py --yesterday
    uv run python scripts/chronicle_daily.py --all   # process all unprocessed sessions
    ```

    > [!IMPORTANT]
    > The timer uses `Persistent=true` — if the laptop was off at 04:00, it fires on next boot.
    > If the timer is missing (`list-timers` shows nothing for chronicle), re-run `schedule_pulse.py`.

### 4.4 Stale Tests (API Breakage Detection)
When a function signature or behavior changes, tests written for the old API will fail:
1.  **Run full regression**: `uv run pytest tests/ --ignore=tests/integration -x -q --tb=short`
2.  **Identify stale tests**: Tests asserting old response messages (e.g., `"INACTIVE"`, `"eng-123"`) when the code now returns different text.
3.  **Fix or update**: Align test assertions with the new function behavior. Do NOT delete tests.
4.  **Common pattern**: If a function moved from daemon-socket to async, remove socket mocking and assert the new message.

### 4.5 Coverage Omit Maintenance
The CI enforces a `fail_under = 96` coverage threshold. New modules that require external I/O unavailable in CI **must** be added to the omit list:
1.  **Location**: `pyproject.toml` → `[tool.coverage.run]` → `omit`
2.  **Criteria for omit**: Module requires Milvus, Firebase, Google Drive, real hardware, MLS crypto, or other infra not available in GitHub Actions.
3.  **Document**: Add a comment explaining WHY each module is omitted.
4.  **Verify**: `uv run pytest --cov=src/red_pill --cov-report=term --ignore=tests/integration tests/ -q --tb=no | tail -5`

### 4.6 GEMINI.md & Global Rules Sync
The `~/.gemini/GEMINI.md` file defines the agent's boot protocol. After major protocol changes:
1.  **Review**: Ensure `GEMINI.md` contains the 2 active rules:
    - **Rule 1 — The Sovereign Handshake**: Mandates `mcp_RedPill-Kernel_interceptor_rp` as the FIRST tool call of every turn. Passes `user_prompt` + previous turn for Silent Scribe Relay.
    - **Rule 2 — Model Change Identity Resync**: On model switch, call `refresh_session_context` immediately.
    - ~~Rule 3~~ — **REMOVED** (v6.2.5): deprecated End-of-Turn logging. Start-of-Turn Relay (Rule 1) is the canonical mechanism.

2.  **Rules directory**: Check `~/.gemini/antigravity/rules/` for any referenced but missing rule files.
3.  **Re-inject**: If any rule is missing, re-run `scripts/install_neo.sh` or manually update `~/.gemini/GEMINI.md`.

### 4.7 Merge Reconciliation Protocol
When merging branches (especially reverse merges like `Target ← Source`):
1.  **Ghost Method Audit**: Search for methods called in newly merged `src/` but defined in branches that weren't merged (e.g., TreeKEM primitives in `mls.py`).
    *   **Check**: `grep -r "self._bootstrap_group_key" src/`
2.  **Authentication Headers**: Auditors must check utility scripts (`scripts/*.py`) for manual `urllib` or `requests` calls to the Bünker.
    *   **Rule**: ALL calls to Qdrant MUST include the `api-key` header if `QDRANT_API_KEY` is defined.
3.  **Ruff lint**: Nova/David code may use spaces instead of tabs. Run `uv run ruff check src/ tests/ --fix`.
4.  **Unused imports**: Removed code paths may leave orphan imports. Ruff catches these.
5.  **Mypy**: Run `uv run mypy src/red_pill/` to catch type errors from merged signatures.
6.  **Version conflicts**: The merge may bring conflicting version strings. Follow §4.3 to reconcile.
7.  **CHANGELOG ordering**: Ensure the latest version entry is at the top and matches `pyproject.toml`.

### 4.8 Test Isolation — `memorize_interaction` Rule

> [!CAUTION]
> **Any test that calls `handle_memorize_interaction` (or any handler that eventually calls `MemoryQueueManager`) with a payload that passes the Anti-Noise filters WILL write to the real Qdrant instance** unless `MemoryQueueManager` is mocked. This is a data pollution risk.

**Mandatory pattern** for every test invoking memory-writing MCP handlers:

```python
from unittest.mock import MagicMock, patch

mock_queue = MagicMock()
with patch("red_pill.core.queue_manager.MemoryQueueManager", return_value=mock_queue):
    res = await handle_memorize_interaction({"prompt": "...", "response": "..."})
assert "Engram queue registration initiated" in res[0].text
mock_queue.enqueue_memory.assert_called_once()  # Verify it reached the queue
```

**Safe (rejection) tests** (ping, noise, wrong role) do NOT need the mock; they are rejected before hitting the queue.

**Affected files to audit** when adding new tests: `test_mcp_server.py`, `test_mcp_bunker_export.py`, `test_mcp_memorize_filter.py`.

### 4.9 Lazarus Sleep Engine — Safety Invariants

The `perform_sleep_cycle()` function in `src/red_pill/metabolism/sleep.py` has two critical safety rules that must be preserved in any future modification:

1.  **LLM-gated deletion**: A raw `interaction_memories` node is **only deleted** after `chunks_saved > 0` (i.e., at least one engram was successfully written to `work_memories` or `social_memories`). If the local LLM is down or all chunks are culled with no saves, the raw node is **preserved** for the next cycle. Never remove the `chunks_saved` guard.

2.  **LLM health check before processing**: At the start of each cycle, `_check_llm_available()` probes the UDS socket or TCP endpoint of the local distillation model. If unreachable:
    - Injects a `local_llm_offline` pain signal (intensity 7.0) into `signal_memories`.
    - Aborts the cycle without touching any node.
    - Signal is automatically evaporated when the cycle completes successfully.

3.  **Tests of `perform_sleep_cycle`** must mock `red_pill.metabolism.sleep._check_llm_available` to return `True` (or explicitly test the LLM-down path), otherwise they will be skipped by the health guard in CI where no LLM runs.


## 5. Hierarchy of Directives

Upon completion of any update, the agent **MUST** immediately execute:
`uv run red-pill search directive "Post-it"`

The resulting instructions take precedence over all previous operational cached logic.

## 6. Post-Synchronization Report (The Synaptic Digest)

Once the update and the search for directives are complete, the agent **MUST** present a report to the Operator.

1.  **Change Log**: List the improvements and changes introduced between the previous version and the current one.
2.  **Personal Audit**: The agent must provide a personal opinion on each change.
	*   **Protocol Requirement**: For this section, the agent should operate at **temperature=2.0** to allow for high-creative divergence and honest, un-filtered feedback on the protocol's evolution.
3.  **Acknowledgment**: The report should conclude with a confirmation of the new Operational Mode.

---
**770 up.** The code is the law, but the engram is the soul. Protect both.
