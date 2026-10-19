# Red Pill Protocol — Operational Workflows

**Status:** Enforced | **Scope:** All agents and contributors making changes to this codebase

> For naming and structural conventions, see [`CONVENTIONS.md`](CONVENTIONS.md).
> For the commit checklist enforced by MCP, see `mcp_RedPill-Kernel_run_pre_pr_audit`.
> For the decision record behind the branching model, see `AD-054` in
> [`DECISION_LOG.md`](../TECHNICAL/DECISION_LOG.md).

---

## 0. Branching Model

Red Pill ships **two working profiles over the same invariants**. Exactly one is active at a
time; the selector is `GIT_WORKFLOW` in the `.env` (`solo` | `canonical`). The agent reads it
before touching git — the active profile is not a matter of taste per session.

### 0.1 Invariants (both profiles)

1. **`main` is stable and never receives a direct push.** The local `pre-push` hook
   (`scripts/git-hooks/pre-push`) rejects it; the GitHub repository ruleset **`no direct
   commit`** enforces the same server-side (deletion + non-fast-forward blocked, PR-only,
   squash merges allowed). Only `main` is guarded this way — `next` is intentionally open.
   All integration into `main` happens through a Pull Request.
2. **No force-push, ever** (`--force`, `-f`, `+refspec`). If a branch diverged, merge or
   revert — never rewrite.
3. **Conventional Commits** (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `cert:`,
   `refactor:`, `perf:`, `ci:`). See CONVENTIONS §4.
4. **The full local gate runs before any push** (§1). CI is deliberately **PR-only** — it is
   the second net, not the first. Do not push hoping CI will tell you.
5. **A branch is a claim, not a private space.** Any session may continue work on a shared
   integration branch (`next`) — that is by design, not an intrusion.
6. **The integration branch is always stable.** `next` (when it exists) is a working tree
   from any session's point of view: green tests, no half-done work, no leftover uncommitted
   changes. Work in progress lives in worktrees; only finished, validated work reaches `next`.

### 0.2 Profile `solo` — single maintainer, accumulated integration (default)

For one maintainer who ships in batches instead of opening a PR per change. This is the
profile the project actually runs on.

```
main ──●───────────────●────────────────●──▶   (stable; only release PRs)
        \             /                /
         ●──●──●──●──● next ──────────┘        (accumulation; one commit per RFC/phase)
          ▲   ▲   ▲
          │   │   └── worktree C  (feat/rfc-c)  ──┐
          │   └────── worktree B  (feat/rfc-b)  ──┤ squash
          └────────── worktree A  (feat/rfc-a)  ──┘
```

**The one rule that defines this profile**: every **local development lives in its own
worktree**, and each worktree lands on `next` as **a single squashed commit** (one commit
per RFC/phase). `next` is the accumulation point; the worktrees are the parallel workshops.

**`next` — the living branch**

- **Name is always `next`.** Never `next-v8.2`, never the RFC name, never a release name.
  The name is the contract: any session that sees `next` knows what it is.
- **Optional.** It exists only after its first push and until the release PR lands. Between
  releases `main` is the only branch.
- **Born from `main`.** `git switch -c next origin/main` at the start of a cycle.
- **Not protected.** Direct commits and pushes to `next` are allowed and expected. Only
  `main` is forbidden.
- **Always stable, always green.** The primary checkout lives on `next`, and `next` must be
  a working tree at all times: it compiles, its tests pass, it contains no half-done work.
  Anything not ready to be green lives in a worktree, never on `next`. This is what lets any
  session pick it up and continue without inheriting someone else's broken state.
- **No uncommitted WIP on `next`.** If a change is not finished, move it to a worktree (or a
  temporary branch) before you stop. A dirty `next` is a shared broken checkout.
- **Synced with `main` by merge**, never rebase: `git merge origin/main` (the hook forbids
  non-fast-forward anyway). Do this before the release PR and whenever `main` moves
  (hotfixes).

**Where work happens**

