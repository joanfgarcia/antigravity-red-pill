---
type: index
title: "Fase: ideas"
status: active
created: 2026-09-13
updated: 2026-09-13
author: "Joan García (Operator) / Aleth (Agent)"
project: aleth-core
tags: [planner, fase, ideas]
---

# Fase: ideas

Primer paso del flujo: **chispas y llamas** — una idea que despierta interés pero
**ni siquiera se ha analizado** (¿se puede hacer? ¿merece la pena? ¿se hará?).
Una idea aquí es un recordatorio, no una promesa.

Es el estado `spark` → `llama` del dossier de ideación
(`RFC_DOSSIER_IDEACION.md` §3.1): la chispa es la frase vaga; la llama es el germen
estructurado (idea + porqué + dominio + preguntas iniciales).

Reglas:

- Cada idea es una carpeta con su `README.md` como entrada.
- `status: spark` (vaga) o `llama` (germen estructurado).
- Sin prioridad obligatoria: si la idea gana peso, se le asigna `priority:` y se
  mueve a `research/`, `design/` o `pending/` según su camino.
- **Flujo blando**: una idea puede saltarse `research/` e ir directa a `design/`
  (está clara) o a `pending/` (es una tarea concreta, no un estudio).
- Este README es genérico; no lista ideas por nombre.