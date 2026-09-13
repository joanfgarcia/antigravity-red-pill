---
name: skill-creation
description: Allows the agent to create new skills to extend its capabilities. MUST ask for user authorization before creating any new skill.
---

# Skill Creation Skill

This skill provides a structured way for the agent to identify, design, and implement new "skills" as documented in the Antigravity developer guides.

## When to use this skill

*   When you identify a recurring complex task that could benefit from a structured protocol.
*   When a new capability is needed that isn't covered by existing tools or workflows.
*   When you want to codify best practices for a specific domain or technology.

## Mandatory Step: Authorization

**CRITICAL**: Before creating any new directory or file for a skill, you MUST seek explicit authorization from the user.

1.  Identify the need for a new skill.
2.  Formulate a brief proposal:
    *   **Name**: Proposed folder name (lowercase-with-hyphens).
    *   **Description**: What the skill will do and why it's useful.
    *   **Scope**: Global or Project-specific.
3.  Use `notify_user` to present this proposal and wait for a "yes" or "approved" before proceeding.

## How to use it

Once authorized, follow these steps:

### 0. Naming Convention (mandatory — Agent Skills standard)

The skill name MUST satisfy ALL of these rules. No exceptions:

*   **kebab-case only**: lowercase `a-z`, digits `0-9`, hyphens `-` only. Underscores (`_`), uppercase, and spaces are FORBIDDEN.
*   **Length**: 1–64 characters.
*   **No leading/trailing hyphens** (`-foo`, `foo-` invalid).
*   **No consecutive hyphens** (`foo--bar` invalid).
*   **Directory MUST match frontmatter**: `<skills-path>/<name>/SKILL.md` must declare `name: <name>` with the EXACT same string. The Agent Skills standard requires it; opencode enforces it; PI warns (`name contains invalid characters`) and tolerates dir/name mismatch but that produces `[Skill conflicts]` warnings across shared directories.
*   **`description` required, non-empty, ≤1024 chars** (drives progressive disclosure).

Valid: `pdf-processing`, `job-manager`, `workspace-memory`
Invalid: `job_manager`, `PDF-Processing`, `-pdf`, `pdf--processing`

If the skill invokes the red-pill CLI, reference it through the `${RED_PILL_CMD}` placeholder (resolved at seeding per harness — the CLI is NOT on the PATH; the standard invocation is `uv run --no-sync --project <REDPILL_DIR> red-pill`).

### 1. Structure Design
Decide if the skill is global (`~/.gemini/antigravity/skills/`), IDE-specific (`seeds/<ide>/skills/`), or project-specific (`.agent/skills/`). Generic skills live in `skills/`; a skill exists in only ONE layer unless an IDE genuinely needs an override (then the IDE-specific copy wins in that harness).

### 2. Directory Creation
Create the folder:
`mkdir -p <skills-path>/<your-skill-name>`

### 3. Writing SKILL.md
Create the `SKILL.md` file with the required contents:
*   **YAML Frontmatter**: `name` (kebab-case, == directory) and `description` (non-empty, ≤1024 chars).
*   **Documentation**: Detailed instructions, "When to use", and "How to use".

### 4. Verification
Verify ALL of the following before reporting success:
1.  Directory name matches frontmatter `name` exactly (kebab-case).
2.  `name` passes the Naming Convention rules in step 0.
3.  Frontmatter has a non-empty `description` (max 1024 chars).
4.  If it references the red-pill CLI, it uses `${RED_PILL_CMD}` (never bare `red-pill`).
5.  (PI present) Load it with PI's own loader: `node -e "import('@earendil-works/pi-coding-agent/dist/index.js').then(({loadSkillsFromDir}) => console.log(loadSkillsFromDir({dir: '<parent>', source:'x'}).diagnostics))"` → zero warnings.
Provide a summary to the user after creation.
