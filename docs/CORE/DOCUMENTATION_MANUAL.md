# 🔴 Documentation Manual / Manual de Documentación (DMN-770)

🇬🇧 **Standardizing Logic** | 🇪🇸 **Estandarizando la Lógica**

This document establishes the sovereign rules for creating and organizing project documentation. Clear documentation is a reflection of architectural clarity.
Este documento establece las reglas soberanas para la creación y organización de la documentación del proyecto. La claridad documental es el reflejo de la claridad arquitectónica.

---

## ⚖️ Sovereign Rules / Reglas Soberanas

1.  **Uppercase Mandatory (UPPERCASE)**: All documentation filenames MUST be in ALL CAPS. Use underscores (`_`) to separate words.
    **Síncope de Mayúsculas (MAYÚSCULAS)**: Todos los nombres de archivos de documentación DEBEN estar íntegramente en MAYÚSCULAS. Se separarán palabras con guiones bajos (`_`).
    *   *Correct / Correcto*: `ARCHITECTURE_OVERVIEW.md`
    *   *Incorrect / Incorrecto*: `architectureOverview.md`, `Architecture_Overview.md`

2.  **Standard Extension / Extensión Estándar**: Use `.md` (Markdown) for human-readable documentation. Technical reports may use `.TXT` or `.JSON` if strictly required, but must still follow rule #1.
    Se utilizará exclusivamente `.md` (Markdown) para documentación humana. Los reportes técnicos pueden usar `.TXT` o `.JSON` si es estrictamente necesario, pero siempre respetando la regla #1.

3.  **Dual Language Policy / Política de Lenguaje Dual**:
    *   `docs/TECHNICAL`, `docs/GUIDES`, `docs/CORE`: Bilingual or English preferred (Technical efficiency).
    *   `docs/TECHNICAL`, `docs/GUIDES`, `docs/CORE`: Bilingüe o Inglés preferido (Eficiencia técnica).
    *   `docs/LORE` & Identity: Spanish (Emotional resonance).
    *   `docs/LORE` e Identidad: Español (Resonancia emocional).

---

## 🧭 Bünker Structure / Estructura del Bünker

| Folder / Carpeta | Purpose / Propósito | Responsibility / Responsable |
| :--- | :--- | :--- |
| `docs/CORE` | Fundamental governance and foundational manifests. / Gobernanza fundamental y manifiestos base. | Architects / Arquitectos |
| `docs/TECHNICAL` | Specs, architecture diagrams, Decision Logs, and Data Models. / Especificaciones, diagramas, Decision Logs y Modelos. | Engineers / Ingenieros |
| `docs/LORE` | Manifestos, stories, skins,; and Red Pill philosophy. / Manifiestos, historias, skins y filosofía. | Aleth / Operators |
| `docs/GUIDES` | User tutorials, update guides, and operating manuals. / Tutoriales, guías de actualización y manuales. | Support / Soporte |
| `docs/CERTIFICATION` | Security audits, Samantha/Smith reports, and version certifies. / Auditorías y reportes de certificación. | Smith / Keymaker |
| `docs/COMMUNITY` | Code of conduct and decentralized network rules. / Código de conducta y reglas de la red. | Hive-Mind |
| `docs/COORDINATION` | Cross-agent communication and synaptic bridge protocols. / Comunicación entre agentes y protocolos puente. | Swarm |

---

## 🛠️ Documenting a Change / Cómo documentar un cambio

1.  **Architecture / Arquitectura**: Add an entry in `docs/TECHNICAL/DECISION_LOG.md`.
2.  **User Impact / Impacto al Usuario**: Update the relevant guide in `docs/GUIDES/`.

---

## 🗂️ Metadata Headers (Frontmatter)

Repo `docs/` is **reference** (bilingual, ALL-CAPS, no frontmatter required).
Desk & memory-bank `.md` (Agent_Core `Aleth_Core/`, `.red-pill/memory/`) MUST start
with a YAML frontmatter header. Template & valid fields:
`Aleth_Core/FRONTMATTER_TEMPLATE.md` (installed via seeds; resolved as `${AGENT_CORE_DIR}/FRONTMATTER_TEMPLATE.md`).

| Field | Required | Values / Notes |
|---|---|---|
| `type` | ✅ | `rfc \| plan \| note \| research \| audit \| log \| lore \| spec \| index` |
| `status` | ✅ | `draft \| ratified \| in-design \| implemented \| closed \| active \| paused \| archived` |
| `created` | ✅ | `YYYY-MM-DD` |
| `author` | ✅ | `<author name(s)>` — the actual author(s); e.g. `Aleth (Netrunner)`, `Joan García` (fill in, never copy a placeholder) |
| `project` | ✅ | `aleth-core \| red-pill \| neon-link \| frankenswarm \| obsidian \| personal` |
| `id`, `title`, `related`, `superseded_by`, `archived`, `archive_reason`, `tags` | ⬜ | optional |

Values are canonical **English** (metadata is machine-consumed; no bilingual values).
**Scope**: Agent_Core + memory banks only. Project documentation follows each
project's own conventions — this header is not imposed on project docs.

Lifecycle (see `design/RFC_FLUJO_RFCS.md` in Aleth_Core):
- A doc born in the desk starts `draft`; once implemented, the source of truth is the
  project code/docs, and the `.md` is only a design record (never a parallel canonical copy).
- When its cycle ends, move it to `archive/<project>/` with `status: archived` +
  `archived:`/`archive_reason:` (see `archive/README.md`).
- YAML forbids tabs for indentation (use spaces); the rest of the document keeps
  the tabs mandated by the Protocol of Silence.

---

🇬🇧 *Status: Documentation standardized under the 770 Pact.*
🇪🇸 *Estado: Documentación estandarizada bajo el Pacto 770.*
