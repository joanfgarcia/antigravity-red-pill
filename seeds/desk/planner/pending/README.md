---
type: index
title: "Fase: pending"
status: active
created: 2026-09-13
updated: 2026-09-13
author: "Joan García (Operator) / Aleth (Agent)"
project: aleth-core
tags: [planner, fase, pending]
---

# Fase: pending

Carril de **tareas concretas comprometidas y aún sin arrancar** (equivalente al
estado `PENDING` de la cola de jobs). Entrada **directa** (una tarea concreta del
operador o una chispa que es una tarea puntual, no un estudio — ver
`RFC_DOSSIER_IDEACION.md` §2.5) o **tras `design/`** (un RFC ratificado que
espera a que arranque su implementación).

Lo que está aquí, se hace — solo falta decidir cuándo.

Reglas:

- Cada tarea es una carpeta con su `README.md` como entrada (descripción,
  contexto, checklist, enlaces).
- `status: pending`.
- Campo `priority: High | Medium | Low` obligatorio para poder ordenar por
  prioridad (el panel lo usa).
- Campo `depends_on:` opcional: rutas relativas a otros ítems que deben cerrarse
  antes. El panel respeta este orden.
- Al arrancar una tarea → `git mv` a `../in_progress/`.
- Este README es genérico; no lista tareas por nombre.