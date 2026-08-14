#!/usr/bin/env node
// cycle-run.mjs — Forge — headless L2 burst driver.
//
// Short-burst executor for L2 (escalation.md): runs the phase cycle OUTSIDE
// the main loop via cold-context `opencode run --agent <role> --auto`
// invocations, so the orchestrator's context stays unpolluted. Each role
// receives its fully-packed prompt from the burst manifest (cold context
// inherits nothing) and writes its schema-conforming JSON to
// .cell/reports/<role>-<phase>.json.
//
// ONLY for short bursts (1 phase, <=10 estimated agent calls). Long missions
// use canonical mode in the main loop (mission-mode.md Pillar 2) — a massive
// cycle is an opaque token sink immune to the auto-stop (controlled-stop.md
// §3.1). Budget/usage guards run between steps.
//
// Usage:
//   node cycle-run.mjs <burst-manifest.json> [--max-calls N] [--no-validate]
//
// MODE (v1.3.0): the canonical path is the JOB MANAGER.
//   --job-manager --mission <id>   → enqueue the whole burst as a `forge_job`
//     (resumable, transferable control) and poll job status to completion.
//   Without flags → legacy direct mode (spawnSync opencode run per step) kept
//     as fallback, but deprecated: the Operator wants every headless launch to
//     go through the Centralized Job Manager.
//
// Exit codes: 0 = cycle complete (all steps done, reports validated)
//             1 = a step failed (report invalid or agent error) — see log
//             3 = budget: --max-calls reached
//             4 = manifest error / missing workdir
//             5 = job-manager mode: job FAILED / FRUSTRATED
//             6 = job-manager mode: job PAUSED by operator (resume with job resume)

import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync, mkdirSync, unlinkSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SKILL_DIR = resolve(fileURLToPath(new URL('.', import.meta.url)));
const MAX_CALLS_DEFAULT = 10;
const TIMEOUT_MS = 15 * 60 * 1000;
const POLL_STEP_MS = 5000;
const POLL_MAX_MS = 24 * 60 * 60 * 1000;

const args = process.argv.slice(2);
const manifestPath = args.find((a) => !a.startsWith('--')) || '.cell/burst.json';
let maxCalls = MAX_CALLS_DEFAULT;
{
  const i = args.indexOf('--max-calls');
  if (i !== -1) maxCalls = parseInt(args[i + 1], 10) || MAX_CALLS_DEFAULT;
  const eq = args.find((a) => a.startsWith('--max-calls='));
  if (eq) maxCalls = parseInt(eq.split('=')[1], 10) || MAX_CALLS_DEFAULT;
}
const useJobManager = args.includes('--job-manager');
const missionId = (() => {
  const i = args.indexOf('--mission');
  if (i !== -1) return args[i + 1];
  const eq = args.find((a) => a.startsWith('--mission='));
  return eq ? eq.split('=')[1] : null;
})();
const backend = (() => {
  const i = args.indexOf('--backend');
  if (i !== -1) return args[i + 1];
  const eq = args.find((a) => a.startsWith('--backend='));
  return eq ? eq.split('=')[1] : 'opencode';
})();
const model = (() => {
  const i = args.indexOf('--model');
  if (i !== -1) return args[i + 1];
  const eq = args.find((a) => a.startsWith('--model='));
  return eq ? eq.split('=')[1] : null;
})();
const effort = (() => {
  const i = args.indexOf('--effort');
  if (i !== -1) return args[i + 1];
  const eq = args.find((a) => a.startsWith('--effort='));
  return eq ? eq.split('=')[1] : null;
})();

let manifest;
try {
  manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
} catch (e) {
  console.error(`cycle-run: unreadable manifest ${manifestPath}: ${e.message}`);
  process.exit(4);
}
const workdir = resolve(manifest.workdir || process.cwd());
if (!existsSync(workdir)) {
  console.error(`cycle-run: workdir does not exist: ${workdir}`);
  process.exit(4);
}
const reportsDir = join(workdir, '.cell', 'reports');
mkdirSync(reportsDir, { recursive: true });

const log = (msg) => console.log(`[cycle-run] ${msg}`);

