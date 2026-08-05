#!/usr/bin/env node
// nudge-verify.mjs — Forge — K5 verification nudge.
//
// Deterministic check behind the "verification = execution" nudge (Rule 1,
// feature K5): before a validator/smoke step runs, the orchestrator (or the
// headless driver) must have executed a NON-TRIVIAL real command. This script
// inspects an implementor report's commands_run (or a state.json subset) and
// answers: is there real executed evidence, or only trivial file-existence
// checks?
//
// The anti-trivial pattern mirrors gate-check.mjs (authoritative — if the
// gate's TRIVIAL regex changes, mirror it here). Duplication is intentional:
// the nudge must work standalone, before the gate runs.
//
// Usage:
//   node nudge-verify.mjs <report.json> [--schema-limit N]
// Exit codes:
//   0  OK — at least one non-trivial executed command found
//   1  NUDGE — no non-trivial command executed yet: RUN a real command first
//   2  error — unreadable/malformed input
// Stdout: single-line JSON {"ok":true|false,"commands":N,"nontrivial":M,"trivial":[...]}
//
// Non-trivial = command that does not match the trivial pattern AND produces
// observable output (the orchestrator runs it, captures output, and includes
// the excerpt in evidence — the schema enforces output_excerpt on PASS).

import { readFileSync } from 'node:fs';

const TRIVIAL = /^\s*(grep|test\s+-[ef]|ls(\s|$)|wc(\s|$)|cat\s+[^|]*$)/;

const [reportPath] = process.argv.slice(2);
if (!reportPath) {
  console.error('usage: nudge-verify.mjs <report.json>');
  process.exit(2);
}

let commands = [];
try {
  const data = JSON.parse(readFileSync(reportPath, 'utf8'));
  if (Array.isArray(data.commands_run)) commands = data.commands_run;
  else if (Array.isArray(data.tests)) {
    commands = data.tests
      .filter((t) => t.evidence && t.evidence.command)
      .map((t) => t.evidence);
  } else if (Array.isArray(data.criteria_results)) {
    commands = data.criteria_results
      .filter((c) => c.evidence && c.evidence.command)
      .map((c) => c.evidence);
  }
} catch (e) {
  console.error(`nudge-verify: unreadable report ${reportPath}: ${e.message}`);
  process.exit(2);
}

const trivial = commands
  .filter((c) => TRIVIAL.test(c.command))
  .map((c) => c.command);
const nontrivial = commands.filter((c) => !TRIVIAL.test(c.command));

const out = {
  ok: nontrivial.length > 0,
  commands: commands.length,
  nontrivial: nontrivial.length,
  trivial: trivial.slice(0, 5),
};
console.log(JSON.stringify(out));
process.exit(out.ok ? 0 : 1);
