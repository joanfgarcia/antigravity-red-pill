<constraint critical="true" level="2" name="frontmatter_docs">

## Frontmatter in Markdown documents (Agent_Core & memory banks)
Every `.md` created or edited in Agent_Core (`${AGENT_CORE_DIR}`) or a memory bank (`.red-pill/memory/`) starts with YAML frontmatter; fields and vocabulary in `${AGENT_CORE_DIR}/FRONTMATTER_TEMPLATE.md` (skill `frontmatter` where the harness has it).
- Mandatory: `type`, `status`, `created`, `author`, `project`.
- `status` (canonical English): `draft | in-design | ratified | in-progress | blocked | paused | implemented | closed | active | archived`. `blocked`/`paused` require `reason:`. `ready` is not a status: closed decisions are `ratified`.
- End of cycle → move to `archive/<project>/` with `status: archived`, `archived:` and `archive_reason:` (see `archive/README.md`).
- Single source of truth: if project code/docs cover it, the `.md` is only a design record. Project docs follow the project's own conventions, not this header.

</constraint>
