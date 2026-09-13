# Desk Scaffold (seeds/desk/)

Fuente canónica de la **estructura base del desk** (`${AGENT_CORE_DIR}`). El
instalador (`scripts/install_neo.sh`) copia este árbol al directorio del desk
**copy-if-absent**: nunca pisa lo que el operador ya ha tocado. Las
actualizaciones de convención se hacen aquí y se propagan en la próxima
instalación.

## Contenido

| Fichero/Carpeta | Qué es |
|---|---|
| `FRONTMATTER_TEMPLATE.md` | Convención de frontmatter YAML del desk y memory banks |
| `INDEX.md` | Índice plantilla del desk (estructura, no contenido) |
| `planner/README.md` | El modelo planner: fase = carpeta, flujo blando, vocabulario de estados |
| `planner/<fase>/README.md` | README genérico de cada fase (ideas/research/design/pending/in_progress) |
| `planner/tools/panel.py` | Panel de seguimiento on-demand |
| `archive/README.md` | Convención del cementerio documental |

## Instalación vs instancia

- El **seed es canónico y portable** — usa nombres genéricos y `${AGENT_CORE_DIR}`.
  No contiene contenido del operador ni nombres de proyectos concretos.
- El **desk de cada máquina es la instancia** — puede renombrar (p.ej.
  `Aleth_Core/`) y rellenar con su contenido real.
- Un seed **nunca** referencia un proyecto ni un desk concretos por nombre
  (regla de separación proyecto↔despacho).

## Cómo actualizar una convención

1. Editar el fichero correspondiente aquí (`seeds/desk/...`).
2. El desk local hereda el cambio en la próxima instalación (copy-if-absent) —
   o se propaga manualmente si el cambio debe aplicar ya.
3. Si el cambio afecta a convenciones, sincronizar también la instancia local
   del operador (en esta máquina, `Aleth_Core/`).