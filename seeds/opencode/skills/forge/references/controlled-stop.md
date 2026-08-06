# Controlled Stop and Resumption — Forge

> **Single source** of the stop protocol, the canonical resume prompt and disk reconciliation. Three consumers share this document: the Operator stop (§2), the canonical resume prompt (§4) and the reconciliation protocol (§5).

Born from real mission post-mortems: dry cuts by subscription limit left port zombies, eternally RUNNING workflows and a state.json that did not reflect the disk. The stop became a first-class act: **a well-stopped mission resumes in minutes; a dry-cut mission takes hours to rebuild.**

---

## §1 — Canonical mission states

`mission_status` only admits these values, in ALL skill files:

| State | Who writes it | Resumption |
|--------|------------------|-----------|
| `RUNNING` | The Orchestrator during the mission (heartbeat `updated_at` pre/post each long step) | — |
| `PAUSED_BY_OPERATOR` | Controlled stop requested by the Operator (§2) | **Resumption ONLY manual** with the §4 prompt |
| `INTERRUPTED_RATE_LIMIT` | Reactive best-effort marker: the limit caught the mission working and there was still time to write it | Manual, or after the window reset |
| `COMPLETE` / `COMPLETE_WITH_PENDING` / `PARTIAL` | The gate (`gate-check.mjs`) at close | Nothing to do |

> **Runtime death vs. protocol stop.** When a mission runs through the red-pill Job Manager, a dry cut by subscription/API limit does NOT kill the protocol: the job's checkpoint (`checkpoint_data`) is persisted in the queue DB after every step, so the job is resumable from the exact step regardless of what the session window did. The job-monitor (kernel) detects stuck/frustrated jobs by timeout and heartbeat; the job is requeued or reported — the state machine above only covers what the protocol itself records.

## §2 — Controlled stop by the Operator

**Canonical trigger:** the Operator writes **"para de forma controlada"** (or equivalent: "controlled stop", "pausa la misión", "stop controlado"). Thanks to the free main thread (mission-mode.md, Pillar 4) the message is processed as soon as the main loop consolidates the step in progress — never hours of waiting.

The Orchestrator executes IN THIS ORDER:

1. **Freeze the front**: launch nothing new. Background agents: if within <2 min of finishing, wait and consolidate their result; otherwise stop them (task cancellation) and annotate the task as unclosed.
2. **Kill the registered processes**: for each `live_processes[]` entry with `status: "RUNNING"` → `kill <pid>` → verify → `kill -9` if it resists → mark `status: "KILLED"`. **PROHIBITED to kill blindly by port** (lesson: a teammate's backend was almost killed sweeping a "known" port): only PIDs registered by THIS mission are touched; the port serves only to verify it is free.
3. **Full checkpoint**: capture real `disk_facts` of the task in progress (git status + git log, not the agent's self-report), write the complete `pause_context{}` (format below), `mission_status: "PAUSED_BY_OPERATOR"` and `updated_at`. If the mission runs as a job, also write the job checkpoint (`job_manager_api.job_checkpoint`) so the driver resumes from the exact step.
4. **Render artifacts**: `node scripts/render-artifacts.mjs` — the .md files reflect the pause.
5. **Present the resume prompt in the chat** (§4), filled with real data, and persist it also in `pause_context.resume_prompt`. The prompt is self-contained: it works in that same chat or pasted into a completely new one.

**`pause_context{}` format**:

```jsonc
"pause_context": {
  "at": "2026-07-15T04:14:32Z",
  "reason": "Operator disconnects the laptop",
  "stopped_by": "operator",
  "resume_block": "B03",
  "resume_task": "F1-T3",
  "job_id": "a1b2c3d4",                               // if running via job-manager (resume with job_resume)
  "repo_clean_head": "71b7276 (B01+B02 pushed, compiles green)",
  "partial_untracked": "model/adapter/ of F1-T3 (incomplete: decide continue or redo)",
  "resume_prompt": "Reconcile from disk: ..."         // the filled §4 prompt
}
```

## §3 — Preventive stop by usage/rate limit

The protocol does not run a custom token-watch: missions that run through the red-pill Job Manager are covered by the kernel's own mechanisms —

- **Per-step checkpoint** (`checkpoint_data` in the queue DB, persisted after every step): a dry cut never loses the mission — the job resumes from the exact step.
- **Per-step timeout** (`compute_step_timeout`, adaptive): a hung step is aborted as a scope and the job retries or is reported.
- **Job-monitor** (kernel): detects `PROCESSING` jobs without heartbeat (stuck) and `FRUSTRATED` jobs (circuit breaker) and surfaces them as signals; the runner's `requeue_stale` recovers stale PROCESSING to PENDING.

When the mission DOES observe a rate limit mid-flight (a dead agent with limit/credits error), the Orchestrator:

1. Parses `resets HH:MM` from the error, if present, and records it in the pause context for manual resumption timing.
2. Relaunches NOTHING and retries NOTHING in the same turn (every token after the first symptom is burned margin).
3. Full checkpoint + `mission_status: "INTERRUPTED_RATE_LIMIT"` (or `PAUSED_BY_OPERATOR`), and ends the turn cleanly with the §4 prompt.
4. If the mission runs as a job, the job remains PENDING/recoverable — no extra action needed: the runner retries at the next tick, or `job resume` when the window is known to have reset.

## §4 — Canonical resume prompt

Template (the Orchestrator fills it with real values; if a job is involved, it embeds the `job resume` step):

```text
Reconcile from disk: you are resuming the Forge mission "<mission>" in <project_dir>.
BEFORE trusting <project_dir>/.cell/state.json:
1. git status + git log --oneline -5 in <project_dir>; compare with the disk_facts of the
   last task and with pause_context.repo_clean_head / partial_untracked.
2. Review live_processes[] of state.json: ps -p <pids>; kill ONLY the registered ones that
   are still alive (PROHIBITED to kill by port blindly) and mark them KILLED.
3. If there are open workflow_runs[], review their journal before deciding to resume.
4. Correct state.json with what the DISK says — the disk is the source of truth, not any
   agent's self-report.
Then: read the forge skill (SKILL.md + references/mission-mode.md +
references/controlled-stop.md), set mission_status=RUNNING and updated_at=now,
and continue from <resume_block>/<resume_task> in canonical mode: one implementor per task
in background + validation/smoke/panel executed by you with real evidence + checkpoint
after each task. If the mission runs as a job: `job_manager_api.job_resume <job_id>` first,
then continue from the driver's checkpoint. If the Operator writes "para de forma
controlada", execute the controlled stop of controlled-stop.md §2.
```

Prompt rules:
- **Always starts with "Reconcile from disk:"** — the contract with the resumption and with any new session.
- Presented in the chat **as a code block** to copy/paste as-is.

## §5 — Mandatory reconciliation protocol (every start/resume)

Steps 1-4 of §4 are **mandatory on EVERY resumption or start over an existing state.json**, whatever its origin (pasted prompt, scheduled task, new session after compaction). Real post-mortems proved it: after each cut, the work applied on disk (migrated pom, intact migrations) was NOT reflected in state.json — trusting the JSON would have repeated or overwritten good work.

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
3. **On resume**: sweep ONLY the registered PIDs (§4 step 2). A process on the expected port with an UNREGISTERED PID is NOT touched: it may belong to another project (lesson: a teammate's backend was almost killed sweeping a "known" port).
4. **The gate verifies it**: `gate-check.mjs` Check 10 (mission) — the mission does not close with `RUNNING` entries in `live_processes[]`.
