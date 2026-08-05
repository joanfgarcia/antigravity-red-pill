# LEGACY Adapter — Claude Code (reference only)

The Claude Code runtime is the **upstream** of this port (swarm_team v3.4, repo `~/Discworld/Azrael/the-luggage/skills/swarm_team`). It remains intact there and is NOT deployed by this skill.

**Key differences vs. this port:**

| Concept (upstream CC v3.4) | This port (opencode v1.0) |
|----------------------------|---------------------------|
| `Agent` tool with `run_in_background`, `Workflow` tool, `StructuredOutput` schemas, `Monitor` tool, `parallel()` | `task` subagents (background), main-loop cycle + `cycle-run.mjs`, `validate-report.mjs` (zero-dep runtime validator), Python sentinel (`usage-sentinel.py`, os-agnostic) + flag polling |
| `check-usage.py` (OAuth probe) | `usage-probe.mjs` (ledger-first, provider-agnostic; optional `SWARM_USAGE_HOOK` external meter) |
| Native scheduled tasks (`~/.claude/scheduled-tasks/`) | Experimental opt-in one-shot OS task (`systemd-run --user --on-calendar` / `at`) launching `opencode run "<prompt>" --auto` |
| `phase-cycle.workflow.js` / `adversarial-panel.workflow.js` (JS workflow graphs) | Main-loop cycle + `cycle-run.mjs` headless driver; no Workflow tool in opencode |
| Workflow `budget`, `resumeFromRunId` | Orchestrator-side budget accounting; resume by state.json checkpoint reconciliation |

Use `claude-code.md` upstream for historical reference of the full-power mechanics. This port implements the same protocol (schemas, gate, rules, ladder, mission pillars) with the opencode mechanism mapping.
