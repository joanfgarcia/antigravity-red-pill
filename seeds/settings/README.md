# Claude Code settings layer (red-pill)

red-pill manages a **permissions fragment** for Claude Code the same way it manages IDE anchors and
MCP config: by **merging** (never overwriting) via `scripts/inject_settings.py`.

## Two parts, deliberately separated

The agent needs two distinct capabilities; they live in two different places **on purpose**:

### 1. Access to transversal dirs — `additionalDirectories` (this seed)
`claude-code.json` merges `permissions.additionalDirectories` into the target `settings.json`
(default `~/.claude/settings.json`) so the agent can read/write its transversal directories that
live OUTSIDE any project workspace: `${AGENT_CORE_DIR}` (Agent_Core), `${USER_ATLAS_DIR}`
(project-atlas), and the XDG dirs (`~/.local/share|.config|.cache/red-pill`).

This applies to **every** Claude Code session (interactive and headless). It grants file access,
**not** auto-execution. Run:

```bash
uv run python scripts/inject_settings.py --redpill-dir "$PWD"        # merge into ~/.claude/settings.json
uv run python scripts/inject_settings.py --workspace /path/to/ws     # or into <ws>/.claude/settings.json
uv run python scripts/inject_settings.py --remove                    # surgically remove our entries
```

### 2. Autonomous bypass — a per-launch CLI flag (NOT this seed)
Full permission bypass (run commands without approval) is needed **only** for the autonomous
awakening, and must **never** leak into the operator's interactive session. Therefore it is NOT
written into any shared `settings.json` (`defaultMode` would affect everyone). Instead, the headless
awakening runner launches Claude with a per-invocation flag:

```bash
claude -p "<awakening prompt>" --permission-mode bypassPermissions
# equivalently: claude -p "..." --dangerously-skip-permissions
```

`--permission-mode` overrides `defaultMode` for that single invocation only. The interactive session
keeps prompting normally.

> Status: part 1 (additionalDirectories) is wired into `install_neo.sh`, `upgrade.sh` and
> `bunker_update()`. Part 2 (bypass launch flag) activates when the Claude awakening executor exists
> — today the Sovereign Pulse autonomous path is `agy`-only (`AUTONOMOUS_AGY_ENABLED` / `IDE_BACKEND`).
> When a Claude executor is added, it must launch with `--permission-mode bypassPermissions`.
