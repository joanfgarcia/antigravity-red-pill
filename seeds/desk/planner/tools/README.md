---
type: index
title: "planner/tools — herramientas del desk (germen)"
status: active
created: 2026-10-15
updated: 2026-10-15
author: "Aleth (Netrunner)"
project: aleth-core
tags: [desk, tools, seed, germen, enlaces]
---

<!-- REDPILL:BEGIN desk v=1 -->
# planner/tools — herramientas del desk

Las herramientas **generales** del desk. Su fuente canónica es el **germen** en el
repo red-pill (`sharing/seeds/desk/`), y se siembran en cada instalación. Al crear
una tool general nueva, **nace aquí** (no solo en el desk de un puesto).

## `panel.py` — panel de seguimiento

Recorre el desk, lee el frontmatter y genera el panel por fase/prioridad/dependencias.
On-demand (a stdout o `-o FILE`). También avisa de desajustes carpeta-vs-status.

```
python3 planner/tools/panel.py            # panel a stdout
```

## `decisions.py` — ledger `decisions:` del frontmatter

Parser de las decisiones de diseño declaradas en el frontmatter (`id`, `status`,
`blast_radius`, `question`, `default`). Lo consume el panel para pintar el bloque
«Decisiones abiertas»; el panel lo importa de forma **defensiva** (si falta, no
pinta el bloque y sigue). Sin CLI propia.

## `state.py` — `STATE.md`, punto de entrada en frío (P2-ARNES-004 §3.2)

Genera un snapshot determinista del desk en un solo documento: panel activo +
decisiones abiertas + ítems `blocked`/`paused` con su `reason`. Es **generado**
(no se mantiene a mano): regenéralo tras cambios relevantes.

```
python3 planner/tools/state.py            # STATE.md a stdout
python3 planner/tools/state.py -o STATE.md
```

## `links.py` — grafo de enlaces (RFC-ENLACES-001)

Construye el grafo de referencias tipadas (`related` / `depends_on` / `supersedes` /
`superseded_by`): **backlinks derivados**, referencias rotas (**dangling**),
huérfanos y ciclos de `depends_on`.

```
python3 planner/tools/links.py                      # grafo completo a stdout
python3 planner/tools/links.py --check              # solo refs rotas NUEVAS vs baseline (exit 1 si hay)
python3 planner/tools/links.py --update-baseline    # acepta las refs rotas actuales
```

La **baseline** (`.links_baseline`) es **estado del puesto**, no germen: no se
siembra; se genera con `--update-baseline`.

## `hooks/pre-commit` — aviso de refs rotas nuevas

Hook de git que corre `links.py --check` en cada commit. **Warn-only** por defecto
(respeta el ethos "backup, no control estricto"); `LINKS_STRICT=1` o
`git config redpill.linksStrict true` lo vuelve bloqueante.

Instalación (idempotente, fija `core.hooksPath=planner/tools/hooks`):

```
planner/tools/hooks/install.sh
```

## Regla operativa

Al **añadir / mover / renombrar / actualizar** docs del desk: corre `links.py` y
deja que el hook avise. Toda tool general nueva → al germen (`seeds/desk/`).
<!-- REDPILL:END desk -->
