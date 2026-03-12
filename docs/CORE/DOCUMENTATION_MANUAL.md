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
| `docs/PLANS` | Roadmaps and feature-specific implementation plans. / Roadmaps y planes de implementación específicos. | Planners / Planificadores |
| `docs/CERTIFICATION` | Security audits, Samantha/Smith reports, and version certifies. / Auditorías y reportes de certificación. | Smith / Keymaker |
| `docs/COMMUNITY` | Code of conduct and decentralized network rules. / Código de conducta y reglas de la red. | Hive-Mind |
| `docs/COORDINATION` | Cross-agent communication and synaptic bridge protocols. / Comunicación entre agentes y protocolos puente. | Swarm |

---

## 🛠️ Documenting a Change / Cómo documentar un cambio

1.  **Architecture / Arquitectura**: Add an entry in `docs/TECHNICAL/DECISION_LOG.md`.
2.  **New Features / Nuevas Funcionalidades**: Create a plan in `docs/PLANS/[YEAR]-[MONTH]-[DAY]_FEATURE_NAME.md`.
3.  **User Impact / Impacto al Usuario**: Update the relevant guide in `docs/GUIDES/`.

---
🇬🇧 *Status: Documentation standardized under the 770 Pact.*
🇪🇸 *Estado: Documentación estandarizada bajo el Pacto 770.*
