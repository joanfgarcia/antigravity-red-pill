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
│   ├── AGENT_SAFETY_PROTOCOL.md  ✅
│   └── CONVENTIONS.md            ✅
├── TECHNICAL/
│   ├── ARCHITECTURE.md           ✅
│   └── THREAT_MODEL.md           ✅
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

Standard root-level files that follow industry convention keep their traditional casing:

```
README.md         ✅  (industry standard)
CHANGELOG.md      ✅
CONTRIBUTING.md   ✅
LICENSE           ✅
NOTICE            ✅
SECURITY.md       ✅
QUICKSTART.md     ✅
```

### 1.4 Python Source Files

All Python files use **lowercase_with_underscores** (PEP 8 standard):

```
src/red_pill/
├── memory.py         ✅
├── config.py         ✅
└── soul.py           ✅
```

### 1.5 Scripts

All scripts use **lowercase_with_underscores**:

```
scripts/
├── install_neo.sh        ✅
├── sovereignty_benchmark.py  ✅
└── bunker_daemon.py      ✅
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
docs/PLANS/         ✅
docs/COMMUNITY/     ✅
docs/CERTIFICATION/ ✅   ← not docs/certification/
```

### 2.2 Source Directories

All directories under `src/` use **lowercase_with_underscores**:

```
src/red_pill/
├── swarm/
├── metabolism/
├── core/
└── utils/
```

### 2.3 Test Directory

```
tests/              ✅  (lowercase, singular or plural per project convention)
```

---

## 3. The lowercase / UPPERCASE Decision Rule

When in doubt, apply this rule:

| Content type | Naming | Location |
|---|---|---|
| Human-readable documentation | `UPPERCASE.md` | `docs/` |
| Agent runtime code / seeds / rules | `lowercase.md` | `seeds/`, `.agent/rules/` |
| Python source / scripts | `lowercase.py` / `lowercase.sh` | `src/`, `scripts/` |
| Tests | `test_lowercase.py` | `tests/` |
| Root canonical files | `UPPERCASE.md` | project root |

---

## 4. Certification Reports

Certification reports are stored in `docs/CERTIFICATION/` with the naming format:

```
REPORT_{AUDITOR}_{DATE}.md
```

Examples:
```
REPORT_CLAUDE_4.6_20260322.md    ✅
REPORT_GEMINI_PRO_20260401.md    ✅
```

---

## 5. Why This Matters for Agents

An AI agent working on this codebase without this document would likely:

- Create `docs/certification/` (lowercase) instead of `docs/CERTIFICATION/`
- Move `seeds/snapshot_rule.md` into `docs/CORE/` (it's not documentation)
- Create runtime output files inside `docs/` directories

This document exists to prevent exactly those mistakes. **When in doubt: UPPERCASE for docs, lowercase for code.**

> *"The convention is the memory we don't have to carry."*
