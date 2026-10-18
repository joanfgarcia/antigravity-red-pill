---
type: index
title: "Archive — desk (histórico por proyecto)"
status: active
created: 2026-09-04
updated: 2026-09-13
author: "Joan García (Operator) / Aleth (Agent)"
project: aleth-core
tags: [index, archive]
---
# Archive — desk

Cementerio documental del despacho. Aquí vive todo lo que fue útil y ya cumplió
su función: RFCs implementados, planes ejecutados, auditorías resueltas, notas
obsoletas y espejos cuya fuente canónica vive en otro proyecto.

> **Regla de oro**: lo que está aquí NO se consulta como referencia viva. Si un
> concepto vuelve a hacer falta, su fuente de verdad es el código o los docs del
> proyecto correspondiente. Este directorio solo existe para no perder la memoria
> del *porqué*.

## Estructura (por proyecto)

| Carpeta | Contenido | Fuente de verdad canónica |
|---|---|---|
| `<proyecto>/` | RFCs/planes/auditorías de cada proyecto | `src/`, `docs/`, `DECISION_LOG.md` de cada repo |
| `personal/` | Documentos personales/legales del Operador (no código) | — (custodia personal) |

## Por qué algo termina aquí

- **Implementado y documentado en el proyecto** → se purga del árbol activo; el
  archivo solo se conserva si el diseño tenía decisiones que el código no
  documenta (D1-Dn, ADs).
- **Implementado a medias o superado por otro diseño** → se archiva con su
  estado real en el frontmatter (`status: archived`, `superseded_by`).
- **Auditorías y diagnósticos resueltos** → se archivan como histórico.
- **Espejos** (copias cuya canónica está en otro repo) → se archivan dejando el
  puntero en `../INDEX.md`.

## Cómo se archiva

1. `git mv <origen> archive/<proyecto>/`.
2. Añadir/actualizar el frontmatter: `status: archived`, `archived: <fecha>`,
   `superseded_by:` o `archive_reason:`.
3. Referenciar en `../INDEX.md` (línea de archivo) para que siga siendo
   localizable.
4. Nunca borrar un archivo de aquí sin `git log` previo (reversibilidad).