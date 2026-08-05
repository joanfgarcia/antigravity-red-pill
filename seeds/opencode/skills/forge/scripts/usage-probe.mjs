#!/usr/bin/env node
// usage-probe.mjs — Forge — Usage probe (0 tokens).
//
// Provider-agnostic replacement for check-usage.py (Claude-only OAuth probe).
// Primary signal: the self-accounting window ledger persisted in state.json
// (usage_ledger.spent_tokens / capacity_est). Always available: pure disk read,
// no network, no OAuth. Optional secondary signal: an external hook command
// (SWARM_USAGE_HOOK) that prints utilization JSON — lets operators plug a real
// provider meter (e.g. an opencode server /usage endpoint) without changing
// the probe.
//
// Contract with the orchestrator (exit codes — identical to check-usage.py):
//   0  CONTINUE — margin available, or FAIL-OPEN (nothing measurable → decision
//      "UNKNOWN"). Never stop on false alarms; log the warning instead.
//   2  STOP     — worst observed utilization >= threshold (default 93).
//   1  reserved: invocation error (bad args).
// Stdout: single-line JSON:
//   {"decision":"CONTINUE|STOP|UNKNOWN","max_utilization":71.2,"threshold":93,
//    "windows":{"ledger":{"utilization":71.2},"hook":{...}},"reason":"..."}
//
// Usage:
//   node usage-probe.mjs [path/to/state.json] [--threshold N]

import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const THRESHOLD = 93;
const args = process.argv.slice(2);
let statePath = args.find((a) => !a.startsWith('--')) || '.swarm/state.json';
const thresholdArg = args.indexOf('--threshold');
const threshold = thresholdArg >= 0 ? Number(args[thresholdArg + 1]) : (process.env.SWARM_USAGE_THRESHOLD ? Number(process.env.SWARM_USAGE_THRESHOLD) : THRESHOLD);

const windows = {};
let reason = '';

// ── Signal 1: window ledger (always available) ───────────────────────────────
function readLedger(path) {
  try {
    const st = JSON.parse(readFileSync(path, 'utf8'));
    const led = st.usage_ledger || {};
    const spent = led.spent_tokens || 0;
    const cap = led.capacity_est;
    if (cap) {
      windows.ledger = { utilization: Math.round((100 * spent) / cap * 10) / 10, spent_tokens: spent, capacity_est: cap, window_reset_at: led.window_reset_at || null };
    } else {
      reason += 'ledger: no capacity_est; ';
    }
  } catch (e) {
    reason += `ledger: unreadable (${e.message}); `;
  }
}

// ── Signal 2: external hook (best-effort, fail-open) ─────────────────────────
function readHook() {
  const hook = process.env.SWARM_USAGE_HOOK;
  if (!hook) return;
  try {
    const out = execFileSync('sh', ['-c', hook], { encoding: 'utf8', timeout: 45000, stdio: ['ignore', 'pipe', 'ignore'] });
    const line = out.split('\n').find((l) => l.trim().startsWith('{'));
    if (!line) { reason += 'hook: no JSON line; '; return; }
    const j = JSON.parse(line);
    if (typeof j.max_utilization === 'number') {
      windows.hook = { utilization: j.max_utilization, window_reset_at: j.window_reset_at || null };
    } else {
      reason += 'hook: no max_utilization; ';
    }
  } catch (e) {
    reason += `hook: failed (${e.message}); `;
  }
}

readLedger(statePath);
readHook();

const cands = Object.values(windows).map((w) => w.utilization).filter((u) => typeof u === 'number');
let decision, maxUtil;
if (cands.length === 0) {
  decision = 'UNKNOWN'; maxUtil = null;
  reason += 'no signal measurable — FAIL-OPEN, continue and log.';
} else {
  maxUtil = Math.max(...cands);
  decision = maxUtil >= threshold ? 'STOP' : 'CONTINUE';
}

console.log(JSON.stringify({ decision, max_utilization: maxUtil, threshold, windows, reason: reason.trim() }));
process.exit(decision === 'STOP' ? 2 : 0);