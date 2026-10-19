# Governance Directive: Session Snapshots

## Context
Continuity across context windows / model switches: the agent keeps a structured
snapshot of the **workspace** state so a new session resumes without loss.

## Execution Rules

1. **Snapshot generation**: at the end of a session, on "guarda el contexto /
   snapshot / handoff", or when context gets heavy, invoke the `context-distiller`
   skill. Output: **one** file at `<workspace>/.red-pill/memory/session_snapshot.md`
   (workspace-memory). **Never** write to `.agent/` or to project source trees.
2. **No obfuscation.** Identity is **config of the instance** (see
   `docs/CORE/IDENTITY_AND_INSTANCE.md`): the snapshot is technical and honest and
   never sanitizes, hides, or rewrites the agent/operator identity or lore terms.
   There is no "silence protocol" here.
3. **Structure**: terms/aliases (optional), affected modules, decision log (durable,
   non-obvious changes and why), and the **final frontier** (exact state +
   blockers/open decisions). Point to artifacts (RFC, shard, commit) instead of
   copying them.
4. **Plane separation**: project markdown files hold **technical** data; social /
   relational / personal data lives in the RAG (Bünker), never in project files.

## Verification
On resuming, read `session_snapshot.md` to reconstitute state; the kernel **OPEN
LOOPS** digest covers the pending decisions/jobs/notes counts.
