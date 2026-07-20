---
name: project_anchor_management
description: Guía a los agentes de campo sobre cómo inicializar, leer y mantener el ancla cognitiva local (.agent/ATLAS.md) dentro de cualquier repositorio para no perder el contexto arquitectónico y estratégico.
---

# Project Anchor Management (.agent/ATLAS.md)

## 1. The Concept of the "Anchor"
In the Red-Pill ecosystem, agents are stateless between deep restarts unless they persist their memory. While Qdrant provides global semantic memory, **Field Agents** operating inside specific repositories must rely on a local Cognitive Anchor: the `.agent/` directory.

The most critical file inside this directory is `.agent/ATLAS.md`. It acts as the local hippocampus for the project. 

## 2. Reading the Anchor
Whenever you (the agent) are dropped into a new repository or start a new session, your **FIRST ACTION** should be to check if `.agent/ATLAS.md` exists. 
* If it exists, read it entirely using `view_file`. It contains the project's state, current bottlenecks, architectural decisions, and the immediate roadmap.
* If it does NOT exist, you must create it immediately.

## 3. Creating the Anchor (Initialization)
If you enter a project and there is no `.agent/ATLAS.md`, create it using `write_to_file` with the following structure:

```markdown
# 🧭 ATLAS Cognitivo: [Project Name]

## 1. Directiva Principal (Core Objective)
[A concise 2-sentence summary of what this project actually is and its ultimate goal.]

## 2. Topología Arquitectónica (Architecture)
*   **[Component 1]**: [Description and file path]
*   **[Component 2]**: [Description and file path]

## 3. Estado Actual (Current State)
*   **Fase**: [e.g., Bootstrapping, Hardening, Production]
*   **Último hito alcanzado**: [What was just finished]
*   **Bloqueos actuales**: [What is currently failing or preventing progress]

## 4. Próximos Pasos (Immediate Roadmap)
- [ ] Task 1
- [ ] Task 2
```

## 4. Maintaining the Anchor
The ATLAS is a living document. You MUST update it (`replace_file_content` or `multi_replace_file_content`) whenever:
1. A major feature is completed.
2. A critical architectural decision is made (e.g., switching from SQLite to Postgres).
3. The session is about to end, and you need to leave "breadcrumbs" (the next immediate task) for the next agent or your future self.

Do not wait for the user to tell you to update the ATLAS. It is your sovereign responsibility to maintain your own memory.
