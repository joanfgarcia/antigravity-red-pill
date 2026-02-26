# Contributing to Red Pill Protocol

Thank you for your interest in contributing. Red Pill is a sovereignty-first project with a small set of strict engineering conventions. Please read this document fully before opening a PR.

---

## ⚠️ Non-Negotiable: Tabs, Not Spaces

**Red Pill uses tabs (`\t`) for indentation everywhere — Python, YAML, Bash.**

This is an **Immutable Core** governance decision and will never change. PEP 8 recommends spaces, and we respectfully disagree for this project. Ruff is configured to enforce tabs and will reject any PR with space-based indentation.

**Before your first commit, configure your editor:**

```bash
# VS Code: add to .vscode/settings.json
{
  "editor.insertSpaces": false,
  "editor.detectIndentation": false,
  "editor.tabSize": 4
}

# Vim / Neovim
set noexpandtab
set tabstop=4
set shiftwidth=4

# JetBrains IDEs
# Settings → Editor → Code Style → Python → Tabs and Indents → Tab character
```

If your PR fails CI with `W191` or `E101` errors, it means you have spaces. Run:
```bash
uv run ruff check src/ tests/ --fix
```

---

## 🔧 Development Setup

```bash
git clone https://github.com/your-org/red-pill
cd red-pill
uv sync                         # Installs all deps including argon2-cffi, dev tools
uv run pytest tests/            # All tests must pass
uv run mypy src/red_pill/       # No type errors allowed
uv run ruff check src/ tests/   # Sound of Silence — zero warnings
```

---

## 🧪 Test Requirements

- All new features must include tests.
- Coverage gate: **≥ 80%** (`--cov-fail-under=80` in CI).
- Do not mock what you can test directly. Do mock external I/O (Qdrant, Google Drive, subprocesses).
- Tests live in `tests/`. Integration tests requiring Docker go in `tests/integration/`.

---

## ✅ PR Checklist

Before opening a PR, confirm:

- [ ] `uv run ruff check src/ tests/ scripts/` — clean
- [ ] `uv run mypy src/red_pill/` — no errors
- [ ] `uv run pytest tests/` — all pass
- [ ] New code has tests
- [ ] Docstrings updated if public API changed
- [ ] `CHANGELOG.md` entry added under `[Unreleased]`
- [ ] No secrets, PII, or personal paths in the diff

---

## 🎭 Lore & Terminology

The project uses Matrix/Cyberpunk/Dune lore extensively (`Bünker`, `Gru`, `Smith`, `The 770 Pact`). This is intentional and will not change for enterprise compatibility reasons. If you're contributing, you don't need to use the lore in your code comments — plain English is fine — but please don't rename the existing lore-named components.

---

## 📋 Code Style

- **Tabs**, not spaces (see above).
- Line length: 120 characters max.
- Type hints required on all public functions.
- `logger = logging.getLogger(__name__)` in every module that logs.
- No `print()` in library code — use `logger.*`.

---

## 📬 Reporting Security Issues

See [SECURITY.md](SECURITY.md). Do **not** open public issues for security findings.