// ── JOB MANAGER MODE (canonical since v1.3.0) ───────────────────────────────
if (useJobManager) {
  if (!missionId) {
    console.error(`cycle-run: --job-manager requires --mission <id> (isolation between forges)`);
    process.exit(4);
  }
  const payload = {
    mission_id: missionId,
    manifest: { workdir, phases: manifest.phases || [] },
  };
  if (model) payload.model = model;
  if (effort) payload.effort = effort;
  payload.backend = backend;
  payload.timeout = Math.round(TIMEOUT_MS / 1000);

  const submit = spawnSync(
    'red-pill', ['job', 'submit', '--source', 'forge_job', '--payload', JSON.stringify(payload), '--mission', missionId],
    { encoding: 'utf8', timeout: 30000 },
  );
  if (submit.status !== 0) {
    console.error(`cycle-run: job submit failed:\n${submit.stderr || submit.stdout}`);
    process.exit(4);
  }
  // enqueue_task generates uuid4 WITH dashes (queue_manager.py) — a bare
  // 32-hex regex never matches and this mode dies with exit 4.
  const jobMatch = /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i.exec(submit.stdout || '');
  if (!jobMatch) {
    console.error(`cycle-run: could not parse job id from:\n${submit.stdout}`);
    process.exit(4);
  }
  const jobId = jobMatch[1];
  log(`forge_job encolado: ${jobId} (mission=${missionId}). Polling job status...`);

  const start = Date.now();
  while (Date.now() - start < POLL_MAX_MS) {
    const status = spawnSync('red-pill', ['job', 'status', jobId], { encoding: 'utf8', timeout: 30000 });
    if (status.status !== 0) {
      log(`job status call failed (rc=${status.status}) — retrying`);
    } else {
      let row;
      // The CLI prints json.dumps(task, indent=2): a multi-line block whose
      // first '{' line is just "{" — parse from the first brace to the end.
      try {
        const brace = status.stdout.indexOf('{');
        row = brace >= 0 ? JSON.parse(status.stdout.slice(brace)) : null;
      } catch { row = null; }
      const st = row?.status || '';
      const progress = row?.progress || {};
      log(`  ${jobId.slice(0, 8)} → ${st}${progress.current ? ` (${progress.current}/${progress.total})` : ''}`);
      if (st === 'COMPLETED') { log(`cycle complete via job ${jobId.slice(0, 8)}`); process.exit(0); }
      if (st === 'FRUSTRATED' || st === 'FAILED') { console.error(`cycle-run: job ${jobId.slice(0, 8)} → ${st}`); process.exit(5); }
      if (st === 'PAUSED') { console.error(`cycle-run: job ${jobId.slice(0, 8)} PAUSED by operator — resume with 'red-pill job resume ${jobId.slice(0, 8)}'`); process.exit(6); }
      if (st === 'PROCESSING' && !row?.checkpoint && Date.now() - start > 6 * 3600 * 1000) {
        console.error(`cycle-run: job stuck (no progress for 6h)`); process.exit(5);
      }
    }
    spawnSync('sleep', [String(POLL_STEP_MS / 1000)], { stdio: 'ignore' });
  }
  console.error(`cycle-run: poll timeout`);
  process.exit(5);
}

// ── LEGACY DIRECT MODE (fallback, deprecated) ───────────────────────────────
log(`LEGACY direct mode (spawnSync opencode run) — deprecated since v1.3.0; prefer --job-manager --mission <id>`);
let calls = 0;

for (const phase of manifest.phases || []) {
  log(`phase ${phase.id}: ${phase.steps.length} steps`);
  for (const step of phase.steps || []) {
    if (calls >= maxCalls) {
      log(`budget reached (${maxCalls} calls) — exiting 3`);
      process.exit(3);
    }

    calls += 1;
    const reportPath = join(reportsDir, `${step.role}-${phase.id}.json`);
    log(`step ${calls}/${maxCalls}: ${step.role} (${step.agent}) → ${reportPath}`);
    rm(reportPath);

    const prompt = `${step.prompt}\n\nWrite your report to ${reportPath} conforming to your schema and finish.`;
    const res = spawnSync(
      'opencode', ['run', prompt, '--agent', step.agent, '--auto'],
      { cwd: workdir, encoding: 'utf8', timeout: TIMEOUT_MS, stdio: 'pipe' },
    );
    if (res.error) {
      log(`agent ${step.agent} could not run: ${res.error.message}`);
      process.exit(1);
    }
    if (res.status !== 0) {
      log(`agent ${step.agent} exited ${res.status} — tail of output:\n${(res.stdout || '').slice(-2000)}`);
      // INTERRUPTED (API/rate-limit death) is NOT an escalation: exit 1 lets
      // the orchestrator resume (escalation.md EXHAUSTED vs INTERRUPTED).
      process.exit(1);
    }

    const waited = waitForReport(reportPath);
    if (!waited) {
      log(`no report file appeared for ${step.role}/${phase.id} within ${POLL_MAX_MS / 60000} min — INTERRUPTED`);
      process.exit(1);
    }
    const valid = validateReport(step, reportPath);
    log(`report ${step.role}/${phase.id}: ${valid ? 'VALID' : 'INVALID (see validator output)'}`);
    if (!valid) process.exit(1);

    const nudge = nudgeStep(step, reportPath);
    if (nudge) log(`nudge (K5): ${nudge}`);
  }
}

log(`cycle complete — ${calls} agent calls, all reports valid`);
process.exit(0);

// ---------------------------------------------------------------------------

function rm(p) {
  // require() does not exist in ESM — the old version threw a swallowed
  // ReferenceError, so stale reports were never deleted and waitForReport
  // accepted them as fresh (anti-zero-trust).
  try { unlinkSync(p); } catch { /* ignore */ }
}

function waitForReport(reportPath) {
  const start = Date.now();
  while (Date.now() - start < POLL_MAX_MS) {
    if (existsSync(reportPath)) return true;
    spawnSync('sleep', ['1'], { stdio: 'ignore' });
  }
  return false;
}

function validateReport(step, reportPath) {
  const schemaName = {
    implementor: 'implementor_result.schema.json',
    validator: 'validator_verdict.schema.json',
    smoke_tester: 'smoke_report.schema.json',
    devils_advocate: 'devil_refutation.schema.json',
  }[step.role];
  if (!schemaName) return true; // no schema mapped → orchestrator decides
  const schemaPath = join(SKILL_DIR, '..', 'references', 'schemas', schemaName);
  const v = spawnSync('node', [join(SKILL_DIR, 'validate-report.mjs'), reportPath, schemaPath], { encoding: 'utf8' });
  if (v.status !== 0) log(v.stdout || v.stderr);
  return v.status === 0;
}

function nudgeStep(step, reportPath) {
  if (step.role !== 'implementor') return null;
  const n = spawnSync('node', [join(SKILL_DIR, 'nudge-verify.mjs'), reportPath], { encoding: 'utf8' });
  if (n.status !== 0) {
    return `implementor evidence is trivial/empty — orchestrator must run a REAL command before validation (Rule 1)`;
  }
  return null;
}
