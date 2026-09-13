# Frontmatter Template — Agent_Core Desk & Memory Banks

Every Markdown document in the desk (`${AGENT_CORE_DIR}`) or in a memory bank
(`.red-pill/memory/`, distilled memory docs) starts with a YAML metadata header
(Obsidian-compatible), delimited by `---` at the top of the file. It lets a
newcomer (or the Operator after months away) know at a glance **what the doc is,
its state, which project owns it, and where its source of truth lives**.

> **Scope**: the desk + memory banks only. **Project documentation is governed
> by each project's own conventions** — do not impose this header there.

> **Source of truth**: this file is seeded from `seeds/desk/FRONTMATTER_TEMPLATE.md`
> in the red-pill repo. The desk copy is the live instance; the seed is canonical
> and propagates convention updates on install (copy-if-absent / merge).

## Fields

```yaml
---
type: rfc|plan|note|research|audit|log|lore|spec|index|task
id: RFC-XXX                     # optional: formal identifier if it has one
title: Document title
codename: Internal name         # optional
status: draft                   # see status list below
priority: Medium                # optional: High | Medium | Low (planner items)
depends_on:                     # optional: relative paths of items that must close first
  - ../pending/OTHER.md
created: 2026-08-06
updated: 2026-09-04
author: <Author Name(s)>            # fill with the real author(s); see note below
project: aleth-core|red-pill|neon-link|frankenswarm|obsidian|personal
related:                        # optional: relative paths to connected docs
  - planner/design/governance/RFC_ORGANIZACION_DOCUMENTAL.md
superseded_by:                  # optional: path of the doc that supersedes it
archived: 2026-09-04            # optional: archive date (see archive/)
archive_reason:                 # optional: why it was archived
tags: []
---
```

## Valid `type` values

`rfc | plan | note | research | audit | log | lore | spec | index | task`

(`bitacora` → `log`; `spec` for versioned specs; `index` for navigation docs;
`task` for planner items in `planner/`.)

## Valid `status` values

El vocabulario de estados depende de la **fase** del ítem en el planner
(ver `planner/README.md`). Estados generales:

| Status | Meaning |
|---|---|
| `draft` | Born in the desk, decisions open (see `planner/design/governance/RFC_FLUJO_RFCS.md`) |
| `ratified` | Business decisions closed, ready to implement |
| `in-design` | Design in progress, iterating with the Operator |
| `implemented` | Code merged in the target project |
| `closed` | Verified live + PRs merged + dependencies released |
| `active` | Living document (index, log, research notebook) |
| `archived` | Lifecycle over; lives in `archive/` (see `archive/README.md`) |

### Estados por fase del planner

| Fase (carpeta) | Status válidos | RFC de referencia |
|---|---|---|
| `planner/ideas/` | `spark`, `llama` | `RFC_DOSSIER_IDEACION.md` §3.1 |
| `planner/research/` | `maturing`, `awaiting_operator`, `parked`, `dead`, `superseded` | `RFC_DOSSIER_IDEACION.md` §3.2 |
| `planner/design/` | `draft`, `in-design`, `ratified` | `RFC_FLUJO_RFCS.md` §2.2 |
| `planner/pending/` | `pending` | (equivalente a cola PENDING) |
| `planner/in_progress/` | `in-progress`, `implemented` | `RFC_FLUJO_RFCS.md` §2.2 |
| `archive/` | `archived`, `closed` | `RFC_FLUJO_RFCS.md` §2.2 |

## Rules

- Mandatory fields: `type`, `status`, `created`, `author`, `project`.
- `priority` and `depends_on` are optional but **recommended** for planner items
  (see `planner/README.md`): `priority` in `High | Medium | Low`;
  `depends_on` lists relative paths that must close first (topological order in the panel).
- `author` holds the **actual author(s) of the document** — write the real name(s),
  e.g. `Aleth (Netrunner)`, `Joan García`, or both `Aleth (Netrunner) / Joan García`.
  **Never copy a placeholder**: if you are not one of the listed names, replace it.
- `project` names the canonical source of truth: if it is `red-pill`, the code
  wins; the `.md` is only a design record.
- `related` entries are relative paths from the desk root.
- An archived document must have `status: archived` plus `archived:`/`archive_reason:`.
- Personal `.md` in the Vault (novels, finances, Hotetec) may omit `project`;
  they use `type` if the template is applied.
- Project docs (`sharing/docs/`, `frankenswarm/docs/`, ...) are **out of scope**:
  they follow each project's own conventions (e.g. DMN-770).
- **Project ↔ desk separation**: the desk is private; the project repos are public.
  The desk may reference the project (mirror), but the project NEVER references the
  desk — no desk paths, no desk RFCs, no desk TODO. When a design is
  implemented, its essence lives in the project's own docs (`DECISION_LOG.md`, repo
  docs) with its conventions. See `sharing/docs/CORE/CONVENTIONS.md` §10.6.
- YAML requires spaces for indentation (tabs are invalid); the rest of the
  document keeps the tabs mandated by the Protocol of Silence.