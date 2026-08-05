# Controlled Stop and Resumption — Forge

> **Single source** of the stop protocol (human and automatic), the canonical resume prompt and disk reconciliation. Three consumers share this document: the Operator stop (§2), the usage-limit auto-stop (§3) and the **usage sentinel** (§3.3 and [`usage-sentinel.md`](usage-sentinel.md)).
>
> ⚠️ **v1.0 — the external watchdog is RETIRED** (Operator order 2026-07-28). Its place is taken by a **Python sentinel inside the opencode session** (`usage-sentinel.py`, os-agnostic) that watches for free and stops at **93%**, plus an **experimental opt-in one-shot OS task** for automatic return — see `usage-sentinel.md`.

Born from the brain mission post-mortem (2026-07, 19 blocks): dry cuts by subscription limit left port zombies, eternally RUNNING workflows and a state.json that did not reflect the disk. The stop became a first-class act: **a well-stopped mission resumes in minutes; a dry-cut mission takes hours to rebuild.**

---

## §1 — Canonical mission states

`mission_status` only admits these values, in ALL skill files:

| State | Who writes it | Sentinel / resumption (v1.0) |
|--------|------------------|-------------------------------|
| `RUNNING` | The Orchestrator during the mission (heartbeat `updated_at` pre/post each long step) | The sentinel watches (background process, threshold 93%) |
| `PAUSED_BY_OPERATOR` | Controlled stop requested by the Operator (§2) | **Resumption ONLY manual** with the §4 prompt. The sentinel retires by itself; if there was a scheduled resume, it is cancelled |
| `PAUSED_USAGE_LIMIT` | Preventive auto-stop at 93% (§3), by the sentinel (§3.3) or by the ledger reservation (§3.2) | **OPT-IN one-shot OS task** at `window_reset_at + 5 min` with the §4 prompt (`usage-sentinel.md` §4). Without observed `window_reset_at` → nothing is scheduled: manual resumption |
| `INTERRUPTED_RATE_LIMIT` | Reactive best-effort marker: the limit caught the mission working and there was still time to write it | Same as `PAUSED_USAGE_LIMIT` if the reset time is known; otherwise manual |
| `COMPLETE` / `COMPLETE_WITH_PENDING` / `PARTIAL` | The gate (`gate-check.mjs`) at close | Nothing to do: the sentinel retires on seeing the state change |

Mnemonic rule: **`PAUSED_BY_OPERATOR` = human decision → the human resumes. `PAUSED_USAGE_LIMIT` = technical limit → the scheduled task may resume, and the on-screen prompt is always plan B.**

## §2 — Controlled stop by the Operator

**Canonical trigger:** the Operator writes **"para de forma controlada"** (or equivalent: "controlled stop", "pausa la misión", "stop controlado"). Thanks to the free main thread (mission-mode.md, Pillar 4) the message is processed as soon as the main loop consolidates the step in progress — never hours of waiting.

The Orchestrator executes IN THIS ORDER:

