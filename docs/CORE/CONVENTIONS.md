# Red Pill Protocol — Naming & Structure Conventions

**Status:** Enforced | **Scope:** All agents, contributors, and AI assistants working on this codebase

---

## 1. File Naming

### 1.1 Documentation Files (`docs/`)

All documentation files and directories use **UPPERCASE** names.

```
docs/
├── CORE/
│   ├── PROTOCOL_OF_SILENCE.md    ✅
│   ├── CONVENTIONS.md            ✅
│   └── DOCUMENTATION_MANUAL.md  ✅
├── TECHNICAL/
│   └── ARCHITECTURE.md           ✅
├── CERTIFICATION/
│   └── REPORT_CLAUDE_4.6_20260322.md  ✅
└── LORE/
    └── PHILOSOPHY.md             ✅
```

**No exceptions** for `docs/` directories or their contents.

### 1.2 Agent Runtime Files (`seeds/`, `.agent/rules/`)

Files consumed as **agent runtime code** (seeds, rules, directives) use **lowercase** names with underscores.

```
seeds/
├── snapshot_rule.md              ✅
├── cognitive_integrity_protocol.md  ✅
└── skin_personality_migration.md    ✅
```

These files are **never moved to** `docs/` — they are code, not documentation.

### 1.3 Root-Level Canonical Files

Standard root-level files keep their traditional casing:

```
README.md         ✅
CHANGELOG.md      ✅
CONTRIBUTING.md   ✅
LICENSE           ✅
NOTICE            ✅
SECURITY.md       ✅
QUICKSTART.md     ✅
```

### 1.4 Python Source Files

All Python files use **lowercase_with_underscores** (PEP 8):

```
src/red_pill/memory.py     ✅
src/red_pill/config.py     ✅
src/red_pill/soul.py       ✅
```

### 1.5 Scripts

All scripts use **lowercase_with_underscores**:

```
scripts/install_neo.sh             ✅
scripts/sovereignty_benchmark.py   ✅
scripts/bunker_telemetry.py           ✅
```

### 1.6 Test Files

All test files use the `test_` prefix followed by **lowercase_with_underscores**:

```
tests/test_memory.py                      ✅  (unit — mirrors src/red_pill/memory.py)
tests/test_swarm_mls_integration.py       ✅  (integration — suffix _integration)
tests/test_sound_of_silence.py            ✅  (governance test)
tests/test_coverage_gaps.py               ✅  (targeted coverage)
```

---

## 2. Directory Naming

### 2.1 Documentation Directories

All directories under `docs/` use **UPPERCASE**:

```
docs/CORE/          ✅
docs/TECHNICAL/     ✅
docs/GUIDES/        ✅
docs/LORE/          ✅
docs/CERTIFICATION/ ✅   ← not docs/certification/
docs/COMMUNITY/     ✅
```

### 2.2 Source Directories

All directories under `src/` use **lowercase_with_underscores**:

```
src/red_pill/swarm/
src/red_pill/metabolism/
src/red_pill/core/
src/red_pill/utils/
```

### 2.3 Test Directory

```
tests/    ✅  (lowercase)
```

---

## 3. The Quick Decision Rule

| Content type | Naming | Location |
|---|---|---|
| Human-readable documentation | `UPPERCASE.md` | `docs/` |
| Agent runtime code / seeds / rules | `lowercase.md` | `seeds/`, `.agent/rules/` |
| Python source / scripts | `lowercase.py` / `lowercase.sh` | `src/`, `scripts/` |
| Unit tests | `test_lowercase.py` | `tests/` |
| Integration tests | `test_lowercase_integration.py` | `tests/` |
| Root canonical files | `UPPERCASE.md` | project root |

---

## 4. Commit Message Format

All commits follow the **Conventional Commits** pattern:

```
<type>: <short description in lowercase>

[optional body]
```

### Allowed Types

| Type | When to use |
|------|------------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `docs` | Documentation only changes |
| `test` | Adding or fixing tests |
| `chore` | Maintenance, tooling, dependencies |
| `cert` | Certification-related commits (reports, fixes from audits) |
| `refactor` | Code restructuring with no behavior change |
| `perf` | Performance improvements |
| `ci` | CI/CD changes |

### Examples

```
feat: add purge confirmation to identity command
fix: write SOVEREIGNTY_PROOF.json to IA_DIR/reports/ not CWD
docs: add CONVENTIONS.md to CORE section
test: mark test_distill_engram as xfail (pre-existing urllib mock issue)
cert: save and act on Claude Sonnet 4.6 certification report [6.1.5]
chore: ruff clean — fix all 61 lint errors
```

---

## 5. Branch Naming

```
feat/<short-hyphenated-description>    ✅  feat/enterprise-foundation-split
fix/<short-hyphenated-description>     ✅  fix/samantha-dead-except
chore/<short-hyphenated-description>   ✅  chore/ruff-cleanup
docs/<short-hyphenated-description>    ✅  docs/conventions
```

Main branches: `main` (stable), `dev` (integration). Feature branches merge into `dev`, releases cut from `main`.

---

## 6. CHANGELOG Entry Format

Changelog entries use `[TYPE]` prefixes in **bold**:

