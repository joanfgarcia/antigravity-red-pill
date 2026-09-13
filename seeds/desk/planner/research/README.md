---
type: index
title: "Fase: research"
status: active
created: 2026-09-13
updated: 2026-09-13
author: "Joan García (Operator) / Aleth (Agent)"
project: aleth-core
tags: [planner, fase, research]
---

# Fase: research

Segundo paso del flujo: **una idea que se investiga o refina, pero todavía no se
ha decidido qué se va a hacer — ni siquiera si se va a hacer**. Es el dossier
`maturing` del loop de ideación (`RFC_DOSSIER_IDEACION.md`): pases de
investigación, síntesis y prueba de hipótesis hasta el Maturity Gate.

El actor que la alimenta es el **scout** (shards → evidencia → claims). Una idea
puede llegar aquí desde `ideas/` o **directo** (p.ej. el operador trae "vamos a
mirar esto" y entra a estudiar sin pasar por ideas).

Reglas:

- Cada investigación es una carpeta con su `README.md` (o `INDEX.md`) como ficha.
- `status: maturing` (en proceso), o estados de parada: `awaiting_operator`
  (espera input), `parked` (aparcada deliberadamente), `dead` (descartada),
  `superseded` (el porqué cambió).
- Al madurar → `git mv` a `../design/` (se aprueba y se diseña). Si se descarta →
  `archive/`.
- Puede agruparse por línea (`research/<linea>/`).
- Este README es genérico; no lista investigaciones por nombre.