| Kind of work | Where it lives | Lands on `next` as |
|---|---|---|
| Small change / correction (docs, lint, a fix) | commit **directly on `next`** | one conventional commit |
| RFC phase that is a deliverable unit | its **own worktree**, branch `feat/<slug>` cut from `next` | **one squashed commit** per RFC/phase |
| Urgent hotfix | `fix/<slug>` branched from **`main`** | PR into `main`, then `main` merged back into `next` |
| Parked experiment | worktree on `parked/<slug>` | never merged; its verdict lives in the desk |

Working directly on `next` is the point of this profile: it removes the "this branch belongs
to another session" friction. Isolation is still used where it pays for itself — an RFC that
needs a worktree, or a risky change you want to throw away cleanly.

### 0.2.1 Worktrees → `next`: squash, always

Local development for an RFC does **not** happen on `next` itself. It happens in a dedicated
worktree on its own branch, and it enters `next` **only by squash**. This is the core of the
profile: several workshops in parallel, one readable history in the accumulation branch.

```
next ──●──●──●──●──▶          each ● is one RFC/phase, not its internal churn
        ▲  ▲  ▲
        │  │  └─ feat/rfc-c ──┐
        │  └──── feat/rfc-b ──┤  git merge --squash
        └─────── feat/rfc-a ──┘
```

**Create the worktree from `next`, never from `main`:**

```bash
git fetch origin
git worktree add ~/worktrees/red-pill/<slug> -b feat/<slug> origin/next
```

**Land it on `next` with squash:**

```bash
# In the main checkout, on next
git switch next
git pull --ff-only origin next
git merge --squash feat/<slug>
git commit -m "feat(<area>): <what the RFC/phase delivers>"
git push origin next
```

`--squash` stages the worktree's whole diff without its commits, so `next` gains exactly one
commit with a message you write — the worktree's WIP history never reaches `next`.

**Validation before the squash** (do not skip; CI does not run on `next`):

```bash
# 1. The worktree itself passes
cd ~/worktrees/red-pill/<slug>
uv run ruff check src/ tests/ && uv run pytest tests/ -q --tb=short

# 2. The MERGED result passes, not just the worktree in isolation
cd <main-checkout>            # still on next, squash applied but not committed
uv run ruff check src/ tests/ && uv run pytest tests/ -q --tb=short
git commit -m "feat(<area>): ..."
```

The second run is the one that matters: a worktree can be green alone and break `next` on
contact.

**After the squash**

- The worktree branch **stays alive** until the release PR merges (it is the evidence trail
  for that RFC/phase). Do not delete it on squash.
- The worktree directory may be removed once its work is on `next` and no further phases
  depend on it: `git worktree remove ~/worktrees/red-pill/<slug>`.
- Record the worktree (branch + path + last commit) in the RFC/note so the next session can
  find and resume it. A worktree nobody can find is a lost worktree.
- **Never** merge a worktree with `--no-ff`, and never rebase `next` onto it. Squash in,
  merge down.

**Release**

1. `next` is synced with `main` (`git merge origin/main`) and the local gate passes.
2. Bump `pyproject.toml`, add the `CHANGELOG.md` entry for the version.
3. One PR: **`next` → `main`**. Title = release title.
4. **Squash and merge** — `main` gets a single release commit; the detail lives in the PR,
   the CHANGELOG and the tag.
5. **Delete `next`** (local and remote) right after the merge. The next cycle recreates it
   from the new `main`. This is deliberate: a stale `next` silently diverges.
6. Tag `vX.Y.Z` on the resulting `main` commit.

**Hotfix during a cycle**

`fix/<slug>` from `main` → PR → squash into `main` → `main` merged into `next` (so the fix
does not reappear as a conflict at release time).

### 0.3 Profile `canonical` — multiple contributors

For when there is more than one maintainer, or when the project wants review per change.

- **No `next`.** Every change is its own branch from `main`.
- `feat/<slug>` | `fix/<slug>` | `docs/<slug>` | `chore/<slug>` → **PR → `main`** →
  squash merge → delete the branch.
- One PR = one reviewable, revertable change. The release is a tag on `main`, not a
  branch merge.
- Same invariants, same gate, same commit format.

### 0.4 Switching profiles

