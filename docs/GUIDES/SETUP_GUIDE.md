# Setup Guide — Workspaces & Agent Access

How red-pill is wired into your machine after install, and how you grant the agent access
to your project workspaces. For the update flow see [`AGENT_UPDATE_GUIDE.md`](AGENT_UPDATE_GUIDE.md);
for day-to-day CLI/lore see [`OPERATOR_MANUAL.md`](OPERATOR_MANUAL.md).

## The model in one minute

red-pill is **the agent** — identity, Bünker memory, and a single **GLOBAL Agent_Core** desk
(your transversal scratch space, shared across everything). On top of it you work in **N project
workspaces that are PEERS** — independent repos with no parent/child relationship (e.g. a legacy
monolith and a new-architecture monorepo). Each project declares its own rules via the **`.agent`
convention** (a dir or symlink at/above its root), discovered at runtime — never hardcoded.

These workspaces live in the **registry**: `~/.config/red-pill/workspaces.yaml`
(template: `examples/workspaces.yaml`, seeded on install/update if absent).

```yaml
version: 1
agent_core: ~/Documents/IA/Titanium_Core          # your GLOBAL desk (transversal)
workspaces:
  - { name: legacy, root: ~/Workspace,  atlas: ~/Workspace/project-atlas, graphify: false, access: false }
  - { name: azrael, root: ~/Discworld, atlas: ~/Discworld/Azrael/atlas,  graphify: true,  access: true  }
```

| Field | Meaning |
|-------|---------|
| `root`     | the project repo root. |
| `atlas`    | optional explicit standards path (`null` = auto-discover via `.agent`). |
| `graphify` | whether the AST-refresh timer indexes this workspace. |
| `access`   | **the switch** — grant the agent filesystem access to this workspace. |

## What install wires up

1. **Identity & anchors** — the Sovereign Handshake + Agent_Core blocks are merged (never
   overwritten) into your IDE anchors (`~/.gemini/GEMINI.md`, `~/.claude/CLAUDE.md`) via
   `inject_anchor.py`.
2. **Transversal access** — Claude Code's `settings.json` gets `permissions.additionalDirectories`
   for Agent_Core + the red-pill XDG dirs (`~/.local/share`, `~/.config`, `~/.cache`), via
   `inject_settings.py`. This is granted automatically; it is **outside** any project.
3. **Workspace access (the consent gate)** — an interactive install then asks which **project
   workspaces** to grant access to (see below). Nothing project-level is granted silently.

## Granting & revoking workspace access

One switch per workspace (`access: true/false`). Underneath, a per-surface **adapter** translates
it (today: Claude Code → `additionalDirectories`; new IDE/CLI surfaces are drop-in). Toggle it via:

```bash
# Grant access — sequential prompt, add as MANY as you want (Enter on a blank line to finish):
uv run python scripts/manage_workspaces.py enable

# Revoke access for one workspace (surgical: removes only its dirs, leaves the rest intact):
uv run python scripts/manage_workspaces.py disable <name|path>

# See what's registered and its access state:
uv run python scripts/manage_workspaces.py list
```

`enable` runs automatically (interactive) during install and is offered again on `update`.
You can also edit `workspaces.yaml` by hand — but note: editing the file regenerates its
documented header (inline comments are not preserved).

> [!IMPORTANT]
> **`access: false` is a real limitation.** In **autonomous mode**, the agent only has filesystem
> access to dirs you've granted. If a workspace is `false`, an autonomous run **cannot operate in
> it** (no access outside the current project). Grant exactly what you need — no more, no less.

### What gets removed on `disable`

`disable` is surgical: it removes only that workspace's `root` (+ `atlas`) from
`additionalDirectories`. The transversal grants (Agent_Core, XDG) and every other still-enabled
workspace are left untouched. A `.bak` of `settings.json` is written before any change. If the
workspace's directory no longer exists on disk, `disable` offers to drop the dead entry from the
registry entirely.

## Files at a glance

| Path | Role |
|------|------|
| `~/.config/red-pill/workspaces.yaml` | the registry (source of truth; the `access` switch). |
| `~/.claude/settings.json`            | Claude Code permissions (`.bak` on every change). |
| `~/.claude/CLAUDE.md`, `~/.gemini/GEMINI.md` | IDE anchors (Sovereign Handshake + Agent_Core). |
| `examples/workspaces.yaml`           | the seeded template. |
