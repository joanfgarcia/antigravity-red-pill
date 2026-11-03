# Git workflow — active profile: {{profile}}

This is the **profile-specific** agent rule, rendered from
`seeds/rules/git_workflow.md` using `GIT_WORKFLOW` in `.env` (`solo` | `canonical`).
Do not edit the deployed copy at `~/.agent/rules/git_workflow.md`; change the
profile in `.env` and re-seed (`red-pill bunker update` or the installer).

## Invariants (both profiles)

- `main` is stable: **never** commit or push to it directly. It only moves through a PR.
- **Never force-push** (`--force`, `-f`, `+refspec`). If a branch diverged, merge or revert.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `cert:`, `refactor:`,
  `perf:`, `ci:`).
- Run the full local gate before every push: `ruff`, `mypy`, `pytest` (coverage gate is
  `fail_under` in `pyproject.toml`). CI runs on PRs only — it is the second net, not the first.
- A branch is shared, not owned by the session that created it. Continue work from another
  session instead of opening a parallel one.
- **Feature branches stay local.** The remote is `main` + `next` (solo) or `main` + PR
  branches (canonical); do not leave a remote feature branch behind.
- When a worktree is used, record `branch + path + last commit` in the RFC/note. The branch
  is the evidence trail until the release PR lands.

<!-- profile:solo:start -->
## `solo` — single maintainer, accumulated integration

- **`next` is the living integration branch.** Name is always `next` (never a release/RFC
  name). Optional: it exists after its first push and until the release PR lands.
- **`next` is always stable and green.** The primary checkout lives on `next`; it must build,
  pass tests and contain no half-done work or uncommitted WIP. A change that is not ready
  lives in a worktree.
- **Each local development lives in its own worktree** (`git worktree add ... -b feat/<slug>
  origin/next`), cut from `next`, never from `main`.
- **Worktrees enter `next` only by squash**: `git merge --squash feat/<slug>` from `next`,
  validate the **merged** result, then one conventional commit. One commit per RFC/phase.
- Small fixes may be committed directly on `next`.
- Sync with `main` by **merge**, never rebase (`git merge origin/main`). The pre-push hook
  rejects non-fast-forward updates.
- **Release**: sync `main` into `next` → bump version + CHANGELOG → one PR `next → main` →
  **squash merge** (GitHub auto-deletes the head branch) → delete `next` locally too → tag
  `vX.Y.Z` on `main`. The next cycle recreates `next` **fresh from `main`**.
- **A missing `origin/next` after a release PR is the expected state, not a bug.** Do not
  recreate it with its old history, do not merge `main` back into it, and do not "repair"
  it: the next cycle cuts a new `next` from the new `main`. (Incident 2026-11-03: an agent
  reconciled the deleted `next` after the 8.3.0 squash — the flow was right, the reflex was
  wrong.)
- A branch cut **before** the release bump (e.g. an `awaken/*` based on the old `next`) enters
  the new `next` by **cherry-pick or rebase** — never by squash-merging its whole tree, which
  would revert the version bump.
- **The cycle that starts with no `next` creates it from the new `main`**
  (`git switch -c next origin/main`). This includes the first autonomous awakening after a
  release: an awakening that finds no `origin/next` must not fail, must not point to the old
  branch, and must not resurrect it — it cuts the new `next` from `main` and works from there.
- **Hotfix**: `fix/<slug>` from `main` → PR → `main`, then merge `main` back into `next`.
<!-- profile:solo:end -->

<!-- profile:canonical:start -->
## `canonical` — multiple contributors

- **No `next`.** One short-lived branch per change, cut from `main`: `feat/<slug>`,
  `fix/<slug>`, `docs/<slug>`, `chore/<slug>`.
- Open one PR per change → `main`; merge with **squash** and delete the branch.
- Release = tag on `main`.
<!-- profile:canonical:end -->
