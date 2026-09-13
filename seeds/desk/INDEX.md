---
type: index
title: "${AGENT_CORE_DIR} — Índice"
status: active
created: 2026-09-13
updated: 2026-09-13
author: "Joan García (Operator) / Aleth (Agent)"
project: aleth-core
tags: [index]
---

# 🧠 Desk — Índice

Despacho del agente. **No es un repo público**: es la mesa de trabajo (diseño,
investigación, planes, historia) del agente. La fuente de verdad del *código* está
en cada proyecto; aquí viven las ideas, las decisiones de diseño y la memoria del
agente.

> Los `.md` de este despacho llevan frontmatter YAML — ver
> [`FRONTMATTER_TEMPLATE.md`](FRONTMATTER_TEMPLATE.md) y el ciclo de vida de RFCs
> en [`planner/design/governance/RFC_FLUJO_RFCS.md`](planner/design/governance/RFC_FLUJO_RFCS.md).

> **Seguimiento de estados**: no hay un panel físico — el árbol ES el panel.
> La fase de cada ítem es su carpeta (ver [`planner/README.md`](planner/README.md)).
> Para generar el panel sobre demanda:
> `python3 planner/tools/panel.py` (o `--archive` para ver lo finalizado).

## Planificación (todo el sistema bajo `planner/`)

El modelo: **fase = carpeta** (flujo blando — entrada directa en cualquier fase,
fases saltables). Ver [`planner/README.md`](planner/README.md) para el detalle.

| Fase | Contenido | Estado |
|---|---|---|
| [`planner/ideas/`](planner/ideas/README.md) | Chispas/llamas sin analizar | `spark`, `llama` |
| [`planner/research/`](planner/research/README.md) | Investigación por línea, sin decidir | `maturing`... |
| [`planner/design/`](planner/design/README.md) | RFCs por familia | `draft`→`ratified` |
| [`planner/pending/`](planner/pending/README.md) | Tareas comprometidas sin arrancar | `pending` |
| [`planner/in_progress/`](planner/in_progress/README.md) | En curso | `in-progress` |
| [`planner/tools/panel.py`](planner/tools/panel.py) | Panel de seguimiento on-demand | — |

> **Seguimiento de estados**: no hay un panel físico — el árbol ES el panel.
> `python3 planner/tools/panel.py` (o `--archive` para ver lo finalizado).

## Diseño (RFCs y decisiones) — por familia

Cada familia es una carpeta en [`planner/design/`](planner/design/README.md) con
sus RFCs y planes (p.ej. `RFC_FLUJO_RFCS.md`, `RFC_DOSSIER_IDEACION.md`).

## Investigación — por línea

Cada línea es una carpeta en [`planner/research/`](planner/research/README.md).

## Operación

- [`ROADMAP.md`](ROADMAP.md) — hoja de ruta estratégica y curiosidad.
- [`awakening/`](awakening/) — logs de despertar autónomo, uno por sesión
  (`YYYYMMDD_HHMM.log`). El legacy `AWAKENING_LOG.md` se conserva como histórico
  (ya no crece).
- [`notes/`](notes/) — notas de sesión recientes.
- [`lore/`](lore/) — filosofía y visión del agente.
- [`docs/`](docs/) — documentos base no ligados a una tarea (tesis, decisiones cerradas).

## Archivo (finalizado)

[`archive/README.md`](archive/README.md) explica el criterio. Resumen:

- `archive/<proyecto>/` — RFCs/planes/auditorías de cada proyecto (fuente de verdad: cada repo).
- `archive/personal/` — documentos personales/legales del Operador.