# Maintenance Protocol: Zero-Daemon (Silent) Architecture

This document dictates the maintenance rituals required to keep the Red Pill Bünker healthy under the **Zero-Daemon** (Protocol Silence) paradigm.

## 1. The Pulse (Heartbeat)
The system does not run 24/7. It breathes in cycles (Pulses) triggered by the OS.

- **Tasks**: `redpill-pulse` (Hourly), `redpill-telemetry` (Every 30s), `redpill-queue` (Every 10m).
- **Log Inspection**: 
  - `journalctl --user -u redpill-telemetry.service -f`
  - `journalctl --user -u redpill-pulse.service -f`

> **⚠️ CRITICAL: Crontab & Virtual Environments**  
> If you are scheduling autonomous pulses via `cron`, remember that the cron daemon executes from the user's `$HOME` by default. Using `uv run python src/red_pill/swarm/autonomous_cron.py` directly will trigger `ModuleNotFoundError` (`dotenv`, `platformdirs`, etc.) because the virtual environment is not resolved.  
> **Always** enforce the working directory in your crontab:  
> `0 * * * * cd /path/to/project && /path/to/uv run src/red_pill/swarm/autonomous_cron.py`

## 2. Autonomic Healing (CUDA Drift)
The Bünker monitors its own biological health (NPU/GPU/VRAM).

### Dynamic CUDA Recovery
If a "Pain Signal" regarding `torch_cuda_mismatch` appears in the dashboard, the system can be repaired by running:
```bash
uv run python scripts/setup_torch.py --auto-fix
```
This script:
1. Detects the system CUDA version via `nvcc` or `nvidia-smi`.
2. Projects the correct PyTorch tag (e.g., `cu130`).
3. Verifies URL existence on `pytorch.org`.
4. Reinstalls the matching wheel without manual version entry.

## 3. Nomenclature Standards
To maintain the **Sound of Silence**, the system favors ephemeral one-shots over long-running processes. The ONE exception is the **Sovereign Daemon** (`red-pill daemon`), which runs monitor-only plugins with hard timeouts.

| Obsolete Term | Canonical Term |
| :--- | :--- |
| `bunker_daemon.py` | `bunker_telemetry.py` → now `TelemetryPlugin` in `daemon/plugins/` |
| `LazarusPulse` (heartbeat.py) | **DELETED v7.2.1** — rituals extracted to `rituals.py` |
| Heavy blocking daemon | Timer-triggered one-shot (`redpill-*.timer`) |
| `red-pill daemon` | ✅ Valid — starts the Sovereign Daemon (plugin-based, monitor-only) |

## 3.1 Path Sovereignty

> [!CAUTION]
> **All filesystem paths to external tools (Antigravity IDE, Cursor, etc.) MUST resolve through `core/paths.py` functions.** Hardcoded paths like `Path.home() / ".gemini" / "antigravity"` are FORBIDDEN outside of `core/paths.py` and `config.py`. This is enforced by `test_path_sovereignty.py`.

| Path | Function |
| :--- | :--- |
| `~/.gemini/antigravity/` | `get_antigravity_root()` |
| `~/.gemini/antigravity/brain/` | `get_antigravity_brain_dir()` |
| `~/.gemini/antigravity/rules/` | `get_antigravity_rules_dir()` |
| `~/.gemini/antigravity/conversations/` | `get_antigravity_conversations_dir()` |

## 4. Manual Health Verification
```bash
uv run red-pill telemetry
```
This command performs a full hardware and Bünker scan and exits cleanly, providing a snapshot of the current system state.

## 5. Neon-Link Watchdog & P2P Transport (v0.5.0+)

Since `neon-link>=0.5.0`, the daemon includes native `sd_notify` heartbeats (from v0.4.0), P2P transport via `neon-rings`, non-destructive Firebase polling with background TTL sweep, and Protocol of Silence licensing. The systemd unit must be configured with:

```ini
[Service]
Type=notify
WatchdogSec=3
NotifyAccess=all
Restart=on-failure
```

### Upgrade from pre-0.5.0
1. Update dependency: `uv sync` (resolves `neon-link>=0.5.0` and transitive `neon-rings>=0.1.1`)
2. Update the systemd unit file with `Type=notify` and `WatchdogSec=3`
3. Reload and restart: `systemctl --user daemon-reload && systemctl --user restart neon-link.service`
4. Disable legacy aliases: `systemctl --user disable redpill-neonlink.service`

> **⚠️ CRITICAL:** The `neon-link-healer` (service + timer + script) is **removed** in v0.4.0. Native WatchdogSec replaces the curl-based health check. If the healer is still running, disable it:
> ```bash
> systemctl --user disable neon-link-healer.timer neon-link-healer.service
> ```

### Verification
```bash
# Check watchdog is active
systemctl --user show neon-link.service | grep -E "Type|Watchdog"
# Expected: Type=notify, WatchdogUSec=3000000
```

## 6. NPU Health Check (FastFlowLM)

For systems with AMD XDNA2 NPU:
```bash
# Validate NPU stack
flm validate
# Expected: NPU FW Version >= 1.1.0, amdxdna >= 0.6, Memlock = infinity

# Ensure memlock is unlimited (required after reboot)
ulimit -l  # Should show "unlimited"
# If not: sudo prlimit --memlock=unlimited --pid $$
```
