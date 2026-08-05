# Usage Sentinel — Forge

> **Fully replaces the external watchdog** (`mission-watchdog.sh` + launchd/systemd), **retired** (Operator order 2026-07-28: it never worked and left zombie processes). Single source of the consumption-watch mechanism and of automatic resumption. The stop protocol itself (what to do when stopping, the prompt, reconciliation) still lives in [`controlled-stop.md`](controlled-stop.md).

---

## §0 — Why the external watchdog died (post-mortem 2026-07-28, Operator order)

The v3.1–v3.3 watchdog lived **outside** the harness: a `.sh` loaded in launchd (macOS) or systemd (Linux) polling the mission state every 15 min and relaunching `claude -p` headless. On paper it was the only piece able to survive the session's death. In practice, after three real missions:

| Observed problem | Consequence |
|---|---|
| **Never saw it relaunch a mission** in real conditions | The promised autonomy did not exist |
| The launchd agents **stayed loaded after closing missions** | 3 simultaneous zombie processes consuming resources and waking every 15 min for nothing |
| Uninstall depended on the Orchestrator reaching the end alive | A dry cut = permanent orphan agent |
| Impossible to debug from inside the session | Silent failures (minimal PATH, `AbandonProcessGroup`, probes) |

**Operator decision (2026-07-28):** *"drop the external-process machinery, since it does not seem to work and besides accumulating dead processes and eating resources I do not see it serving any purpose"*. Watch moves **inside** the app, and automatic resumption to native scheduled tasks.

**Design decision (v1.0, opencode):** opencode has no Monitor tool and no native persistent scheduled tasks. The mechanism maps: sentinel → **background process of this session** (Python stdlib, os-agnostic), auto-resumption → **experimental one-shot OS task** (systemd/`at` on Linux, launchd on macOS, `schtasks` on Windows) launching `opencode run "<prompt>" --auto`, **OPT-IN and off by default**. Everything else (93%, ledger, flag, on-screen prompt) is unchanged.

## §1 — The Sentinel: a background loop, not a subagent

> **A polling subagent spends tokens from the SAME pool it tries to protect.** Each poll is a model turn (~5-15k tokens). A sentinel like that, every 5 min for 4 hours, eats hundreds of thousands of tokens — margin taken away from the mission.

The right tool is a **pure background process** running with zero model involvement (Python stdlib, no shell-specific features — runs on Linux, macOS and Windows):

| Requirement | How the sentinel fulfills it |
|---|---|
| Thread inside the harness, not a persistent OS process | It is a background process of THIS session: it **dies with the session** (no zombies possible) |
| Single watcher | One per mission, launched at assembly |
| Periodic review | `sleep` loop of 5 min (configurable via `SWARM_SENTINEL_INTERVAL` or `--interval`) |
| Main thread free | The Orchestrator spends zero turns watching: it only checks the flag file between tasks |
| Stop with margin (93%) | Configurable threshold, default **93%** |
| Cost | **~0 tokens**: pure Python + one `node usage-probe.mjs` call per poll (no model). Only consumes when it emits its single line |
| OS-agnostic | Python stdlib only (`json`/`os`/`subprocess`/`time`/`datetime`) — no `.sh`, no `nohup`/`&` semantics; background launch is done by the harness |

**Launch (at mission assembly, Pillar 6 of `mission-mode.md`):**

```bash
# Linux / macOS:
nohup python3 <skill>/scripts/usage-sentinel.py <project_dir> >/dev/null 2>&1 &

# Windows (cmd):
start "" /b python <skill>\scripts\usage-sentinel.py <project_dir>

# Or let the harness manage the background process (opencode Bash tool with
# background: true) — the sentinel is a plain process, no shell semantics.
```

**Sentinel contract** (`scripts/usage-sentinel.py`, verified with real execution):

