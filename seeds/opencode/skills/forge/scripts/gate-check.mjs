#!/usr/bin/env node
// gate-check.mjs — Forge v3.2 — Gate determinista de cierre (7 checks, 10 en misión).
// El veredicto de los agentes es ADVISORY: este script RECOMPUTA el estado real desde .swarm/state.json.
// Uso: node gate-check.mjs [path/al/state.json]   (default: .swarm/state.json)
// Output: JSON { gate: "OPEN"|"CLOSED", verdict, violations[], summary } — exit 1 si CLOSED.

import { readFileSync } from 'node:fs';

const statePath = process.argv[2] || '.swarm/state.json';
let state;
try {
  state = JSON.parse(readFileSync(statePath, 'utf8'));
} catch (e) {
  console.log(JSON.stringify({ gate: 'CLOSED', verdict: 'PARTIAL', violations: [`No se pudo leer/parsear ${statePath}: ${e.message}`] }, null, 2));
  process.exit(1);
}

const violations = [];
const phases = state.phases || [];
const registry = state.registry || [];
const coverage = state.coverage || [];
const decisions = state.decisions || [];
const tests = state.tests || []; // todos los tests agregados (smoke + qa)
const isMission = Boolean(state.mission);

// REGLA 1/6: evidencia trivial no cuenta como ejecución real
const TRIVIAL = /^\s*(grep|test\s+-[ef]|ls(\s|$)|wc(\s|$)|cat\s+[^|]*$)/;

// Check 1 — toda fase cerrada (DONE o PARCIAL documentado; nada PENDING/EXHAUSTED/INTERRUPTED sin resolver)
for (const ph of phases) {
  if (!['DONE', 'PARCIAL'].includes(ph.status)) {
    const id = ph.phase_id || ph.id;
    if (ph.status === 'EXHAUSTED') {
      violations.push(`Check 1: fase ${id} EXHAUSTED (fallos genuinos) — disparar la escalera anti-abandono (escalation.md) o documentarla como PARCIAL con deuda; no se cierra tal cual`);
    } else if (ph.status === 'INTERRUPTED') {
      violations.push(`Check 1: fase ${id} INTERRUPTED (${ph.interrupted_reason || 'agentes caídos por rate-limit/API'}) — reanudar con resumeFromRunId / modo canónico (controlled-stop.md); NO es fallo genuino, NO disparar la escalera`);
    } else {
      violations.push(`Check 1: fase ${id} en estado '${ph.status}' (debe ser DONE o PARCIAL documentado)`);
    }
  }
  if (ph.status === 'PARCIAL' && !ph.last_fail && !ph.debt_ref) {
    violations.push(`Check 1: fase ${ph.phase_id || ph.id} PARCIAL sin motivo ni referencia a deuda`);
  }
}

// Check 2 — 0 asunciones ASSUMED/INVESTIGATING
for (const a of registry) {
  if (['ASSUMED', 'INVESTIGATING'].includes(a.status)) {
    violations.push(`Check 2: asunción ${a.id || ''} '${a.statement}' sigue ${a.status} (blocker, Regla 2)`);
  }
}

// Check 3 — todo DISPROVEN con fix_ref
for (const a of registry) {
  if (a.status === 'DISPROVEN' && !a.fix_ref) {
    violations.push(`Check 3: asunción ${a.id || ''} DISPROVEN sin fix_ref`);
  }
}

// Check 4 — 0 SIN_CUBRIR (PENDING_HUMAN/BLOCKED no bloquean pero se listan en summary)
for (const c of coverage) {
  if (c.status === 'SIN_CUBRIR') violations.push(`Check 4: punto del plan ${c.id} '${c.requirement || ''}' SIN_CUBRIR (Regla 3/8)`);
  if (c.status === 'SIN_SMOKE') violations.push(`Check 4: punto ${c.id} sin smoke test (Regla 4)`);
  if (c.status === 'BLOCKED' && !c.blocked_reason) violations.push(`Check 4: punto ${c.id} BLOCKED sin razón documentada`);
}

// Check 5 — 0 tests FAIL sin fase de fix asociada
for (const t of tests) {
  if (t.verdict === 'FAIL' && !t.fix_ref) {
    violations.push(`Check 5: test ${t.id} FAIL sin fix asociado`);
  }
}

// Check 6 — evidencia no trivial en todo PASS (anti fake-smoke)
for (const t of tests) {
  if (t.verdict === 'PASS') {
    if (!t.evidence || !t.evidence.command || !t.evidence.output_excerpt) {
      violations.push(`Check 6: test ${t.id} PASS sin evidencia completa (Regla 6) → INSUFFICIENT`);
    } else if (TRIVIAL.test(t.evidence.command)) {
      violations.push(`Check 6: test ${t.id} PASS con evidencia trivial '${t.evidence.command}' (Regla 1) → INSUFFICIENT`);
    }
  }
  if (t.verdict === 'PENDING_HUMAN' && !(t.human_instructions && t.human_instructions.trim().length >= 20)) {
    violations.push(`Check 6: test ${t.id} PENDING_HUMAN sin instrucciones útiles`);
  }
}

