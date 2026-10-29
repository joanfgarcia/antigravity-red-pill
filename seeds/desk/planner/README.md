---
type: index
title: "Planner — sistema de planificación del desk"
status: active
created: 2026-09-13
updated: 2026-10-02
author: "Joan García (Operator) / Aleth (Agent)"
project: aleth-core
related:
  - ../INDEX.md
  - ../FRONTMATTER_TEMPLATE.md
tags: [planner, fases, panel, prioridad]
---

<!-- REDPILL:BEGIN desk v=1 -->
# Planner — sistema de planificación

Carpeta del despacho que centraliza **todo el sistema de planificación**: las
fases de trabajo (ideas · research · design · pending · in_progress) y la
herramienta que genera el panel de seguimiento on-demand (`tools/panel.py`).

> **Modelo reconciliado con los RFCs** — no se reinventa nada:
> - `ideas/research/` usan el flujo del **dossier de ideación**
>   (`design/governance/RFC_DOSSIER_IDEACION.md`): spark → llama → maturing → matured.
> - `design/pending/in_progress/` usan el **ciclo de vida de RFCs**
>   (`design/governance/RFC_FLUJO_RFCS.md`): draft → ratified → implemented → closed.
>
> Esos dos RFCs de gobernanza **no vienen con la semilla** del despacho: si tu
> despacho los tiene (`design/governance/`), mandan ellos; si no, este README
> resume lo esencial (fases, estados y ciclo de vida).

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
- **Desk-first para planes/RFCs** (regla dura): un RFC **nace y vive aquí**
  (`design/<familia>/`). Al hablar de planes/diseños/RFCs, mirar **este árbol
  primero** — antes de buscar en el repo. El proyecto **nunca** aloja el RFC del
  desk ni lo referencia: solo su esencia implementada (AD-NNN, docs del repo).
  Ciclo de vida: `draft → ratified → implemented → closed → archived`
  (detallado en `design/governance/RFC_FLUJO_RFCS.md` si tu despacho lo tiene).

## Tamaño de documento (guardarraíl medible)

Un documento que no se asimila no se lee: se hojea. Y se carga en contexto, así
que además **desplaza** lo demás.

**La unidad son TOKENS, no KB.** El KB es lo que ocupa en disco; el token es lo
que ocupa **en la ventana del modelo**, y es lo único que se compara con el
contexto disponible. Un documento de 30 KB de prosa española son ~9.400 tok; el
mismo peso en tablas y rutas pasa de 12.000. El KB miente; el token no. Por eso
el KB se muestra al lado sólo como comodidad (`~x KB`).

| Umbral | Regla | En folios A4 técnicos |
|---|---|---|
| **> 2.000 tok** (~6 KB) | El documento **debe** llevar un índice de secciones al principio | ~2-3 páginas |
| **> 6.000 tok** (~19 KB) | **Señal de dividir**: sub-carpeta + `INDEX.md` que resuma y enlace | ~6-7 páginas |

De dónde salen (medido el 2026-10-29, no supuesto): con `granite_8b` el
**prompt útil** real es `n_ctx - 4.096` = **6.144 tok** — no los 10.240 que
anuncia la ventana, porque 4.096 se reservan para la salida. Y **3,2 caracteres
≈ 1 token** en prosa española. De ahí:

- **blando = un tercio del presupuesto** (~2.000): se lee entero junto a otros
  dos o tres documentos y la pregunta.
- **duro = el presupuesto entero** (~6.000): por sí solo ya no deja sitio a nada
  con lo que compararlo. No se razona, se hojea.

Ojo con dar por buena una ventana: depende de la **compresión del KV cache**, no
del modelo. El mismo `granite_8b` en la misma máquina: `f16` → 12.288 tok,
`q8_0` → 24.576, `q4_0` → 49.152. Estos umbrales están anclados al caso
**conservador (`f16`)**: con KV comprimido hay más sitio y el criterio sigue
siendo válido, sólo que exigente.

**El índice es la pieza, no la fusión.** Un directorio con muchos documentos
pequeños **no** se fusiona: se le pone un `INDEX.md` con un resumen general del
tema y 1-2 líneas por documento enlazado. Eso escala recursivamente (sub-carpeta
con su propio índice) sin crear monolitos. Sólo se fusiona lo que está
**duplicado**.

### Procedimiento al reorganizar (checklist)

1. Si el fichero se llama `README`/`INDEX` pero **es** un documento → **renombrar**
   a su nombre real (`git mv`).
2. Carpeta con **varios** documentos → `INDEX.md` como puerta (resumen del tema en
   2 frases + tabla con 1-2 líneas por documento + "cómo leerlo").
3. Carpeta con **un** documento → **TOC interno** al principio; un índice de un
   solo elemento no aporta nada.
4. Supera el umbral duro → **partir** por secciones temáticas.
5. **Actualizar TODAS las referencias**, incluida la que se olvida siempre: los
   `related: ./README.md` **relativos dentro de la misma carpeta**. Un `grep` de
   la ruta completa no los ve; el hook de `links.py` sí. Correr `links.py` **antes**
   de commitear, no después.
6. Regenerar `STATE.md`: `python3 planner/tools/state.py -o STATE.md`.

**Es una hipótesis fechada, no una ley.** Los números viven en
`tools/check_doc_size.py` como dos constantes (`SOFT_LIMIT_TOKENS`,
`HARD_LIMIT_TOKENS`) con su fecha de calibración, más `CHARS_PER_TOKEN` para el
`~x KB`. Cuando los modelos objetivo crezcan —un 12B o 27B donde hoy hay un 9B,
o una técnica de lectura por partes— se suben ahí y se anota el nuevo objetivo.
Nunca se cambia un número disperso por el código.

```bash
python3 planner/tools/check_doc_size.py            # el desk
python3 planner/tools/check_doc_size.py --strict   # falla también el blando
```

**La deuda no se escribe aquí, se mide.** Un número copiado en un README se queda
viejo el día siguiente y nadie lo nota; el script sí sabe la verdad:

```bash
python3 planner/tools/check_doc_size.py | sed -n '4p'   # documentos · > blando · > duro
```

Los que superan el umbral duro son la cola de trabajo de índices, y se ataca de
uno en uno con el procedimiento de arriba.

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
<!-- REDPILL:END desk -->