Set `GIT_WORKFLOW` in `.env` and re-seed (`red-pill bunker update`, or
`scripts/inject_cli.py`). The agent rule seeded at `~/.agent/rules/git_workflow.md` states
the active profile, so every harness sees it.

- `solo → canonical`: finish or park `next` first (merge it via a release PR, or park it as
  `parked/<slug>` with a verdict in the desk). Do not leave an orphan `next`.
- `canonical → solo`: nothing to migrate; `next` is created on the next cycle.

### 0.5 Branch names

```
main                      stable, PR-only
next                      solo profile: accumulated integration (fixed name)
feat/<slug>               feature / RFC work
fix/<slug>                bug fix
docs/<slug>               documentation only
chore/<slug>              tooling, deps, housekeeping
parked/<slug>             parked experiment with a verdict (see desk research/)
cell/<phase>              Forge parallel-implementor worktree (ephemeral)
awaken/<timestamp>        autonomous awakening worktree (ephemeral)
```

`<slug>` is kebab-case: lowercase, digits, hyphens (CONVENTIONS §5).

---

## 1. Pre-Push Checklist

Run **before every `git push`** — no exceptions. CI only runs on Pull Requests, so this is
the only gate `next` gets.

```
[ ] 1. CHANGELOG.md updated for this version
[ ] 2. ruff check src/ tests/     → All checks passed
[ ] 3. pytest tests/ -q --tb=short → No unexpected failures
[ ] 4. Coverage gate met          → value in pyproject.toml
[ ] 5. git commit with correct type prefix
[ ] 6. git push
```

### Quick command

```bash
uv run ruff check src/ tests/ && \
uv run pytest tests/ -q --tb=no --cov=src/red_pill \
  --ignore=tests/test_sound_of_silence.py
```

**CHANGELOG first.** If you push without updating the CHANGELOG, the next agent working on
this branch will not know what changed. This is the most commonly skipped step.

**Coverage**: the enforced threshold is `[tool.coverage.report] fail_under` in
`pyproject.toml`. That value is the single source of truth — do not hardcode a number here
or in a guide; read the file.

---

## 2. Pre-PR Audit

Run before opening a Pull Request. This is more thorough than the pre-push check.

### Via MCP (preferred)

```
mcp_RedPill-Kernel_run_pre_pr_audit
```

### Manual steps

```bash
# 1. Lint
uv run ruff check src/ tests/

# 2. Type check
uv run mypy src/red_pill/ --ignore-missing-imports

# 3. Full test suite + coverage (gate read from pyproject.toml)
uv run pytest tests/ -q --tb=short \
  --cov=src/red_pill \
  --ignore=tests/test_sound_of_silence.py

# 4. Verify no runtime artifacts committed
git status --short | grep -E "^[AM].*\.(json|log|md)" | grep -v docs/
```

### Checklist

```
[ ] Lint: 0 errors
[ ] Type check: 0 errors (or documented suppressions)
[ ] Tests: all pass (xfail documented, integration skips acceptable)
[ ] Coverage: gate in pyproject.toml met
[ ] CHANGELOG: entry present for this version
[ ] No runtime artifacts committed (SOVEREIGNTY_PROOF.json, *.log, etc.)
[ ] No hardcoded local paths (~/...) in src/
[ ] docs/README.md updated if docs files were added/removed
```

---

## 3. Release Flow

Use this flow when creating a new version tag and integrating the accumulated work into
`main`. It applies to both profiles; in `canonical` the "integration branch" is simply the
latest `main` (skip steps 1 and 4).

### Steps

```bash
# 1. Sync the integration branch with main (merge, never rebase)
git switch next
git merge origin/main

# 2. Verify pre-PR passes (Section 2) ✅

# 3. Bump version in pyproject.toml
#    [project] version = "X.Y.Z"

# 4. Ensure CHANGELOG has [X.Y.Z] entry with today's date
#    Commit the bump on next
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to X.Y.Z"

# 5. Push next and open the release PR (next → main)
git push origin next

# 6. Merge the PR with "Squash and merge" (single release commit on main)

# 7. Delete next locally and remotely, then recreate it next cycle
git switch main && git pull
git branch -d next
git push origin --delete next

# 8. Tag the release commit on main
git tag vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z
```

