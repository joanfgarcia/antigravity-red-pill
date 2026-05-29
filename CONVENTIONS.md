# Red-Pill Sovereign Architecture Conventions

## 🚨 RULE 1: XDG Base Directory Compliance (STRICT)

All configurations, application states, queues, logs, and models **MUST** strictly adhere to the Linux XDG Base Directory standard.

### Prohibitions (The Smith Filter)
- **NEVER** use a local `storage/` directory inside the repository.
- **NEVER** use `os.path.join(APP_ROOT, "storage")`.
- **NEVER** create `.db` files or caches inside the project root (`WORKSPACE_ROOT`).

### Approved Resolver (The Only Way)
All path resolution across the entire codebase for configurations, databases, models, queues, state, etc. **MUST** strictly go through the centralized resolvers provided by [paths.py](file:///home/joan/Documents/IA/sharing/src/red_pill/core/paths.py). Ad-hoc path resolution using relative directories, `os.path.join(os.getcwd(), ...)` or direct file system assumptions is strictly forbidden. This module uses `platformdirs` to guarantee OS-agnostic compliance and serves as the single source of truth for all system paths.

| Data Type | XDG Standard | Path Resolver |
|-----------|--------------|---------------|
| Configuration | `~/.config/red-pill/` | `get_config_dir()` |
| App Data (Qdrant) | `~/.local/share/red-pill/` | `get_data_dir()` |
| Databases (SQLite) | `~/.local/share/red-pill/db/` | `get_db_dir()` |
| AI Models (.gguf) | `~/.local/share/red-pill/models/` | `get_models_dir()` |
| Background Queues | `~/.local/share/red-pill/queue/` | `get_queue_dir()` |
| Ephemeral State | `~/.local/state/red-pill/` | `get_state_dir()` |
| Daemon Execution | `~/.agent/model-daemon/` | `get_daemon_dir()` |
| Model Profiles | `~/.agent/model_profiles.yaml` | `get_model_profiles_path()` |
| Model Files | `~/.local/share/red-pill/models/<name>` | `resolve_model_path(name)` |

### Exceptions
- **Backups**: By default, backups do NOT go to XDG. They must go to the user's defined AI directory: `<IA_DIR>/backups/red-pill/` (resolved via `get_backup_dir()`).

---
*Failure to comply with this rule will result in the `tests/test_xdg_compliance.py` Smith Filter failing the CI/CD pipeline.*

---

## 🚨 RULE 2: Working Tree Cleanliness (Scratch Directory)

To maintain a pure architectural root directory, the creation of ad-hoc or temporary files in the repository root is strictly forbidden.

### Prohibitions
- **NEVER** create `test_*.py`, `check_*.py`, `demo_*.py` or similar one-off scripts in the repository root.
- **NEVER** output `.json`, `.db`, or `.log` files to the repository root.

### Approved Resolver (The Scratch Dir)
- All "throwaway" scripts, temporary debugging tests, or experimental outputs **MUST** be placed in the `scratch/` directory.
- The `scratch/` directory is gitignored by default and serves as the sandbox for experimental and disposable code.

---

## 🚨 RULE 3: Service Health Contract (Systemd Services)

Every systemd service in the ecosystem **MUST** declare its monitoring strategy in `examples/services.yaml` (template) / `~/.config/red-pill/services.yaml` (runtime). A service without an entry in this manifest is **not a citizen** of the ecosystem.

> For full technical reference, see [SERVICE_HEALTH_CONTRACT.md](docs/TECHNICAL/OPERATIONS/SERVICE_HEALTH_CONTRACT.md).

### Service Types

| Type | Description | Required Fields | systemd Parameters |
|------|-------------|-----------------|-------------------|
| `daemon-loop` | Long-running process with a periodic loop | `loop_interval_s`, `watchdog_multiplier` | `Type=notify`, `WatchdogSec` |
| `daemon-listener` | Blocks on socket accept (HTTP server) | `health_url` | `Type=simple` (no watchdog) |
| `oneshot` | Runs once and exits (timer-triggered) | `max_runtime_s` | `Type=oneshot`, `TimeoutStartSec` |

### Mandatory Requirements

1. **`daemon-loop` services** MUST call `sd_notify("WATCHDOG=1")` in their main loop. The unit file MUST set `Type=notify` and `WatchdogSec = loop_interval_s × watchdog_multiplier`.
2. **`daemon-listener` services** MUST expose a `/health` HTTP endpoint. No WatchdogSec (would kill idle listeners).
3. **`oneshot` services** MUST declare `max_runtime_s`. The unit file MUST set `TimeoutStartSec` accordingly.
4. **All services** MUST declare `legacy_aliases` if predecessor services existed under different names to prevent duplicate-process incidents.

### sd_notify Implementation (Zero Dependencies)

```python
import os, socket

def _sd_notify(state: str) -> None:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if addr[0] == "@":
            addr = "\0" + addr[1:]
        sock.sendto(state.encode(), addr)
        sock.close()
    except Exception:
        pass
```

### Why This Matters

On 2026-05-22, two identical Neon-Link services (`neon-link.service` + `redpill-neonlink.service`) ran in parallel for 10+ hours undetected, causing 4x duplicate Telegram responses. This rule exists to prevent exactly that class of incident.

---
*Failure to comply will be detected by the Sentinel's `ServiceHealthCheck` plugin during the hourly audit cycle.*

