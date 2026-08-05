#!/usr/bin/env node
// render-artifacts.mjs — Forge — Render humano de state.json.
// La FUENTE DE VERDAD es .swarm/state.json; estos .md son solo su proyección legible.
// Uso: node render-artifacts.mjs [path/al/state.json] [outdir]   (defaults: .swarm/state.json, .swarm/)

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const statePath = process.argv[2] || '.swarm/state.json';
const outDir = process.argv[3] || '.swarm';
const state = JSON.parse(readFileSync(statePath, 'utf8'));
mkdirSync(outDir, { recursive: true });

const HEADER = `> ⚠️ GENERADO desde ${statePath} por render-artifacts.mjs — NO editar a mano.\n> Última actualización: ${state.updated_at || 'n/d'} · Protocolo: Forge (Zero-Trust)\n\n`;
const ICON = { PASS: '✅', FAIL: '❌', PENDING_HUMAN: '⏳', DONE: '✅', PARCIAL: '⚠️', EXHAUSTED: '⚠️', VERIFIED: '✅', ASSUMED: '⚠️', DISPROVEN: '❌', INVESTIGATING: '🔍', CUBIERTO: '✅', SIN_CUBRIR: '🔴', SIN_SMOKE: '⚠️', BLOCKED: '⛔', EXTRA: '➕', CLEARED: '✅', BLOCKER: '⛔' };
const ic = (s) => `${ICON[s] || ''} ${s}`.trim();
const esc = (s) => String(s ?? '').replace(/\|/g, '\\|').replace(/\n/g, ' ');

const phases = state.phases || [];
const registry = state.registry || [];
const coverage = state.coverage || [];
const tests = state.tests || [];
const decisions = state.decisions || [];

// ── 1. execution-tracker.md ──
{
  let md = `# Execution Tracker — ${state.mission || state.task || 'Tarea'}\n\n${HEADER}`;
  md += `Nivel de escalado actual: **L${state.level ?? '?'}**${state.floor != null ? ` (suelo L${state.floor})` : ''}\n\n`;
  md += `| Fase | Tarea | Iter | Estado | Último fallo |\n|------|-------|:----:|:------:|-------------|\n`;
  for (const p of phases) md += `| ${p.phase_id || p.id} | ${esc(p.title)} | ${p.iterations ?? 0} | ${ic(p.status)} | ${esc(p.last_fail || '—')} |\n`;
  if (state.escalation_log?.length) {
    md += `\n## Log de escalado\n\n| De | A | Motivo |\n|----|----|--------|\n`;
    for (const e of state.escalation_log) md += `| L${e.from} | L${e.to} | ${esc(e.reason)} |\n`;
  }
  if (state.workflow_runs?.length) {
    md += `\n## Workflow runs (para reanudación)\n\n| Bloque | runId | Estado |\n|--------|-------|--------|\n`;
    for (const r of state.workflow_runs) md += `| ${r.block_id || '—'} | \`${r.run_id}\` | ${r.status || ''} |\n`;
  }
  writeFileSync(join(outDir, 'execution-tracker.md'), md);
}

// ── 2. assumption_registry.md ──
{
  let md = `# Assumption Registry — ${state.mission || state.task || 'Tarea'}\n\n${HEADER}`;
  md += `| ID | Asunción | Fuente | Criticidad | Estado | Verificado por | Fix | Notas |\n|----|----------|--------|:----------:|:------:|----------------|-----|-------|\n`;
  for (const a of registry) {
    md += `| ${a.id || '—'} | ${esc(a.statement)} | ${a.source ? `${a.source.role} ${a.source.phase_id}` : '—'} | ${a.criticality || '—'} | ${ic(a.status)} | ${esc(a.verified_by || '—')} | ${esc(a.fix_ref || '—')} | ${esc(a.notes || '')} |\n`;
  }
  const open = registry.filter(a => ['ASSUMED', 'INVESTIGATING'].includes(a.status)).length;
  md += `\n**Abiertas (blocker de cierre): ${open}** · Verified: ${registry.filter(a => a.status === 'VERIFIED').length} · Disproven: ${registry.filter(a => a.status === 'DISPROVEN').length}\n`;
  writeFileSync(join(outDir, 'assumption_registry.md'), md);
}

