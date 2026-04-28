---
name: skill_creation
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

### 1. Structure Design
Decide if the skill is global (`~/.gemini/antigravity/skills/`) or project-specific (`.agent/skills/`).

### 2. Directory Creation
Create the folder:
`mkdir -p <skills-path>/<your-skill-name>`

### 3. Writing SKILL.md
Create the `SKILL.md` file with the required contents:
*   **YAML Frontmatter**: `name` and `description`.
*   **Documentation**: Detailed instructions, "When to use", and "How to use".

### 4. Verification
Verify the skill is correctly placed and follows the mandatory formatting rules. Provide a summary to the user after creation.
