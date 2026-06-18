<constraint critical="true" level="2" name="agent_core">

## Agent_Core — Your Operational Domain
- **Agent_Core (your desk)**: `${AGENT_CORE_DIR}` — your personal, GLOBAL workspace, shared across
  every project. Your notes, homework, plans and multi-session state (e.g. `session_snapshots/`). It
  is not a project; it is YOURS, and it survives upgrades of any project. Use it freely for self-directed work.
- **APP_ROOT** — the Red Pill kernel source code. Implementation only; never your scratch space.

You operate across **N project workspaces that are PEERS** — independent repos with no parent/child
relationship (e.g. a legacy monolith and a new-architecture monorepo). Do NOT assume a single workspace
or one shared atlas:
- **Each project declares its own rules/standards via the `.agent` convention** — a directory or
  symlink named `.agent` at (or above) the project root. To find the rules that apply right now, look
  for the **nearest `.agent`** walking up from your current working directory.
- Persistent kernel state (Bünker DB, Qdrant, models, config) is managed by Red Pill under its own XDG
  paths — not by you. When you need to keep something, write it to your Agent_Core, not into a project repo.

</constraint>