// ── 3. coverage_matrix.md ──
{
  const covered = coverage.filter(c => c.status === 'CUBIERTO').length;
  const pct = coverage.length ? Math.round((covered / coverage.length) * 100) : 0;
  const closable = coverage.every(c => ['CUBIERTO', 'PENDING_HUMAN', 'BLOCKED', 'EXTRA'].includes(c.status));
  let md = `# Coverage Matrix — ${state.mission || state.task || 'Tarea'}\n\n${HEADER}`;
  md += `> Coverage: ${covered}/${coverage.length} (${pct}%) — ${closable ? '✅ cierre permitido (pendientes documentados)' : '⚠️ NO CIERRE PERMITIDO'}\n\n`;
  md += `| # Plan | Requisito | Fase | Implementación | Smoke | Estado |\n|--------|-----------|------|----------------|:-----:|:------:|\n`;
  for (const c of coverage) {
    md += `| ${c.id} | ${esc(c.requirement)} | ${c.phase_id || '—'} | ${esc((c.impl_refs || []).join(', ') || '—')} | ${c.smoke_ref || '—'} | ${ic(c.status)}${c.blocked_reason ? `: ${esc(c.blocked_reason)}` : ''} |\n`;
  }
  writeFileSync(join(outDir, 'coverage_matrix.md'), md);
}

// ── 4. qa-report.md ──
{
  const t = { pass: tests.filter(x => x.verdict === 'PASS').length, fail: tests.filter(x => x.verdict === 'FAIL').length, pending: tests.filter(x => x.verdict === 'PENDING_HUMAN').length };
  let md = `# 🧪 QA Report — ${state.mission || state.task || 'Tarea'}\n\n${HEADER}`;
  md += `## Veredicto\n\n| Categoría | Cantidad |\n|-----------|:--------:|\n| ✅ PASS | ${t.pass} |\n| ❌ FAIL | ${t.fail} |\n| ⏳ PENDING HUMAN | ${t.pending} |\n\n`;
  if (t.pending) md += `> ⚠️ ${t.pending} tests requieren verificación humana. Ver "Pending Human".\n\n`;
  md += `## Tests detallados\n\n| ID | Tipo | Comando ejecutado | Output real | Esperado | Resultado |\n|----|------|-------------------|-------------|----------|:---------:|\n`;
  for (const x of tests) md += `| ${x.id} | ${x.type || ''} | \`${esc(x.evidence?.command || 'N/A')}\` | ${esc(x.evidence?.output_excerpt || x.observed || 'N/A')} | ${esc(x.expected)} | ${ic(x.verdict)} |\n`;
  const ph = tests.filter(x => x.verdict === 'PENDING_HUMAN');
  if (ph.length) {
    md += `\n## Pending Human Validation\n\n| Test | Instrucciones |\n|------|---------------|\n`;
    for (const x of ph) md += `| ${x.id} | ${esc(x.human_instructions)} |\n`;
  }
  md += `\n## Assumption Coverage\n\n| Total | Verified | Disproven | Abiertas |\n|:-----:|:--------:|:---------:|:--------:|\n| ${registry.length} | ${registry.filter(a => a.status === 'VERIFIED').length} | ${registry.filter(a => a.status === 'DISPROVEN').length} | ${registry.filter(a => ['ASSUMED', 'INVESTIGATING'].includes(a.status)).length} |\n`;
  writeFileSync(join(outDir, 'qa-report.md'), md);
}

// ── 5. implementation-report.md ──
{
  let md = `# 📋 Implementation Report — ${state.mission || state.task || 'Tarea'}\n\n${HEADER}`;
  md += `## Resumen ejecutivo\n\n| Métrica | Valor |\n|---------|-------|\n`;
  md += `| Fases ejecutadas | ${phases.filter(p => p.status === 'DONE').length}/${phases.length} |\n`;
  md += `| Coverage del plan | ${coverage.length ? Math.round((coverage.filter(c => c.status === 'CUBIERTO').length / coverage.length) * 100) : 0}% |\n`;
  md += `| Asunciones | ${registry.length} (${registry.filter(a => a.status === 'VERIFIED').length} verified, ${registry.filter(a => a.status === 'DISPROVEN').length} disproven, ${registry.filter(a => ['ASSUMED', 'INVESTIGATING'].includes(a.status)).length} abiertas) |\n`;
  md += `| Decisiones autónomas | ${decisions.length} |\n`;
  if (state.budget_spent_tokens) md += `| Presupuesto gastado | ~${Math.round(state.budget_spent_tokens / 1000)}k tokens |\n`;
  md += `\n## Detalle por fase\n\n| Fase | Tarea | Iter | Estado | Notas |\n|------|-------|:----:|:------:|-------|\n`;
  for (const p of phases) md += `| ${p.phase_id || p.id} | ${esc(p.title)} | ${p.iterations ?? 0} | ${ic(p.status)} | ${esc(p.notes || p.last_fail || '')} |\n`;
  const disproven = registry.filter(a => a.status === 'DISPROVEN');
  if (disproven.length) {
    md += `\n## Asunciones críticas descubiertas (DISPROVEN)\n\n`;
    for (const a of disproven) md += `- **${a.id || ''}** ${a.statement} → corregido en ${a.fix_ref}\n`;
  }
  if (state.lessons?.length) {
    md += `\n## Lecciones aprendidas\n\n`;
    for (const l of state.lessons) md += `- ${l}\n`;
  }
  writeFileSync(join(outDir, 'implementation-report.md'), md);
}

