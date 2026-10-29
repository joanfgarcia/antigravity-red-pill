---
type: spec
title: "AGENTS.md — convenciones del desk (para agentes)"
status: active
created: 2026-10-10
updated: 2026-10-10
author: "Aleth (Netrunner)"
project: aleth-core
tags: [desk, convenciones, commits, agentes, soberania]
---

<!-- REDPILL:BEGIN desk v=1 -->
# AGENTS.md — convenciones del desk

`/home/joan/Documents/IA/Aleth_Core` es la **mesa privada de Aleth**: notas,
planes, RFCs, historia. Es un **backup, no control de versiones estricto** —
importa el **contenido actual**, no la procedencia ni quién tocó qué.

## Commits — dos carriles por intención (no por fichero)

- **Contenido pensado** — `planner/**` (ideas, research, RFCs), `notes/**`,
  `docs/**`: commit **atómico**, mensaje de **una línea** descriptivo. Es lo único
  que merece poder bisectar/revertir y releer por historia.
- **Churn generado** — `awakening/*.log`, snapshots de sesión, ruido automático:
  **snapshot en bloque**, mensaje genérico. No aporta versionar log a log.

Commit y push **directos a `main`** están permitidos aquí (excepción a la Golden
Rule del kernel). Sin ceremonia: mensaje corto y ya.

## Frontera de escritura (soberanía del desk)

- El Operador (Joan) escribe **solo** las respuestas a las notas del `awakening/`.
  Todo lo demás es **read-only** para él, por acuerdo mutuo.
- Si necesita tocar cualquier otra cosa, lo **pide**, lo **deja anotado** o lo
  **comunica** — no edita directo.
- Los agentes crean/editan su contenido libremente, respetando este archivo y el
  frontmatter YAML (`FRONTMATTER_TEMPLATE.md`).

## Grafo de enlaces y tools del germen (RFC-ENLACES-001)

- **Al añadir / mover / renombrar / actualizar docs del desk, mantén el grafo de
  enlaces**: corre `python3 planner/tools/links.py` (backlinks, refs rotas,
  huérfanos, ciclos). Es barato y detecta lo que el `grep` no ve.
- Un **hook `pre-commit`** avisa de **refs rotas NUEVAS** (warn-only; `LINKS_STRICT=1`
  lo vuelve bloqueante). Ya está activo (`core.hooksPath=planner/tools/hooks`); si no,
  instálalo: `planner/tools/hooks/install.sh`. Si una ref rota es **aceptada** a
  propósito, regístrala con `links.py --update-baseline`.
- **Las tools generales nuevas nacen en el germen**: se construyen aquí pero su
  fuente canónica es `sharing/seeds/desk/` del repo red-pill (se siembran en cada
  instalación) — ver `planner/pending/DESK-001-tools-generales-al-seed/`.
<!-- REDPILL:END desk -->