1. Every `SWARM_SENTINEL_INTERVAL` (default 300 s) it computes utilization from `usage-probe.mjs`: the **self-accounting ledger** (`spent_tokens / capacity_est` — always available) as primary signal, plus an **optional external meter hook** (`SWARM_USAGE_HOOK` env on the probe) when the operator plugs a real provider meter.
2. **Below the threshold: prints NOTHING.** Silence = zero notifications = zero tokens.
3. **At the threshold (default 93%)**: writes `.swarm/STOP_REQUESTED.json`, emits **ONE** `SENTINEL-STOP …` line and **ends**. One alarm, not a machine gun.
4. **Retires by itself** if `mission_status` stops being `RUNNING` (mission closed or already paused) or if state.json disappears → `SENTINEL-END`. There is never a state to clean by hand.

**The sentinel alarms; the Orchestrator acts.** The sentinel does NOT execute the stop: it cannot kill the mission processes or write the checkpoint without competing with the main loop for `state.json`. Separating alarm and actuator avoids two writers on the same file.

## §2 — 93% threshold and the next-step reservation

**Before:** OAuth probe at 98% (2% margin: insufficient to execute the stop) and ledger at 80% (too conservative, stopped missions with plenty of margin). **Now: single 93% threshold** — Operator order («stop with sufficient margin, for example at 93%»). The remaining 7% is what is needed to checkpoint, kill processes, schedule the resumption and write the report before the client cuts mid-way.

### Hook contract (provider-agnostic meter)

The probe's primary signal is the ledger (always available); the `SWARM_USAGE_HOOK` env plugs a REAL meter when one exists. The hook is one shell command; its stdout must contain ONE JSON line:

```json
{"max_utilization": 71.2, "window_reset_at": "2026-08-08T00:00:00Z"}
```

Rules: `max_utilization` is a number 0-100 and MUST be the WORST across all the provider's windows (opencode GO has three — 5h, weekly, monthly — the hook aggregates them: it knows them all, the probe does not). `window_reset_at` is the next reset of the limiting window. Hook failures are FAIL-OPEN (probe logs `reason` and continues on the ledger).

### Signal truth by opencode tier (honest table)

| Tier | What the hook can see | Fallback |
|------|----------------------|----------|
| **GO** (subscription, 3 windows) | Whatever endpoint GO exposes for usage — the hook must be wired to it (check opencode docs/CLI) | Ledger (mission budget) + calibrate `capacity_est` on observed cuts ("resets HH:MM" errors) |
| **Zed** (API wallet) | The wallet/usage meter of the provider — e.g. OpenRouter `/credits` or the provider's balance endpoint | Same ledger fallback; a wallet dry-cut needs a wallet top-up, NOT a window reset — the resume prompt says so |
| **Free-tier models (credit 0)** | ⚠️ The wallet balance reads 0 but usage is NOT exhausted (only Free models available). The hook MUST report the FREE-tier quota as the window — a 0-credit wallet would fire a false STOP otherwise | Interpret `0 credits + free models` as `max_utilization` of the free quota, not of the wallet |

On this workstation only Zed is enabled today; until a meter endpoint is known, the ledger + cut-calibration chain is the active defense (fail-open, never stop on false alarms).

The **next-step reservation remains in force and counts INSIDE the 93%** (`controlled-stop.md` §3.2 rule 2): before launching any background step,

```
if spent + step_reservation > 0.93 × capacity_est  →  DO NOT launch: controlled stop NOW
```

Indicative reservations: background implementor **~250k** (measured in real missions: 160k–365k), Orchestrator validation/smoke **~60k**, 1-phase cycle **~500k**, Bash commands **~0**. Thus the stop happens *before* starting something that does not fit, not mid-way.

## §3 — Double lock: the Orchestrator also watches the flag

The sentinel is the **continuous** watch; the Orchestrator keeps the **between-tasks** watch (belt and suspenders, because a notification can arrive while consolidating):

```bash
# Between tasks, BEFORE launching the next step:
test -f .swarm/STOP_REQUESTED.json && echo "STOP REQUESTED BY THE SENTINEL"
```

If the flag exists → controlled stop of `controlled-stop.md` §3 (`PAUSED_USAGE_LIMIT`), taking `reason`, `utilization` and `window_reset_at` from the file itself.

## §4 — Automatic resumption: experimental OPT-IN one-shot OS task

