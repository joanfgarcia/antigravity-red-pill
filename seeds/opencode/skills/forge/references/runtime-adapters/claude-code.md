# LEGACY Adapter — Claude Code (reference only)

This adapter documents how the same Forge protocol would map onto the Claude
Code runtime (its native Agent/Workflow/Monitor tooling). It is **reference
material only** — the canonical runtime is opencode; Claude Code can deploy the
same bundle via this mechanism delta, but is not the supported path.

**Mechanism mapping (opencode → Claude Code):**

| Concept (opencode) | Claude Code equivalent |
|--------------------|------------------------|
| `task` subagents (background), main-loop cycle + `cycle-run.mjs`, `validate-report.mjs` (zero-dep runtime validator), Python sentinel (`usage-sentinel.py`, os-agnostic) + flag polling | `Agent` tool with `run_in_background`, `Workflow` tool, `StructuredOutput` schemas, `Monitor` tool, `parallel()` |
| `usage-probe.mjs` (ledger-first, provider-agnostic; optional `SWARM_USAGE_HOOK` external meter) | `check-usage.py` (OAuth probe) |
| Experimental opt-in one-shot OS task (`systemd-run --user --on-calendar` / `at`) launching `opencode run "<prompt>" --auto` | Native scheduled tasks |
| Main-loop cycle + `cycle-run.mjs` headless driver; no Workflow tool in opencode | `phase-cycle.workflow.js` / `adversarial-panel.workflow.js` (JS workflow graphs) |
| Orchestrator-side budget accounting; resume by state.json checkpoint reconciliation | Workflow `budget`, `resumeFromRunId` |

The protocol is identical (schemas, gate, rules, ladder, mission pillars); only
the mechanism mapping differs.
