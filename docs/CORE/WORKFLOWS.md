# Red Pill Protocol — Operational Workflows

**Status:** Enforced | **Scope:** All agents and contributors making changes to this codebase

> For naming and structural conventions, see [`CONVENTIONS.md`](CONVENTIONS.md).
> For the commit checklist enforced by MCP, see `mcp_RedPill-Kernel_run_pre_pr_audit`.

---

## 1. Pre-Push Checklist

Run **before every `git push`** — no exceptions.

```
[ ] 1. CHANGELOG.md updated for this version
[ ] 2. ruff check src/ tests/     → All checks passed
[ ] 3. pytest tests/ -q --tb=short → No unexpected failures
[ ] 4. Coverage gate ≥96%          → Required
[ ] 5. git commit with correct type prefix
[ ] 6. git push
```

### Quick command

```bash
uv run ruff check src/ tests/ && \
uv run pytest tests/ -q --tb=no --cov=src/red_pill --cov-fail-under=96 \
  --ignore=tests/test_sound_of_silence.py
```

**CHANGELOG first.** If you push without updating the CHANGELOG, the next agent working on this branch will not know what changed. This is the most commonly skipped step.

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

# 3. Full test suite + coverage
uv run pytest tests/ -q --tb=short \
  --cov=src/red_pill \
  --cov-fail-under=96 \
  --ignore=tests/test_sound_of_silence.py

# 4. Verify no runtime artifacts committed
git status --short | grep -E "^[AM].*\.(json|log|md)" | grep -v docs/
```

### Checklist

```
[ ] Lint: 0 errors
[ ] Type check: 0 errors (or documented suppressions)
[ ] Tests: all pass (xfail documented, integration skips acceptable)
[ ] Coverage: ≥96%
[ ] CHANGELOG: entry present for this version
[ ] No runtime artifacts committed (SOVEREIGNTY_PROOF.json, *.log, etc.)
[ ] No hardcoded local paths (~/...) in src/
[ ] docs/README.md updated if docs files were added/removed
```

---

## 3. Release Flow

Use this flow when creating a new version tag and merging to `main`.

### Steps

```bash
# 1. Verify pre-PR passes (Section 2) ✅

# 2. Bump version in pyproject.toml
#    [project] version = "X.Y.Z"

# 3. Ensure CHANGELOG has [X.Y.Z] entry with today's date

# 4. Commit version bump
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to X.Y.Z"

# 5. Tag
git tag vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z

# 6. Merge to main
git checkout main
git merge feat/branch-name --no-ff
git push origin main
```

### Release checklist

```
[ ] pyproject.toml version matches CHANGELOG version
[ ] Tag vX.Y.Z created and pushed
[ ] Merged to main via --no-ff
[ ] GitHub release created (optional but recommended)
```

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
| `docs/certification/` lowercase | CONVENTIONS.md §2.1 |
| Runtime artifact in `docs/` | CONVENTIONS.md §7 |
| Dead code block (unreachable except) | `ruff check` + SoS test |
| Hardcoded `~/` path | Pre-PR audit §2 |
| Mid-file module-level import (E402) | Move imports to top of file |