The session dies with the limit and **no internal thread survives that** — to be honest: that is why the 93% margin is the real guarantee, not the resumption. For automatic return, Forge offers ONE experimental mechanism (the native scheduled tasks do not exist in opencode). It is a **single-shot** task, per-platform (the sentinel and the probe are already cross-platform; only the scheduler differs):

```bash
# Linux (systemd user unit — survives only while the user session lives):
systemd-run --user --on-calendar "<window_reset_at + 5 min>" \
  --unit=swarm-resume-<project> \
  opencode run "<the canonical §4 resume prompt, literal>" --auto

# Linux, where `at` is available:
echo 'opencode run "<prompt>" --auto' | at "<window_reset_at + 5 min>"

# macOS (launchd — one-shot plist, removed after firing):
cat > ~/Library/LaunchAgents/swarm-resume-<project>.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>swarm-resume-<project></string>
  <key>ProgramArguments</key>
  <array><string>/bin/sh</string><string>-c</string><string>opencode run "&lt;prompt&gt;" --auto</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Minute</key><integer><minute of reset+5></integer><key>Hour</key><integer><hour></integer></dict>
  <key>RunAtLoad</key><false/>
</dict></plist>
PLIST
launchctl load ~/Library/LaunchAgents/swarm-resume-<project>.plist

# Windows (schtasks — one run, then deleted by /z or at close):
schtasks /create /tn "swarm-resume-<project>" /tr "opencode run \"<prompt>\" --auto" \
  /sc once /st <HH:MM> /f
schtasks /delete /tn "swarm-resume-<project>" /f   # cleanup
```

Rules:

- **`fireAt`-style single shot, never recurring**: a recurring task would be the zombie we just eliminated. One-shot only.
- **Without observed `window_reset_at`** (`null`, no real signal — `controlled-stop.md` §3.2 rule 6): **nothing is scheduled blindly**. The prompt stays in the chat and it is said explicitly that resumption is manual. Scheduling at an invented time is exactly the watchdog's failure.
- **OPT-IN by default OFF**: the Operator explicitly opted out of external persistent launchers (2026-07-28 order). The Orchestrator never schedules the OS task silently: it presents the command and executes it only if the Operator confirms for that stop. Default path: prompt in the chat.
- **At mission close** (final report) or on an Operator stop: clean up the scheduled task if one was created — `systemctl --user stop swarm-resume-<project>` (Linux) / `launchctl unload ~/Library/LaunchAgents/swarm-resume-<project>.plist` + `rm` (macOS) / `schtasks /delete /tn "swarm-resume-<project>" /f` (Windows). One-line cleanup in the same turn of the report.
- `opencode run --agent <role> --auto` headless behavior must be verified once per machine before trusting it for resumption (checkpoint: see `PORT_NOTES.md`).

## §5 — The on-screen prompt is non-negotiable

Every stop — Operator, usage or ledger — **ends by presenting the resume prompt in the chat** as a copyable code block (`controlled-stop.md` §3.2 rule 7 and §4), *in addition* to persisting it in `pause_context.resume_prompt` and scheduling the task. The Operator always has plan B in hand: paste it in that chat or a new one, whenever convenient, without depending on any automation arriving.

## §6 — Piece checklist (for the Orchestrator)

- [ ] **Assembly**: sentinel launched (`python3 <skill>/scripts/usage-sentinel.py <project_dir> &` — or background Bash tool) and annotated in state.json (`sentinel: {pid, threshold, started_at}`).
- [ ] **Calibration**: `usage_ledger.capacity_est` with the best available data (real cuts observed on this workstation; without data, conservative default 1.2M).
- [ ] **Between tasks**: check `.swarm/STOP_REQUESTED.json` and the next-step reservation.
- [ ] **On `SENTINEL-STOP`**: stop of `controlled-stop.md` §3 + OPT-IN scheduled task (§4) + prompt on screen (§5).
- [ ] **At close**: the sentinel retires by itself when `mission_status` changes; cancel the scheduled task if left alive. **Zero persistent OS processes to uninstall** — the sentinel dies with the session, and the one-shot resume task is explicit opt-in.
