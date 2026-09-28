<constraint critical="true" level="2" name="frontmatter_docs">

## Frontmatter in Markdown documents (Agent_Core & memory banks)
Every Markdown document created or edited in **Agent_Core** (`${AGENT_CORE_DIR}`) or in a
memory bank (`.red-pill/memory/`, distilled memory docs) MUST start with a YAML frontmatter
header. Template and field reference: `${AGENT_CORE_DIR}/FRONTMATTER_TEMPLATE.md`.
1. **Mandatory fields**: `type`, `status`, `created`, `author`, `project`.
2. **Status** (canonical English): `draft | in-design | ratified | in-progress | blocked | paused | implemented | closed | active | archived`.
   - `blocked` y `paused` **exigen `reason:` obligatorio** (p.ej. "esperando otro RFC"); sin `reason`, el documento está incompleto. `blocked` = impedido por otra pieza; `paused` = pausado por decisión propia.
   - `ready` **no es un estado**: "decisiones cerradas, listo para implementar" es `ratified` (AWAKEN-002 §4.2 A-3). El vocabulario puede variar por fase del planner (ver `FRONTMATTER_TEMPLATE.md`).
3. **Lifecycle**: when a document finishes its cycle, move it to `archive/<project>/`
   and set `status: archived` + `archived:`/`archive_reason:` (see `archive/README.md`).
4. **Single source of truth**: if the project code/docs already document the feature,
   the `.md` is only a design record — never keep parallel canonical copies.
5. **Scope**: Agent_Core + memory banks only. Project documentation follows each
   project's own conventions; do not impose this header there.

</constraint>