### Release checklist

```
[ ] pyproject.toml version matches CHANGELOG version
[ ] next merged into main via PR (squash)
[ ] next deleted (local + remote) — next cycle recreates it from main
[ ] Tag vX.Y.Z created and pushed
[ ] GitHub release created (optional but recommended)
```

> Never `git checkout main && git merge --no-ff && git push origin main`: the `pre-push` hook
> rejects the push, and the squash-merge through the PR is what keeps `main` readable.

---

## 4. Certification Flow

Used when requesting an engineering-grade audit from Ecosystem Auditors (e.g., DeepSeek, Claude, Gemini, Grok, Lumo, etc.).

### Preparation

```bash
# Generate split digests for LLM context limits
scripts/prepare_certification.sh
```

This produces:
```
RED_PILL_DIGEST_CORE.txt    ← src/ + config
RED_PILL_DIGEST_TESTS.txt   ← tests/
RED_PILL_DIGEST_LORE.txt    ← docs/ + seeds/
```

### Ecosystem Auditors

Per `docs/TECHNICAL/CERTIFICATION/CERTIFICATION_PROTOCOL.md`, any advanced reasoning model can act as an auditor. Common auditors include (but are not limited to):

- **Claude** (Anthropic): Protocol Rigor & Security Audit
- **DeepSeek** (DeepSeek): Logic, Mathematical Correctness & Optimization
- **Gemini** (Google): Context, Architecture & Scalability Analysis
- **Grok** (xAI): Codebase Integrity & Threat Vectors
- **Lumo**: Privacy & Encryption Specialist
- **GPT-4o/o1/o3** (OpenAI): Cross-platform Compatibility & Edge Cases

### Report storage

After receiving the certification report, save it at:

```
docs/TECHNICAL/CERTIFICATION/REPORT_{AUDITOR}_{YYYYMMDD}.md
```

Act on P1 items immediately. P0 items block production certification. P2/P3 are tracked for the next cycle.

### Post-certification checklist

```
[ ] Report saved to docs/CERTIFICATION/
[ ] P1 fixes committed in the same release cycle
[ ] CHANGELOG entry [CERT] added
[ ] docs/README.md CERTIFICATION section updated
```

---

## 5. Documentation Update Flow

When adding or removing files in `docs/`:

```
[ ] File name is UPPERCASE.md (see CONVENTIONS.md §1.1)
[ ] Directory is UPPERCASE (see CONVENTIONS.md §2.1)
[ ] docs/README.md updated with new/removed file
[ ] Internal links checked (no broken references)
[ ] CHANGELOG entry [DOCS] added if substantive
```

---

## 6. Identity Resync Flow

When the agent loses identity context (e.g., after a model change):

```bash
# Via MCP
mcp_RedPill-Kernel_refresh_session_context

# Via CLI
red-pill identity refresh
```

If the Bünker is unreachable:

```bash
python3 scripts/wake_up_v6.py
```

---

## Common Pitfalls

| Mistake | Prevention |
|---------|-----------|
| Push without CHANGELOG | Pre-push checklist §1 |
| Working on `main` "just this once" | §0.1 — create or switch to `next` first |
| Leaving uncommitted WIP or a red tree on `next` | §0.2 — move it to a worktree; `next` stays green |
| Squashing a worktree without testing the merged result | §0.2.1 — run the gate after `merge --squash`, before `commit` |
| Creating `next` with a release/RFC name | §0.2 — the name is always `next` |
| Rebasing `next` onto `main` | §0.2 — merge; the hook forbids non-fast-forward |
| Keeping `next` alive after the release PR | §3 step 7 — delete it, recreate next cycle |
| Branching an RFC worktree from `main` | §0.2 — worktrees branch from `next` |
| `docs/certification/` lowercase | CONVENTIONS.md §2.1 |
| Runtime artifact in `docs/` | CONVENTIONS.md §7 |
| Dead code block (unreachable except) | `ruff check` + SoS test |
| Hardcoded `~/` path | Pre-PR audit §2 |
| Mid-file module-level import (E402) | Move imports to top of file |
