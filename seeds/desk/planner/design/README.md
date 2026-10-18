---
type: index
title: "Fase: design"
status: active
created: 2026-09-13
updated: 2026-09-13
author: "Joan García (Operator) / Aleth (Agent)"
project: aleth-core
tags: [planner, fase, design]
---

# Fase: design

Tercer paso del flujo: **la idea está aprobada y se está diseñando un plan** —
aquí viven los RFCs y las decisiones de diseño. Puede venir de `research/`
(dossier madurado → nace el RFC) o **directo de `ideas/`** (idea clara que no
necesita investigación).

Corresponde al estado `matured` del dossier de ideación + al ciclo de vida del
`RFC_FLUJO_RFCS.md`: `draft` → `in-design` → `ratified`.

Reglas:

- Cada familia es una carpeta (`<familia>/`); dentro, los RFCs y sus planes.
- `status` según el RFC_FLUJO: `draft` (decisiones abiertas), `in-design`
  (iterando), `ratified` (decisiones cerradas, listo para implementar).
- Al ratificar y arrancar la implementación → la tarea de implementación vive en
  `../pending/` o `../in_progress/`; el RFC se queda aquí como registro de diseño
  (según `RFC_FLUJO_RFCS.md` §2.1).
- Al cerrar → `git mv` a `archive/<proyecto>/`.
- Este README es genérico; no lista familias por nombre.