1. **Freeze the front**: launch nothing new. Background agents: if within <2 min of finishing, wait and consolidate their result; otherwise stop them (task cancellation) and annotate the task as unclosed.
2. **Kill the registered processes**: for each `live_processes[]` entry with `status: "RUNNING"` → `kill <pid>` → verify → `kill -9` if it resists → mark `status: "KILLED"`. **PROHIBITED to kill blindly by port** (lesson: Cerberus's backend was almost killed sweeping a "known" port): only PIDs registered by THIS mission are touched; the port serves only to verify it is free.
3. **Full checkpoint**: capture real `disk_facts` of the task in progress (git status + git log, not the agent's self-report), write the complete `pause_context{}` (format below), `mission_status: "PAUSED_BY_OPERATOR"` and `updated_at`.
4. **Retire the sentinel and clean the resumption**: the sentinel (background process) retires by itself as soon as it sees `mission_status` stop being `RUNNING` — nothing to uninstall. If a scheduled resume `swarm-resume-<project>` remained from a previous pause, cancel it (`usage-sentinel.md` §4). Annotate `pause_context.sentinel: "RETIRED"`.
5. **Render artifacts**: `node scripts/render-artifacts.mjs` — the .md files reflect the pause.
6. **Present the resume prompt in the chat** (§4), filled with real data, and persist it also in `pause_context.resume_prompt`. The prompt is self-contained: it works in that same chat or pasted into a completely new one.

**`pause_context{}` format** (canonizes the one used in the brain mission):

```jsonc
"pause_context": {
  "at": "2026-07-15T04:14:32Z",
  "reason": "Operator disconnects the laptop",            // or "5h window at 93.3%"
  "stopped_by": "operator",                               // "operator" | "auto_usage" | "rate_limit"
  "resume_block": "B03",
  "resume_task": "F1-T3",
  "sentinel": "RETIRED",                                  // retires by itself on state change
  "scheduled_resume": "swarm-resume-vetinari @ 2026-07-28T06:15:00+02:00",  // or null if not scheduled
  "repo_clean_head": "71b7276 (B01+B02 pushed, compiles green)",
  "partial_untracked": "model/adapter/ of F1-T3 (incomplete: decide continue or redo)",
  "resume_prompt": "Reconcile from disk: ..."             // the filled §4 prompt
}
```

## §3 — Preventive auto-stop by usage limit

The dry cut of the client is the NORMAL case of the subscription limit — the `INTERRUPTED_RATE_LIMIT` marker almost never gets written. The design avoids it by **not reaching the cut**:

- The **sentinel** (`usage-sentinel.md`) watches continuously and free; the Orchestrator also checks **between tasks** (after consolidating one, before launching the next — never mid-step):
  ```bash
  test -f .swarm/STOP_REQUESTED.json && echo "STOP REQUESTED BY THE SENTINEL"   # double lock
  node <skill>/scripts/usage-probe.mjs .swarm/state.json     # exit 0 = continue · exit 2 = stop
  ```
- **Exit 2 (STOP) or sentinel flag**: some window ≥ threshold (**93%** — the remaining 7% is the real margin to execute this stop). The SAME §2 procedure executes with three differences: `mission_status: "PAUSED_USAGE_LIMIT"`, `stopped_by: "auto_usage"`, and the on-screen prompt indicates **when the window resets** (`window_reset_at`). Additionally the **resumption is scheduled** as an opt-in one-shot OS task if there is an observed reset time (`usage-sentinel.md` §4); the on-screen prompt is always plan B.
- **Exit 0 with `decision: "UNKNOWN"`** (nothing measurable): FAIL-OPEN — the warning is noted in `notes[]` and the mission **continues**. Never stop on a false alarm; the reactive marker and the expired heartbeat stay as backup in case the limit really arrives.
- Each reading is registered in `usage{}` of state.json: `{"last_check_at": "...", "max_utilization": 54.0, "threshold": 93}`.

## §3.1 — CRITICAL blind spot: big background cycles (plan v5 post-mortem, 2026-07-18)

> **Hard lesson.** During the whole plan v5 mission the team **never managed to execute a single auto-stop on its own**: the limit cut dry again and again and it was the Operator who asked for the stop. The cause was NOT the probe (it measures well) but **WHERE it runs**.

The §3 protocol says "run the probe BETWEEN tasks". That assumes each task consumes a **small fraction** of the window. **A monolithic phase-cycle script breaks that premise**: it is ONE main-loop task that internally launches dozens of agents and consumes **millions of tokens** in background (measured: one Phase 4 block spent **5.7M tokens** in a single run). The Orchestrator does not regain control until it ends — and by then the window already burst and the client cut the whole session (main loop included), with no stop opportunity.

**Rules so the auto-stop really works** (mandatory in Mission Mode):

1. **Probe BEFORE launching each background cycle/block** — not only "between tasks". A phase-cycle script is not a bounded step: it is an opaque token sink. Probe right before.
2. **Enough margin for the ESTIMATED cost of the block**, not just `< 93%`. If the cycle you are about to launch can spend ~2-5M tokens and the window is at 85%, **it does not fit** → controlled stop NOW (§3), not later. Practical rule: estimate the block cost (number of agents × observed average cost) and compare with the margin; in doubt, do not launch.
3. **Cap the cycle with a budget**: pass a token objective so it self-stops and returns control BEFORE exhausting the window, instead of running blind.
4. **Prefer small steps in long missions**: the **canonical mode** (mission-mode.md Pillar 2 — one implementor per task in background + Orchestrator validation) gives frequent control points where the probe CAN stop in time. 50-70 agent cycles are the **anti-pattern** for usage control: maximum opacity, maximum consumption per step. Use them only with a loose window margin and an estimated cost that fits entirely.
5. **If the cut arrives anyway** (cycle that exceeded the estimate): it is a dry cut → the next session reconciles from disk (§5). That is why the per-task checkpoint and `disk_facts` are non-negotiable: they are the only net when the auto-stop does not fire.

> Summary: the preventive auto-stop **only protects steps whose cost fits in the remaining margin**. A massive cycle launched without probing before nor capping its budget is, by design, immune to the auto-stop — and it was exactly the repeated failure mode of that mission.

## §3.2 — Self-accounting window ledger (works WITHOUT OAuth)

> **brain mission post-mortem (2026-07-20, 4 identical dry cuts):** in ALL cuts `check-usage.py` was in FAIL-OPEN (expired OAuth token) and the team advanced blind to the hard cut. The OAuth probe cannot be the only defense. v3.3 added a source of truth that is ALWAYS available: **the harness reports the tokens of each subagent** (`subagent_tokens` in each task notification) and **limit errors say the exact reset time** ("You've hit your session limit · resets 1:10am").

The Orchestrator keeps in state.json a **window ledger**:

```jsonc
"usage_ledger": {
  "window_reset_at": "2026-07-20T01:10:00+02:00",   // parsed from the LAST limit error seen
  "window_started_at": "2026-07-20T01:10:00+02:00", // = previous reset (the window starts there)
  "spent_tokens": 412000,                           // sum of subagent_tokens + main loop estimate
  "capacity_est": 1200000,                          // estimated window capacity (self-calibrated)
  "calibrations": [                                 // each hard cut IS calibration data
    {"at": "2026-07-19T21:04:00Z", "observed_spend_at_cut": 1310000}
  ]
}
```

**The 7 ledger rules (mandatory in Mission Mode):**

1. **ALWAYS account**: on consolidating each agent/cycle notification, add its `subagent_tokens` to `spent_tokens` (+~30k per own consolidation turn of the main loop, conservative estimate). Persisted with the heartbeat — zero cost, zero dependencies.
2. **Reserve before launching**: each step type has an estimated cost (indicative table, calibratable with the mission's own data: background implementor **~250k** (measured in vetinari: 160k–365k), 1-phase cycle **~500k**, Orchestrator validation/smoke **~60k**, verify/build in Bash **~0**). Before launching: if `spent + reservation > 0.93 × capacity_est` → **do NOT launch**; execute the §3 stop (`PAUSED_USAGE_LIMIT`). The step reservation counts INSIDE that 93%, so the stop happens before starting something that does not fit — better stop one step earlier than die mid-way.
3. **Calibration at each cut**: if despite everything a hard cut arrives, `observed_spend_at_cut` (the accumulated spend at that moment) goes to `calibrations[]` and `capacity_est = 0.9 × median(observations)`. The skill learns the real subscription capacity of the workstation in 1-2 cuts; conservative initial default: **1.2M**.
4. **Fire drill at the first symptom**: the FIRST notification of a dead agent with limit/credits error fires the IMMEDIATE reactive protocol — (a) parse `resets HH:MM` → `window_reset_at`; (b) calibrate (rule 3); (c) relaunch NOTHING, retry NOTHING; (d) full checkpoint + `mission_status: "INTERRUPTED_RATE_LIMIT"`; (e) end the turn cleanly in that same message. Every token spent after the first symptom is burned margin.
5. **Window reset**: on resuming after `window_reset_at`, `spent_tokens` returns to 0 and `window_started_at = window_reset_at`. If the resumption arrives mid-window (e.g. scheduled resumption minutes after a freed weekly cut), the known spend is kept.
6. **`window_reset_at` ONLY from real signals (lesson brain 2026-07-20)**: the window belongs to the **ACCOUNT, not the session** — it starts with the Operator's first request in that window (which may be another chat or another workstation), so `window_started_at + 5h` is an INVALID estimate that can delay the relaunch by hours. `window_reset_at` is only written if it comes from a real signal — the parsed "resets HH:MM" of a limit error — and `window_reset_source: "observed"` is annotated. **Without a real signal → `window_reset_at: null`** and NO resumption is scheduled blind: the on-screen prompt is the path (`usage-sentinel.md` §4). The ledger remains useful regardless: it measures THE MISSION's spend, which is a minimum of the account's spend — if the mission alone already touches the threshold, the account is worse; stopping is still correct. `capacity_est` is interpreted as "mission budget per window", not as the exact subscription capacity.
7. **The resume prompt ALWAYS on screen**: every stop — human (§2), usage (§3) or ledger (§3.2) — ENDS by presenting the filled §4 prompt in the chat, as a copyable code block, IN ADDITION to persisting it in `pause_context.resume_prompt`. Even when there is a scheduled resumption: the on-screen prompt is the Operator's plan B if the automatic relaunch does not arrive or he wants to advance it by hand. A pause without a prompt in the chat is an INCOMPLETE pause.

**Signal priority** (defense in depth): usage-probe with valid external meter (measures for real) → **ledger** (always available) → reactive fire-drill marker (rule 4) → disk checkpoint for the next session (last net). The mission uses the best signal available at each moment, never none.

## §3.3 — The usage sentinel (replaces the external watchdog)

Continuous watch is done by the **sentinel**: a background process running `scripts/usage-sentinel.py` (Python stdlib — Linux/macOS/Windows), costing **zero tokens** while silent, and at **93%** writing `.swarm/STOP_REQUESTED.json` and emitting one `SENTINEL-STOP` line. The Orchestrator **executes** the stop (§3): the sentinel only alarms, so it does not compete for `state.json`.

Full mechanism, launch, threshold, scheduled resumption and checklist:
**[`usage-sentinel.md`](usage-sentinel.md)** — mandatory reading when assembling a mission.

## §4 — Canonical resume prompt

Template (the Orchestrator fills it with real values; the scheduled OS task embeds a copy):

```text
Reconcile from disk: you are resuming the Forge mission "<mission>" in <project_dir>.
BEFORE trusting <project_dir>/.swarm/state.json:
1. git status + git log --oneline -5 in <project_dir>; compare with the disk_facts of the
   last task and with pause_context.repo_clean_head / partial_untracked.
2. Review live_processes[] of state.json: ps -p <pids>; kill ONLY the registered ones that
   are still alive (PROHIBITED to kill by port blindly) and mark them KILLED.
3. If there are open workflow_runs[], review their journal before deciding to resume.
4. Correct state.json with what the DISK says — the disk is the source of truth, not any
   agent's self-report.
Then: read the forge skill (SKILL.md + references/mission-mode.md +
references/controlled-stop.md), set mission_status=RUNNING and updated_at=now, relaunch the
usage sentinel (python3 <skill>/scripts/usage-sentinel.py <project_dir> — usage-sentinel.md §1),
and continue from <resume_block>/<resume_task> in canonical mode: one implementor per task
in background + validation/smoke/panel executed by you with real evidence + checkpoint
after each task. Watch usage between tasks (flag .swarm/STOP_REQUESTED.json of the sentinel +
usage-probe.mjs + the 93% ledger reservation): if any fires, execute the preventive auto-stop
(controlled-stop.md §3). If the Operator writes "para de forma controlada", execute the
controlled stop of controlled-stop.md §2.
```

Prompt rules:
- **Always starts with "Reconcile from disk:"** — the contract with the scheduled resumption and with any new session.
- Presented in the chat **as a code block** to copy/paste as-is.
- In usage stops (§3), append the line:
  `The window resets at <window_reset_at> — paste this prompt from that time on.`

## §5 — Mandatory reconciliation protocol (every start/resume)

Steps 1-4 of §4 are **mandatory on EVERY resumption or start over an existing state.json**, whatever its origin (pasted prompt, scheduled task, new session after compaction). The brain post-mortem proved it: after each cut, the work applied on disk (migrated pom, intact migrations) was NOT reflected in state.json — trusting the JSON would have repeated or overwritten good work.

Additionally, **`disk_facts` is the source of truth per task**: when consolidating each task, the Orchestrator captures them HIMSELF with git (`git rev-parse HEAD`, `git status --porcelain`, list of touched files) and persists them next to the phase status:

```jsonc
"disk_facts": {
  "commit": "71b7276",
  "files_created": ["backend/src/main/java/.../TraceService.java"],
  "files_modified": ["backend/pom.xml"],
  "untracked": [],
  "captured_at": "2026-07-14T22:58:35Z"
}
```

The agent's self-report (`implementor_result.changes`) is advisory — like everything in v3.

## §6 — Process hygiene (`live_processes[]`)

Every smoke/step that starts a server (Java backend, docker, http.server...) fulfills this contract — without it, each cut sows zombies occupying ports and confusing the next session:

1. **Register BEFORE using**: as soon as the process starts, add to `live_processes[]`:
   ```jsonc
   { "pid": 12345, "port": 8087, "command": "mvn spring-boot:run",
     "purpose": "smoke F1-T3", "phase_id": "F1", "started_at": "...", "status": "RUNNING" }
   ```
2. **Kill when the step ends** (not at block end): `kill` → verify → mark `KILLED`.
3. **On resume**: sweep ONLY the registered PIDs (§4 step 2). A process on the expected port with an UNREGISTERED PID is NOT touched: it may belong to another project (Cerberus lesson).
4. **The gate verifies it**: `gate-check.mjs` Check 10 (mission) — the mission does not close with `RUNNING` entries in `live_processes[]`.
