# Desk Scaffold (seeds/desk/)

Fuente canónica de la **estructura base del desk** (`${AGENT_CORE_DIR}`). El
instalador (`scripts/install_neo.sh` → `scripts/scaffold_desk.sh`) siembra este
árbol en el desk. **Quién manda en cada fichero depende de tres niveles de
propiedad**, más un cuarto grupo que no se siembra nunca:

| Nivel | Qué | Si el desk lo ha tocado |
|---|---|---|
| **Germen** (`.germ`) | código (`planner/tools/*.py`, `hooks/**`) | manda el seed: se alinea, con copia y aviso si no consta que esté intacto |
| **Bloque** (`.blocks`) | prosa compartida: los README de fase, `AGENTS.md`, plantillas | manda el desk **dentro de su región**: el seed sólo toca lo que hay entre `<!-- REDPILL:BEGIN desk -->` y `<!-- REDPILL:END desk -->`; si ambos cambian, merge de 3 vías; si hay conflicto, no se escribe nada y el del seed queda al lado `*.seed-new` |
| **Puesto** (todo lo demás) | contenido del operador (`INDEX.md`, notas, familias) | `copy-if-absent`: el seed nunca lo pisa |
| **Del seed, no del desk** | este `README.md`, `.germ`, `.blocks` | nunca se siembran: documentan el seed, no la mesa del agente |

En un fichero de bloque, el **frontmatter y todo lo que quede fuera de las marcas
es del desk** (title, author, related, secciones propias). Lo de dentro es del seed.

Estos tres niveles **son ya el ciclo de vida de un módulo**: `install`/`enable` =
sembrar o `desk_block.py splice`, `upgrade` = matriz de 3 hashes (germen) o de 3
textos (bloque), `disable`/`remove` = `desk_block.py remove`, que retira sólo
nuestra región y deja el documento y su prosa.

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
   el código se alinea (con copia y aviso si el desk lo había tocado); el bloque se
   fusiona con la versión del desk y, si hay conflicto, no se escribe nada y el del
   seed queda al lado como `*.seed-new`. Ver la tabla de arriba.
3. Si el cambio afecta a convenciones, sincronizar también la instancia local
   del operador (el desk de esta máquina).