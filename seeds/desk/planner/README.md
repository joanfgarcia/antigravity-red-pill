---
type: index
title: "Planner — sistema de planificación del desk"
status: active
created: 2026-09-13
updated: 2026-09-13
author: "Joan García (Operator) / Aleth (Agent)"
project: aleth-core
related:
  - ../INDEX.md
  - ../FRONTMATTER_TEMPLATE.md
  - ./design/governance/RFC_FLUJO_RFCS.md
  - ./design/governance/RFC_DOSSIER_IDEACION.md
tags: [planner, fases, panel, prioridad]
---

# Planner — sistema de planificación

Carpeta del despacho que centraliza **todo el sistema de planificación**: las
fases de trabajo (ideas · research · design · pending · in_progress) y la
herramienta que genera el panel de seguimiento on-demand (`tools/panel.py`).

> **Modelo reconciliado con los RFCs** — no se reinventa nada:
> - `ideas/research/` usan el flujo del **dossier de ideación**
>   (`design/governance/RFC_DOSSIER_IDEACION.md`): spark → llama → maturing → matured.
> - `design/pending/in_progress/` usan el **ciclo de vida de RFCs**
>   (`design/governance/RFC_FLUJO_RFCS.md`): draft → ratified → implemented → closed.

## Modelo: la fase es una carpeta

Un ítem (tarea, RFC, idea) es **una carpeta**. Su ubicación en el árbol dice su
fase; cambiar de fase es mover la carpeta:

```
planner/ideas/        → spark/llama, ni analizada
planner/research/     → maturing, se investiga sin decidir
planner/design/       → aprobada, diseñando el plan (RFCs)
planner/pending/      → tarea comprometida, sin arrancar
planner/in_progress/  → implementando
archive/<proyecto>/   → finalizado (cerrado/archivado)
```

El movimiento se hace con `git mv` (preserva historia):

```bash
git mv planner/ideas/MI_IDEA planner/research/
git mv planner/research/MI_IDEA planner/design/<familia>/
git mv planner/pending/MI_TAREA planner/in_progress/
git mv planner/in_progress/MI_TAREA archive/<proyecto>/
```

## Flujo blando (no es un pipeline duro)

Las fases son una **guía, no una imposición**. Un ítem puede:

- **entrar directo en cualquier fase** (una idea del operador puede nacer en
  `design/`; una tarea concreta, en `pending/`; un estudio, en `research/`);
- **saltarse fases** (una idea clara va de `ideas/` directa a `design/` sin
  research; una chispa que es una tarea puntual va a `pending/` directa —
  `RFC_DOSSIER_IDEACION.md` §2.5);

Para ejecución agéntica la carpeta marca la fase actual y el `status` del
frontmatter es la fuente de verdad; un ítem nunca se mueve de fase "por error",
pero no se obliga a recorrer el flujo completo.

## Vocabulario de estados (por fase)

| Fase | Estados válidos | RFC de referencia |
|---|---|---|
| `ideas/` | `spark`, `llama` | dossier de ideación §3.1 |
| `research/` | `maturing`, `awaiting_operator`, `parked`, `dead`, `superseded` | dossier de ideación §3.2 |
| `design/` | `draft`, `in-design`, `ratified` | RFC_FLUJO_RFCS §2.2 |
| `pending/` | `pending` | (equivalente a cola PENDING) |
| `in_progress/` | `in-progress`, `implemented` | RFC_FLUJO_RFCS §2.2 |
| `archive/` | `archived`, `closed` | RFC_FLUJO_RFCS §2.2 |

## Estructura

```
planner/
├── README.md           ← este archivo
├── ideas/              ← chispas/llamas, sin analizar
├── research/           ← investigación por línea
├── design/             ← RFCs por familia
├── pending/            ← tareas comprometidas sin arrancar
├── in_progress/        ← implementando
└── tools/panel.py      ← panel de seguimiento on-demand
```

> `docs/` (raíz) guarda documentos no ligados a ninguna tarea (p.ej. la tesis
> del proyecto, decisiones cerradas). `archive/` (raíz) es el cementerio de lo finalizado.

## Reglas

- Cada carpeta de fase tiene un `README.md` **genérico** que describe qué viven
  ahí, sin listar ítems (no se actualiza al añadir/quitar).
- Cada ítem tiene su propia carpeta con un `README.md` (o `INDEX.md`) que es su
  **entrada** — la ficha del dossier (campos §3.1) o el RFC — y, si crece, los
  archivos relacionados (evidencia, artefactos).
- El `status` del frontmatter se mantiene en sync con la fase (la carpeta es la
  fase gruesa; el status el estado fino). `tools/panel.py` avisa de desajustes.
- `priority: High | Medium | Low` y `depends_on:` (rutas relativas) son campos
  opcionales del frontmatter — ver `../FRONTMATTER_TEMPLATE.md`.

## Panel

`tools/panel.py` recorre el árbol, lee el frontmatter y genera el panel en
markdown por stdout (o `-o FILE`). Por defecto muestra **solo lo activo**;
`--archive` añade la sección Finalizado.

```bash
python3 tools/panel.py                    # panel activo
python3 tools/panel.py --archive          # + finalizado (archive/)
python3 tools/panel.py --status draft     # filtra por estado
python3 tools/panel.py --project red-pill
python3 tools/panel.py -o /tmp/panel.md
```

El panel ordena por prioridad y respeta `depends_on` (topológico). No es un
fichero físico: se genera cuando se pide.