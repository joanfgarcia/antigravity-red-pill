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

# Fase: in_progress

Último paso del flujo: **se está implementando**. Corresponde al estado
`implemented` del `RFC_FLUJO_RFCS.md`. Mantenerla corta (2-3 tareas): es lo que
el agente debería estar haciendo — el panel la muestra primero.

Reglas:

- Cada tarea es una carpeta con su `README.md` como entrada y su checklist
  actualizado.
- `status: in-progress` (en marcha) o `implemented` (implementado, verificado).
- Campo `priority: High | Medium | Low` obligatorio.
- Al terminar la tarea → `git mv` a `archive/<proyecto>/` (finalizada) con
  `status: archived`.
- Este README es genérico; no lista tareas por nombre.