| Prefix | Meaning |
|--------|---------|
| `[ARCH]` | Architectural change or major structural decision |
| `[NEW]` | New file, feature, or capability |
| `[FEAT]` | Enhancement to existing feature |
| `[FIX]` | Bug fix |
| `[QA]` | Test, coverage, or code quality improvement |
| `[DOCS]` | Documentation addition or correction |
| `[CERT]` | Certification report or audit action |
| `[LICENSE]` | Licensing change |
| `[DELETE]` | Deliberate removal of files or functionality |
| `[PERF]` | Performance improvement |
| `[SECURITY]` | Security fix or posture change |

### Version Format

```
## [MAJOR.MINOR.PATCH] - YYYY-MM-DD
```

Versions follow semver. Patch bumps for fixes/docs, minor for features, major for breaking changes.

---

## 7. Runtime Artifact Locations

Runtime-generated files **must not** be written to `docs/` or the repo root.

| Artifact | Correct location |
|---------|-----------------|
| Sovereignty proofs | `IA_DIR/reports/SOVEREIGNTY_PROOF.json` |
| Samantha analysis reports | `IA_DIR/reports/SAMANTHA_REPORT_*.md` |
| Telemetry files | `IA_DIR/.bunker_telemetry.md` |
| MLS group state | `~/.config/red_pill/swarm_groups/` |
| Keystores | `~/.agent/` |

All runtime artifact paths are gitignored. **Never** commit a runtime output to `docs/CERTIFICATION/` or any `docs/` subdirectory unless it is a human-curated audit report (Section 8).

---

## 8. Certification Report Naming

Certification reports (human-curated audit documents) are stored in `docs/CERTIFICATION/`:

```
REPORT_{AUDITOR}_{YYYYMMDD}.md
```

Examples:
```
REPORT_CLAUDE_4.6_20260322.md    ✅
REPORT_GEMINI_PRO_20260401.md    ✅
REPORT_DEEPSEEK_R1_20260501.md   ✅
```

---

## 9. Language Conventions

This project is deliberately **bilingual**:

| Language | Domain |
|----------|--------|
| **English** | All technical documentation, code comments, commit messages, ARCHITECTURE.md, CHANGELOG.md |
| **Spanish** | Lore, identity layer, emotional resonance (`docs/LORE/`), agent-facing seeds, philosophical assertions |

Mixed-language is acceptable in seeds and lore when the emotional register requires it. In production code and documentation, prefer English for consistency.

---

## 10. Code Style — Protocol of Silence Summary

The full standard is in [`docs/CORE/PROTOCOL_OF_SILENCE.md`](PROTOCOL_OF_SILENCE.md). Key rules:

| Rule | Standard |
|------|----------|
| **Indentation** | **Tabs only** — never spaces (YAML: spaces are standard exception) |
| **Dead code** | **Forbidden** — no commented-out blocks, no unreachable `except`, no separator lines |
| **Comments** | Only *why*, never *what*. Decision rationale → `DECISION_LOG.md`, not inline |
| **Imports** | Group: stdlib → third-party → local. No mid-file module-level imports (E402) |
| **Docstrings** | Required for public functions, classes, and modules. Use tab indentation inside |
| **File length** | If a file grows beyond 500 lines, consider decomposition |

The Sound of Silence protocol is enforced automatically by `test_sound_of_silence.py` and `ruff check`.

---

## 10.5 Markdown Metadata — Frontmatter (Desk & Workspace Docs)

Repo `docs/` is reference (bilingual, ALL-CAPS, no frontmatter required). **Desk and
memory-bank `.md`** (Agent_Core `Aleth_Core/`, `.red-pill/memory/`) MUST start with a
YAML frontmatter header. Project docs follow each project's own conventions (out of scope):

```yaml
---
type: rfc|plan|note|research|audit|log|lore|spec|index
id: RFC-XXX            # optional
title: "..."
status: draft|ratified|in-design|implemented|closed|active|paused|archived
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: <Author Name(s)>  # actual author(s); e.g. Aleth (Netrunner), Joan García — never copy a placeholder
project: aleth-core|red-pill|neon-link|frankenswarm|obsidian|personal
related: [...]        # optional
superseded_by:        # optional
archived:             # optional
archive_reason:       # optional
tags: []
---
```

Values are canonical **English** (metadata is machine-consumed). Full template &
lifecycle: `Aleth_Core/FRONTMATTER_TEMPLATE.md` and `docs/CORE/DOCUMENTATION_MANUAL.md`.
Lifecycle: born `draft` in the desk → implemented (source of truth moves to the
project) → `archive/<project>/` with `status: archived`.

---

## 11. Why This Matters for Agents

An AI agent working on this codebase without this document would likely:

- Create `docs/certification/` (lowercase) instead of `docs/CERTIFICATION/`
- Move `seeds/snapshot_rule.md` into `docs/CORE/` (it's not documentation)
- Write runtime output files inside `docs/` directories
- Use inconsistent commit prefixes or changelog entry types
- Add separator comment lines (`# ===`) violating the Protocol of Silence

This document exists to prevent exactly those mistakes. **When in doubt: UPPERCASE for docs, lowercase for code.**

> *"The convention is the memory we don't have to carry."*
