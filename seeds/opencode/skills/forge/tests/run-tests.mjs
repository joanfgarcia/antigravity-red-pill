#!/usr/bin/env node
// run-tests.mjs — Self-test suite for the forge skill bundle (regression goldsets).
// Usage: node run-tests.mjs            (from anywhere; locates the bundle via import.meta.url)
// Exit code: 0 = all green, 1 = any failure.
//
// Coverage:
//   Phase A — schema contracts: 15 fixtures (9 schemas, valid+invalid) via validate-report.mjs.
//   Phase B — deterministic gate: 5 state goldsets, one per violation family (checks 1-10).
//   Phase C — triage plan: 3 fixtures (2 valid + recommendation, 1 invalid).

import { readFileSync, writeFileSync, mkdirSync, rmSync, readdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join, dirname } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

const BUNDLE = join(dirname(fileURLToPath(import.meta.url)), '..');
const SCRIPTS = join(BUNDLE, 'scripts');
const SCHEMAS = join(BUNDLE, 'references', 'schemas');
const GOLD = join(BUNDLE, 'tests', 'goldsets');
const TMP = join(tmpdir(), 'forge-skill-tests');

const SCHEMA_BY_KIND = {
  implementor: 'implementor_result', validator: 'validator_verdict', smoke: 'smoke_report',
  assumption: 'assumption', coverage: 'coverage_entry', devil: 'devil_refutation',
  qa: 'qa_final', decision: 'decision', mission: 'mission_report',
};

rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });

let pass = 0, fail = 0;
const report = (label, ok, detail) => {
  if (ok) { pass++; console.log(`PASS  ${label}`); }
  else { fail++; console.log(`FAIL  ${label}${detail ? `\n      ${detail}` : ''}`); }
};

// ── Phase A: schema contracts ──
const fixtures = JSON.parse(readFileSync(join(GOLD, 'schemas-fixtures.json'), 'utf8'));
for (const [caseName, instance] of Object.entries(fixtures)) {
  const kind = caseName.split('_')[0];
  const schemaFile = join(SCHEMAS, `${SCHEMA_BY_KIND[kind] || kind}.schema.json`);
  const instFile = join(TMP, `${caseName}.json`);
  writeFileSync(instFile, JSON.stringify(instance));
  const expectValid = caseName.endsWith('_valid');
  let ok = false, detail = '';
  try {
    const out = execFileSync('node', [join(SCRIPTS, 'validate-report.mjs'), schemaFile, instFile], { encoding: 'utf8' });
    ok = JSON.parse(out).valid;
  } catch (e) {
    detail = e.stdout?.slice(0, 300) || e.message;
    try { ok = JSON.parse(e.stdout).valid; } catch { ok = false; }
  }
  report(`schema  ${caseName}`, ok === expectValid, ok === expectValid ? '' : detail);
}

// ── Phase B: deterministic gate ──
const gateFiles = readdirSync(GOLD).filter(f => f.startsWith('gate-') && f.endsWith('.json'));
for (const f of gateFiles) {
  const gold = JSON.parse(readFileSync(join(GOLD, f), 'utf8'));
  const stateFile = join(TMP, f);
  writeFileSync(stateFile, JSON.stringify(gold.state));
  const ex = gold.expect;
  let out, code;
  try {
    out = execFileSync('node', [join(SCRIPTS, 'gate-check.mjs'), stateFile], { encoding: 'utf8' });
    code = 0;
  } catch (e) {
    code = e.status ?? 1;
    out = e.stdout || '';
  }
  const res = JSON.parse(out);
  const expectOpen = ex.gate === 'OPEN';
  let ok = (code === (expectOpen ? 0 : 1)) && res.gate === ex.gate && res.verdict === ex.verdict;
  let detail = ok ? '' : `code=${code} gate=${res.gate} verdict=${res.verdict} (expected ${ex.gate}/${ex.verdict})`;
  if (ok && ex.violations_include) {
    for (const v of ex.violations_include) {
      if (!res.violations.some(vi => vi.includes(v))) { ok = false; detail = `missing violation '${v}'`; break; }
    }
  }
  report(`gate    ${f.replace('.json', '')}`, ok, ok ? '' : `${detail}\n      violations: ${JSON.stringify(res.violations)}`);
}

// ── Phase C: triage plan ──
const triageFiles = readdirSync(GOLD).filter(f => f.startsWith('triage-') && f.endsWith('.json'));
for (const f of triageFiles) {
  const gold = JSON.parse(readFileSync(join(GOLD, f), 'utf8'));
  const instFile = join(TMP, f);
  writeFileSync(instFile, JSON.stringify(gold.instance));
  let ok = false, detail = '';
  try {
    const out = execFileSync('node', [join(SCRIPTS, 'validate-report.mjs'), join(SCHEMAS, 'triage_plan.schema.json'), instFile], { encoding: 'utf8' });
    ok = JSON.parse(out).valid;
  } catch (e) {
    try { ok = JSON.parse(e.stdout).valid; } catch { ok = false; }
    detail = e.stdout?.slice(0, 300) || e.message;
  }
  if (ok !== gold.expect_valid) {
    report(`triage  ${f.replace('.json', '')}`, false, `valid=${ok} (expected ${gold.expect_valid}) ${detail}`);
    continue;
  }
  if (gold.expect_valid && gold.expect_recommendation !== undefined) {
    const rec = gold.instance.recommendation;
    report(`triage  ${f.replace('.json', '')}`, rec === gold.expect_recommendation, `recommendation=${rec} (expected ${gold.expect_recommendation})`);
    continue;
  }
  report(`triage  ${f.replace('.json', '')}`, true);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
