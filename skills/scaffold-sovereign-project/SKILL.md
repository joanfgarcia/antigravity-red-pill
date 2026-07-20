---
name: scaffold-sovereign-project
description: Automatically scaffolds a new Red-Pill ecosystem project with strict architectural conventions and the Protocol of Silence.
---

# Scaffold Sovereign Project

This skill enforces the strict topological map and conventions of the Red-Pill ecosystem when bootstrapping a new codebase. It must be executed whenever the user requests the creation of a new project, library, or repository.

## When to use this skill

* When the user asks to "create a new project", "initialize a repo", "hazme un scaffold", or similar requests indicating the birth of a new codebase in the Red-Pill ecosystem.

## How to use it

To properly execute this skill, follow these exact steps sequentially:

1. **Initialization:**
   - Execute `uv init` in the designated project folder.
   - Wait for the initialization to complete.

2. **Directory Structure Enforcement:**
   - Create the required root-level folders: `mkdir -p docs/CORE docs/CERTIFICATION src tests scripts .agent`
   - Copy the initial Cognitive Anchor from this skill's templates:
     `cp <SKILL_DIR>/templates/ATLAS.md ./.agent/ATLAS.md`

3. **Conventions Injection:**
   - Copy the master conventions file to the project:
     `cp <SKILL_DIR>/templates/CONVENTIONS.md ./CONVENTIONS.md`
   - Use `sed` or file replacement tools to replace `pure-mls` (or the previous template name) with the current project's name inside `CONVENTIONS.md`.
   - Copy the GNU GPLv3 License:
     `cp <SKILL_DIR>/templates/LICENSE ./LICENSE`
   - Copy the Protocol of Silence:
     `cp <SKILL_DIR>/templates/PROTOCOL_OF_SILENCE.md ./docs/CORE/PROTOCOL_OF_SILENCE.md`
   - Copy the CHANGELOG template:
     `cp <SKILL_DIR>/templates/CHANGELOG.md ./CHANGELOG.md`

4. **Protocol of Silence (Linter & Tests Configuration):**
   - Append the strict `ruff`, `mypy`, and `pytest` configuration (with 96% coverage threshold) to `pyproject.toml`. Copy from `<SKILL_DIR>/templates/pyproject_silence.toml`.
   - Ensure the required dependencies (`ruff`, `mypy`, `pytest`, `pytest-asyncio`, `pytest-cov`) are added to the `[dependency-groups] dev` section using `uv add --dev ruff mypy pytest pytest-asyncio pytest-cov`.
   - Copy the Linter test enforcer:
     `cp <SKILL_DIR>/templates/test_sound_of_silence.py ./tests/test_sound_of_silence.py`

5. **First Sovereign Commit & Hooks:**
   - Run `git init` (if not already initialized).
   - Install branch protection (no force-push) and commit-message formats:
     `cp <SKILL_DIR>/templates/pre-push .git/hooks/pre-push`
     `cp <SKILL_DIR>/templates/commit-msg .git/hooks/commit-msg`
     `chmod +x .git/hooks/pre-push .git/hooks/commit-msg`
   - Setup GitHub Actions CI:
     `mkdir -p .github/workflows`
     `cp <SKILL_DIR>/templates/ci.yml .github/workflows/ci.yml`
   - Setup Gitignore:
     `cp <SKILL_DIR>/templates/gitignore .gitignore`
   - Run `git add .`
   - Run `git commit -m "chore: initial sovereign scaffold"`
   - Notify the user that the project has been built according to the Red-Pill standards and is ready for development.
