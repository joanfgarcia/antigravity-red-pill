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
To maintain the **Sound of Silence**, engineers must never use the term "daemon" in new contributions. 

| Obsolete Term | Canonical Term |
| :--- | :--- |
| `bunker_daemon.py` | `bunker_telemetry.py` |
| `red-pill daemon` | `red-pill telemetry` |
| `daemon process` | `Oneshot Task / Ritual / Pulse` |

## 4. Manual Health Verification
```bash
uv run red-pill telemetry
```
This command performs a full hardware and Bünker scan and exits cleanly, providing a snapshot of the current system state.