// Check 7 — último voto del panel adversarial = CLEARED
const lastPanel = state.final_panel || state.last_panel;
if (!lastPanel) {
  violations.push('Check 7: no consta revisión final del Devil\'s Advocate (panel adversarial)');
} else if (lastPanel.vote !== 'CLEARED') {
  violations.push(`Check 7: panel adversarial final votó ${lastPanel.vote}: ${JSON.stringify(lastPanel.refutations?.map(r => r.claim) || [])}`);
}

// ── Checks de Modo Misión ──
if (isMission) {
  // Check 8 — toda decisión autónoma con rationale y fuentes
  for (const d of decisions) {
    if (!d.rationale || d.rationale.trim().length < 20) violations.push(`Check 8: decisión ${d.id} sin rationale suficiente`);
    if (!Array.isArray(d.sources_consulted) || d.sources_consulted.length === 0) violations.push(`Check 8: decisión ${d.id} sin fuentes consultadas`);
    if (d.reversible === false && d.executed === true && d.in_plan !== true) {
      violations.push(`Check 8: decisión ${d.id} IRREVERSIBLE ejecutada FUERA del plan ancla (debía ir a pending_human)`);
    }
  }
  // Check 9 — todo pending_human con instrucciones accionables
  for (const p of (state.pending_human || [])) {
    if (!(p.instructions && p.instructions.trim().length >= 20)) {
      violations.push(`Check 9: pending_human '${p.item || p.test_id}' sin instrucciones accionables`);
    }
  }
  // Check 10 — higiene de procesos (v3.2): la misión no cierra con procesos registrados vivos
  for (const p of (state.live_processes || [])) {
    if (p.status !== 'KILLED') {
      violations.push(`Check 10: proceso registrado sin matar: pid ${p.pid} (${p.command || '?'}${p.port ? `, puerto ${p.port}` : ''}) — la misión no cierra con zombis (controlled-stop.md §6)`);
    }
  }
}

// ── Recomputación del veredicto oficial ──
const pendingCount = coverage.filter(c => c.status === 'PENDING_HUMAN').length
  + tests.filter(t => t.verdict === 'PENDING_HUMAN').length
  + (state.pending_human || []).length;
const debtCount = (state.debt || []).length + phases.filter(p => p.status === 'PARCIAL').length;

let verdict;
if (violations.length > 0) verdict = 'PARTIAL';
else if (debtCount > 0) verdict = 'PARTIAL';
else if (pendingCount > 0) verdict = isMission ? 'COMPLETE_WITH_PENDING' : 'COMPLETE';
else verdict = 'COMPLETE';

const gate = violations.length === 0 ? 'OPEN' : 'CLOSED';

const summary = {
  phases: { total: phases.length, done: phases.filter(p => p.status === 'DONE').length, parcial: phases.filter(p => p.status === 'PARCIAL').length },
  assumptions: {
    total: registry.length,
    verified: registry.filter(a => a.status === 'VERIFIED').length,
    disproven: registry.filter(a => a.status === 'DISPROVEN').length,
    open: registry.filter(a => ['ASSUMED', 'INVESTIGATING'].includes(a.status)).length,
  },
  coverage: {
    total: coverage.length,
    cubierto: coverage.filter(c => c.status === 'CUBIERTO').length,
    pending_human: coverage.filter(c => c.status === 'PENDING_HUMAN').length,
    blocked: coverage.filter(c => c.status === 'BLOCKED').length,
    sin_cubrir: coverage.filter(c => c.status === 'SIN_CUBRIR').length,
  },
  tests: {
    pass: tests.filter(t => t.verdict === 'PASS').length,
    fail: tests.filter(t => t.verdict === 'FAIL').length,
    pending_human: tests.filter(t => t.verdict === 'PENDING_HUMAN').length,
  },
  decisions: decisions.length,
  debt: debtCount,
  provenance: provenanceSources(state),
};

// v3.1: audit of WHO executed what, from the ledger entries the orchestrator stamped
// (report provenance: harness/provider/model). Informational, never a gate check.
function provenanceSources(state) {
  const entries = state.usage_ledger?.entries || [];
  const sources = [];
  const seen = new Set();
  for (const e of entries) {
    const p = e.provenance;
    if (!p) continue;
    const key = [p.harness, p.provider, p.model].filter(Boolean).join('/');
    if (seen.has(key)) continue;
    seen.add(key);
    sources.push({ key, roles: entries.filter(x => x.provenance && [x.provenance.harness, x.provenance.provider, x.provenance.model].filter(Boolean).join('/') === key).map(x => x.role || '?').filter((v, i, a) => a.indexOf(v) === i) });
  }
  return { entries: entries.length, sources };
}

console.log(JSON.stringify({ gate, verdict, violations, summary }, null, 2));
process.exit(gate === 'OPEN' ? 0 : 1);
