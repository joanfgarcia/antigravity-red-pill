#!/usr/bin/env node
// worktree.mjs — Forge — git-worktree isolation helper.
//
// Feature O4 (auto-resolved on when >=2 implementors mutate files in
// parallel). Each parallel implementor works in an isolated worktree created
// from the main tree's current HEAD; the merge to the main tree happens only
// after the phase gate (escalation.md, runtime-adapters/opencode.md rule 5).
//
// Usage:
//   node worktree.mjs <project_dir> create <phase_id>   → git worktree add .swarm/worktrees/<phase_id> -b swarm/<phase_id>
//   node worktree.mjs <project_dir> changes <phase_id>  → diff of the worktree vs its base (the main HEAD at create time)
//   node worktree.mjs <project_dir> apply <phase_id>    → apply the worktree diff onto the main tree (git apply --3way, no commit)
//   node worktree.mjs <project_dir> remove <phase_id>   → git worktree remove --force
//
// Exit codes: 0 = ok, 1 = error (message on stderr).

import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const [projectDirArg, cmd, phaseId] = process.argv.slice(2);
if (!projectDirArg || !cmd || !phaseId) {
  console.error('usage: worktree.mjs <project_dir> create|changes|apply|remove <phase_id>');
  process.exit(1);
}
const projectDir = resolve(projectDirArg);
const wtsDir = join(projectDir, '.swarm', 'worktrees');
const wtDir = join(wtsDir, phaseId);
const metaPath = join(wtsDir, `${phaseId}.meta.json`);

const git = (args, cwd) => {
  const r = spawnSync('git', args, { cwd, encoding: 'utf8' });
  return { ok: r.status === 0, out: (r.stdout || '').trim(), raw: r.stdout || '', err: (r.stderr || '').trim() };
};

switch (cmd) {
  case 'create': {
    if (existsSync(wtDir)) { console.error(`worktree ${phaseId} already exists`); process.exit(1); }
    mkdirSync(wtsDir, { recursive: true });
    const head = git(['rev-parse', 'HEAD'], projectDir);
    if (!head.ok) { console.error(`no git HEAD in ${projectDir}: ${head.err}`); process.exit(1); }
    const add = git(['worktree', 'add', '-b', `swarm/${phaseId}`, wtDir, head.out], projectDir);
    if (!add.ok) { console.error(`worktree add failed: ${add.err}`); process.exit(1); }
    writeFileSync(metaPath, JSON.stringify({ phase_id: phaseId, base_head: head.out, created_at: new Date().toISOString() }, null, 2));
    console.log(`worktree ${phaseId} created at ${wtDir} (base ${head.out.slice(0, 7)})`);
    process.exit(0);
  }
  case 'changes': {
    if (!existsSync(metaPath)) { console.error(`no meta for ${phaseId} (create first)`); process.exit(1); }
    const { base_head } = JSON.parse(readFileSync(metaPath, 'utf8'));
    const d = git(['diff', '--stat', base_head, 'HEAD'], wtDir);
    console.log(d.ok ? d.out : `no changes or error: ${d.err}`);
    process.exit(d.ok ? 0 : 1);
  }
  case 'apply': {
    if (!existsSync(metaPath)) { console.error(`no meta for ${phaseId} (create first)`); process.exit(1); }
    const { base_head } = JSON.parse(readFileSync(metaPath, 'utf8'));
    const d = git(['diff', '--binary', base_head, 'HEAD'], wtDir);
    if (!d.ok) { console.error(`diff failed: ${d.err}`); process.exit(1); }
    if (!d.out) { console.log(`worktree ${phaseId}: no changes to apply`); process.exit(0); }
    const a = spawnSync('git', ['apply', '--3way', '--whitespace=nowarn', '-'], { cwd: projectDir, input: d.raw, encoding: 'utf8' });
    if (a.status !== 0) { console.error(`apply failed: ${a.stderr || a.stdout}`); process.exit(1); }
    console.log(`worktree ${phaseId} applied onto main tree (uncommitted)`);
    process.exit(0);
  }
  case 'remove': {
    const r = git(['worktree', 'remove', '--force', wtDir], projectDir);
    if (r.ok && existsSync(metaPath)) spawnSync('rm', ['-f', metaPath]);
    if (!r.ok) { console.error(`worktree remove failed: ${r.err}`); process.exit(1); }
    console.log(`worktree ${phaseId} removed`);
    process.exit(0);
  }
  default:
    console.error(`unknown command ${cmd}`);
    process.exit(1);
}
