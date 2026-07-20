---
name: agent_core
description: Use when the session mentions agent_core, aleth_core, workspace root, peer workspaces, project rules, .agent directory, or transversal state. This skill establishes the agent's operational domain boundaries across independent project repos.
---

## Agent_Core Operational Domain
- **Agent_Core** (your desk): `${AGENT_CORE_DIR}` — personal, global workspace shared across all projects. Use it for notes, plans, and transversal/session state.
- **APP_ROOT**: Red Pill kernel code repository. No scratch files here.
- **Peer Workspaces**: You operate across independent project repos. Do NOT assume one workspace:
  - Each project declares rules via nearest `.agent/` directory walking up from CWD.
  - Kernel state (Qdrant, Bünker DB, models) is managed by Red Pill. Save personal/transversal items in Agent_Core, never in project repos.
