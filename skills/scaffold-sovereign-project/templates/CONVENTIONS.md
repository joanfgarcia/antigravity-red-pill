# pure-mls — Naming & Structure Conventions

**Status:** Enforced | **Scope:** All agents, contributors, and AI assistants working on this codebase

---

## 1. File Naming

### 1.1 Documentation Files (`docs/`)

All documentation files and directories use **UPPERCASE** names.

```
docs/
├── CORE/
│   └── PROTOCOL_OF_SILENCE.md    ✅
```

**No exceptions** for `docs/` directories or their contents.

### 1.2 Root-Level Canonical Files

Standard root-level files keep their traditional casing:

```
README.md         ✅
CHANGELOG.md      ✅
CONVENTIONS.md    ✅
LICENSE           ✅
```

### 1.3 Python Source Files

All Python files use **lowercase_with_underscores** (PEP 8):

```
src/pure_mls/tree.py       ✅
src/pure_mls/group.py      ✅
src/pure_mls/hpke.py       ✅
```

### 1.4 Test Files

All test files use the `test_` prefix followed by **lowercase_with_underscores**:

```
tests/test_tree.py                      ✅  (unit — mirrors src/pure_mls/tree.py)
tests/test_e2e_mqtt.py                  ✅  (integration — end to end)
tests/test_sound_of_silence.py          ✅  (governance test)
```

---

## 2. Directory Naming

### 2.1 Documentation Directories

All directories under `docs/` use **UPPERCASE**:

```
docs/CORE/          ✅
docs/CERTIFICATION/ ✅
```

### 2.2 Source Directories

All directories under `src/` use **lowercase_with_underscores**:

```
src/pure_mls/
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
| Python source / scripts | `lowercase.py` / `lowercase.sh` | `src/`, `scripts/` |
| Unit and E2E tests | `test_lowercase.py` | `tests/` |
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

### Examples

```
feat: add basic LBBT operations to RatchetTree
fix: resolve InvalidTag exception in process_update
docs: add CONVENTIONS.md to track red-pill standards
test: include test_sound_of_silence in QA suite
```

---

## 5. Branch Naming

```
feat/<short-hyphenated-description>    ✅  feat/openmls-interop
fix/<short-hyphenated-description>     ✅  fix/lbbt-out-of-bounds
```

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
| `[SECURITY]` | Security fix or posture change |

Versions follow semver. Patch bumps for fixes/docs, minor for features, major for breaking changes.

---

## 7. Certification Report Naming

Certification reports (human-curated audit documents) are stored in `docs/CERTIFICATION/` (must be created when needed):

```
REPORT_{AUDITOR}_{YYYYMMDD}.md
```

Examples:
```
REPORT_CLAUDE_4.6_20260322.md    ✅
```

---

## 8. Code Style — Protocol of Silence Summary

The full standard is in [`docs/CORE/PROTOCOL_OF_SILENCE.md`](docs/CORE/PROTOCOL_OF_SILENCE.md). Key rules:

| Rule | Standard |
|------|----------|
| **Indentation** | **Tabs only** — never spaces (YAML: spaces are standard exception) |
| **Dead code** | **Forbidden** — no commented-out blocks, no unreachable `except`, no separator lines |
| **Comments** | Only *why*, never *what*. Decision rationale → `DECISION_LOG.md`, not inline |
| **Imports** | Group: stdlib → third-party → local. No mid-file module-level imports (E402) |
| **Docstrings** | Required for public functions, classes, and modules. Use tab indentation inside |

The Sound of Silence protocol is enforced automatically by `test_sound_of_silence.py` and `ruff check`.
