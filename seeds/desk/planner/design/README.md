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

<!-- REDPILL:BEGIN desk v=1 -->
# Fase: design

Tercer paso del flujo: **la idea está aprobada y se está diseñando un plan** —
aquí viven los RFCs y las decisiones de diseño.

Es también una bandeja de **residencia**: el documento se queda aquí aunque su
`status` avance a `implemented`. No hay que moverlo (y el panel no lo pide). Puede venir de `research/`
(dossier madurado → nace el RFC) o **directo de `ideas/`** (idea clara que no
necesita investigación).

Corresponde al estado `matured` del dossier de ideación + al ciclo de vida del
`RFC_FLUJO_RFCS.md`: `draft` → `in-design` → `ratified`.

Reglas:

- Cada familia es una carpeta (`<familia>/`); dentro, los RFCs y sus planes.
- Para ver **todas** las familias y su estado de un vistazo, regenera el índice:
  `python3 planner/tools/families.py -o planner/design/INDEX.md`.
- `status` según el RFC_FLUJO: `draft` (decisiones abiertas), `in-design`
  (iterando), `ratified` (decisiones cerradas, listo para implementar).
- Al ratificar y arrancar la implementación, **la familia se queda junta**: el RFC
  y sus piezas (B0x, contratos, planes) forman un expediente y no se reparten por
  bandejas. Sus estados (`ratified` → `in-progress` → `implemented`) se leen en el
  `status` de cada documento, no en su ruta.
- Lo que sí sale es una **tarea de implementación independiente** (sin familia), y
  se va a `../pending/` o `../in_progress/`.
- La familia entera se archiva cuando **todas** sus piezas están cerradas:
  `git mv planner/design/<familia> archive/<proyecto>/`.
  (según `RFC_FLUJO_RFCS.md` §2.1).
- Al cerrar → `git mv` a `archive/<proyecto>/`.
- Este README es genérico; no lista familias por nombre.
<!-- REDPILL:END desk -->
