---
type: index
title: "Fase: in_progress"
status: active
created: 2026-09-13
updated: 2026-09-13
author: "Joan García (Operator) / Aleth (Agent)"
project: aleth-core
tags: [planner, fase, in-progress]
---

<!-- REDPILL:BEGIN desk v=1 -->
# Fase: in_progress

Último paso del flujo: **se está implementando**. Corresponde al estado
`implemented` del `RFC_FLUJO_RFCS.md`. Mantenerla corta (2-3 tareas): es lo que
el agente debería estar haciendo — el panel la muestra primero.

Reglas:

- Cada tarea es una carpeta con su `README.md` como entrada y su checklist
  actualizado.
- `status: in-progress` (en marcha) o `implemented` (implementado, verificado).
- **Si no se está trabajando en ello, no está aquí.** Es una cola, no un archivo:
  lo que se queda parado vuelve a `../pending/`, y lo cerrado se archiva.
- **No** entran aquí las piezas de una familia de `design/` sólo porque estén
  implementadas: eso convertiría esta bandeja en un cementerio. La familia se queda
  en su expediente y aquí sólo vive lo que de verdad se está trabajando.
- Campo `priority: High | Medium | Low` obligatorio.
- Al terminar la tarea → `git mv` a `archive/<proyecto>/` (finalizada) con
  `status: archived`.
- Este README es genérico; no lista tareas por nombre.
<!-- REDPILL:END desk -->
