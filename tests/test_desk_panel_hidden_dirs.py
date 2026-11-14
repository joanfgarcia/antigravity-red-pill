"""panel.load_docs — los directorios ocultos no son ítems del desk.

Caso real (medido en el desk el 2026-11-09): `load_docs` solo se saltaba `.git`,
así que `.germ.baseline/FRONTMATTER_TEMPLATE.md` —la copia sembrada de la
plantilla— entraba en el panel y publicaba su **fila de ejemplo**:

    | root | `draft   # see status list below` | `Medium   # optional: High` | … |

Un placeholder de documentación apareciendo como trabajo pendiente en el punto
de entrada en frío. La regla es la misma que usa `planner_state_audit.py`:
cualquier ruta con un segmento oculto no es contenido del desk.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "seeds" / "desk" / "planner" / "tools" / "panel.py"


def _panel():
	spec = importlib.util.spec_from_file_location("desk_panel_under_test", PANEL)
	assert spec and spec.loader
	module = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = module  # dataclasses resuelve el módulo por nombre
	spec.loader.exec_module(module)
	return module


def _doc(root: Path, rel: str, title: str) -> None:
	p = root / rel
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(
		f"---\ntype: task\ntitle: {title}\nstatus: active\nproject: aleth-core\n---\n\n# {title}\n",
		encoding="utf-8",
	)


def test_los_directorios_ocultos_no_entran_en_el_panel(tmp_path: Path) -> None:
	_doc(tmp_path, "planner/ideas/A/README.md", "visible")
	_doc(tmp_path, ".germ.baseline/FRONTMATTER_TEMPLATE.md", "plantilla")
	_doc(tmp_path, ".red-pill/memory/MEMORY.md", "cajon")
	_doc(tmp_path, "planner/.cache/anidado.md", "anidado")
	_doc(tmp_path, "planner/ideas/B/README.md", "visible-dos")

	panel = _panel()
	panel.ROOT = tmp_path  # las rutas internas se resuelven contra el ROOT del módulo
	titles = {d.title for d in panel.load_docs(tmp_path)}
	assert titles == {"visible", "visible-dos"}
