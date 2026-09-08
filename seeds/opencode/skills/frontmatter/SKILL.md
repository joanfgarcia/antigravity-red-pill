---
name: frontmatter
description: Use when creating, editing, or reorganizing Markdown documents in Agent_Core (Aleth_Core) or memory banks (.red-pill/memory). Applies the FRONTMATTER_TEMPLATE YAML header convention (canonical English values), lifecycle statuses, and archive rules. Project docs are out of scope.
---

## Frontmatter in Markdown documents (Agent_Core & memory banks)

Every `.md` in Agent_Core (`${AGENT_CORE_DIR}`) or in a memory bank
(`.red-pill/memory/`, distilled memory docs) MUST start with a YAML header.
Canonical template: `${AGENT_CORE_DIR}/FRONTMATTER_TEMPLATE.md`.

> **Scope**: Agent_Core + memory banks only. Project documentation follows each
> project's own conventions; do not impose this header there.

## Mandatory fields

```yaml
---
type: rfc|plan|note|research|audit|log|lore|spec|index
title: "Title"
status: draft|ratified|in-design|implemented|closed|active|paused|archived
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: <Author Name(s)>  # actual author(s); e.g. Aleth (Netrunner), Joan García — never copy a placeholder
project: aleth-core|red-pill|neon-link|frankenswarm|obsidian|personal
related: []          # relative paths, optional
superseded_by:       # optional
archived:            # optional
archive_reason:      # optional
tags: []
---
```

Values are canonical **English** (metadata is machine-consumed; no bilingual values).

## Workflow

1. **New document** → generate the block with `type`, `status: draft`, `created`,
   `author`, `project` and fill the rest.
2. **Ratify/implement** → update `status` and `updated`; once the project documents
   the feature (code + docs), the `.md` becomes a design record only.
3. **End of lifecycle** → `git mv` to `archive/<project>/`, set `status: archived`,
   `archived:` + `archive_reason:`, and reference it in `../INDEX.md`.
4. **YAML**: use spaces for indentation (tabs are invalid). The rest of the
   document keeps tabs (Protocol of Silence).
5. Never keep parallel canonical copies between desk and project: one source of truth.