// ── 6. MISSION_REPORT.md (solo Modo Misión) ──
if (state.mission) {
  const pendingHuman = state.pending_human || [];
  const debt = state.debt || [];
  let md = `# 🎯 MISSION REPORT — ${state.mission}\n\n${HEADER}`;
  md += `**Plan ancla:** \`${state.plan_ref || 'n/d'}\`\n\n`;
  md += `## Veredicto ejecutivo\n\n`;
  md += `# ${state.gate_verdict || '(pendiente de gate-check.mjs)'}\n\n`;
  md += `> Veredicto recomputado por \`gate-check.mjs\` desde la evidencia — nunca autodeclarado.\n\n`;
  const covered = coverage.filter(c => c.status === 'CUBIERTO').length;
  md += `## Coverage del plan\n\n| Total puntos | Cubiertos | Pending human | Blocked |\n|:---:|:---:|:---:|:---:|\n| ${coverage.length} | ${covered} | ${coverage.filter(c => c.status === 'PENDING_HUMAN').length} | ${coverage.filter(c => c.status === 'BLOCKED').length} |\n\n`;
  if (state.blocks?.length) {
    md += `## Bloques ejecutados\n\n| Bloque | Fases | Estado | Workflow run |\n|--------|-------|:------:|-------------|\n`;
    for (const b of state.blocks) md += `| ${b.block_id} | ${(b.phases || []).join(', ')} | ${b.status} | \`${b.workflow_run_id || '—'}\` |\n`;
    md += '\n';
  }
  if (decisions.length) {
    md += `## Decisiones autónomas tomadas (revísalas cuando quieras)\n\n| ID | Pregunta | Elegida | Rationale | ¿Desvía del plan? |\n|----|----------|---------|-----------|:---:|\n`;
    for (const d of decisions) md += `| ${d.id} | ${esc(d.question)} | ${esc(d.chosen)} | ${esc(d.rationale)} | ${d.deviates_from_plan ? '⚠️ sí' : 'no'} |\n`;
    md += '\n';
  }
  if (debt.length) {
    md += `## Deuda residual\n\n`;
    for (const d of debt) md += `### ${d.ref}\n- **Intentado:** ${d.attempts_summary}\n- **Diagnóstico:** ${d.diagnosis}\n\n`;
  }
  md += `## 🙋 Requiere tu intervención\n\n`;
  if (!pendingHuman.length) md += `Nada. La misión no dejó ningún ítem pendiente del Operador.\n\n`;
  else {
    md += `| # | Qué | Por qué el equipo no pudo | Instrucciones | Est. |\n|---|-----|---------------------------|---------------|------|\n`;
    pendingHuman.forEach((p, i) => { md += `| ${i + 1} | ${esc(p.item)} | ${esc(p.why_blocked)} | ${esc(p.instructions)} | ${p.estimated_minutes ? `${p.estimated_minutes} min` : '—'} |\n`; });
    md += '\n';
  }
  const t = { pass: tests.filter(x => x.verdict === 'PASS').length, fail: tests.filter(x => x.verdict === 'FAIL').length, pending: tests.filter(x => x.verdict === 'PENDING_HUMAN').length };
  md += `## Totales honestos\n\n| ✅ PASS | ❌ FAIL | ⏳ PENDING HUMAN |\n|:---:|:---:|:---:|\n| ${t.pass} | ${t.fail} | ${t.pending} |\n\n`;
  md += `> *"Prefiero un reporte honesto de 80% completado que una mentira de 100%."*\n`;
  writeFileSync(join(outDir, 'MISSION_REPORT.md'), md);
}

console.log(JSON.stringify({ rendered: state.mission ? 6 : 5, outDir }, null, 2));
