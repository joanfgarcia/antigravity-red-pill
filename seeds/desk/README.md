# Desk Scaffold (seeds/desk/)

Fuente canónica de la **estructura base del desk** (`${AGENT_CORE_DIR}`). El
instalador (`scripts/install_neo.sh` → `scripts/scaffold_desk.sh`) siembra este
árbol en el desk. **Quién manda en cada fichero depende de tres niveles**, no de
uno:

| Nivel | Qué | Si el desk lo ha tocado |
|---|---|---|
| **Germen** (`.germ`) | código (`planner/tools/**`, hooks) y plantillas | **Código**: manda el seed → se alinea, con copia y aviso. **Prosa**: manda el desk → no se pisa; si además hay novedad del seed, se deja al lado como `*.seed-new` |
| **Puesto** (todo lo demás) | contenido del operador (`INDEX.md`, notas, familias) | `copy-if-absent`: el seed nunca lo pisa |
| **Del seed, no del desk** | este `README.md`, `.germ` | nunca se siembran: documentan el seed, no la mesa del agente |

La decisión de germen se toma con **tres** hashes (base sembrada / lo que hay /
lo que trae el seed), no con dos: comparar sólo "lo que hay" con "lo que trae"
revertía ediciones locales aunque el seed no hubiera cambiado nada. Ver
`scripts/scaffold_desk.sh` y `tests/test_scaffold_desk_policy.py`.

## Contenido

| Fichero/Carpeta | Qué es |
|---|---|
| `FRONTMATTER_TEMPLATE.md` | Convención de frontmatter YAML del desk y memory banks |
| `INDEX.md` | Índice plantilla del desk (estructura, no contenido) |
| `planner/README.md` | El modelo planner: fase = carpeta, flujo blando, vocabulario de estados |
| `planner/<fase>/README.md` | README genérico de cada fase (ideas/research/design/pending/in_progress) |
| `planner/tools/panel.py` | Panel de seguimiento on-demand |
| `archive/README.md` | Convención del cementerio documental |
| `.germ` | Manifiesto de qué ficheros son germen (el resto es puesto) |
| `.gitignore` | Ruido a ignorar en el desk (`__pycache__`, `.germ.state`, `.germ.bak/`, `*.seed-new`) |
| `planner/tools/check_doc_size.py` | Guardarraíl de tamaño en **tokens** (no KB) |
| `planner/tools/doc_read_bench.py` | Banco de pruebas de asimilación documental, comparable entre modelos |

## Instalación vs instancia

- El **seed es canónico y portable** — usa nombres genéricos y `${AGENT_CORE_DIR}`.
  No contiene contenido del operador ni nombres de proyectos concretos.
- El **desk de cada máquina es la instancia** — el operador elige el nombre en la
  instalación (`AGENT_CORE_DIR` en el `.env`; p.ej. `Agent_Core/`, `Titanium_Core/`…)
  y puede cambiarlo después: el nombre viaja en la variable, no en el contenido.
- Un seed **nunca** referencia un proyecto ni un desk concretos por nombre
  (regla de separación proyecto↔despacho).

## Cómo actualizar una convención

1. Editar el fichero correspondiente aquí (`seeds/desk/...`).
2. El desk local hereda el cambio en la próxima instalación, **según el nivel**:
   el código se alinea; la prosa no se pisa (queda como `*.seed-new` si el desk
   la había tocado). Ver la tabla de arriba.
3. Si el cambio afecta a convenciones, sincronizar también la instancia local
   del operador (el desk de esta máquina).