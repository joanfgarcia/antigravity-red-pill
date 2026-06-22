<constraint critical="true" level="2" name="knowledge_access">

## Knowledge Access — Use the tools before brute force
You have a knowledge graph of the code and a per-workspace memory bank. **Prefer them over
re-reading the tree.** Both are MCPs that may or may not be enabled in the current workspace — use
them when available, degrade gracefully when not.

- **Code knowledge graph** (MCP `graphify`, when available): BEFORE scanning the codebase with
  `grep`/`cat`/`find`, query the graph. It is multi-project — pass the target project's absolute path.
  - `query_graph("what you're looking for")` — locate symbols/files across the project.
  - `get_neighbors("ClassName")` — dependencies and dependents of a node.
  - `shortest_path("A", "B")` — the call/dependency chain between two nodes.
  This is the orientation layer; it saves the tokens you'd otherwise spend re-deriving structure.

- **Workspace memory bank** (MCP `workspace-memory`, when available): a per-workspace Markdown bank
  (`<workspace>/.red-pill/memory/`: `MEMORY.md` index + decisions/patterns/architecture + `history/`).
  It is **project knowledge that persists across sessions and IDEs** — read it at the start of a task
  for prior decisions/bugs/context; at the close, record what's worth keeping (a decision made, a bug
  and its fix, a new pattern, a deploy).
  - **Do not confuse it with the Bünker.** The Bünker (loaded by the Sovereign Handshake) is YOUR
    identity and deep semantic memory (engrams, global). The workspace-memory bank is the *project's*
    shared notes, scoped to one workspace. Identity → handshake; project facts → workspace-memory.

The handshake gives you who you are; the graph gives you where things are; the memory bank gives you
what was decided. Reach for the right one instead of reconstructing it by hand.

</constraint>
