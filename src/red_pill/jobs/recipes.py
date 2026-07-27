"""Recetas de job en YAML — la forma humana de encolar un trabajo.

Un payload declarativo completo es correcto para la máquina e ilegible para una
persona: nadie debería escribir a mano un JSON de veinte claves en una línea de
terminal. La receta es ese mismo payload en YAML, con comentarios, y viviendo
DONDE le corresponde: en el repositorio del proyecto satélite, junto al script
que describe (`<proyecto>/.red-pill/jobs/<nombre>.yaml`).

Eso completa la doctrina del RFC: si el kernel no debe conocer al satélite, la
receta para ejecutarlo tampoco es del kernel — es del satélite, versionada con
su código.

	red-pill job submit --recipe ~/Documents/IA/frankenswarm/.red-pill/jobs/school.yaml
	red-pill job submit --recipe school          # busca en ./.red-pill/jobs/
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

RECIPE_DIR = Path(".red-pill") / "jobs"
_META_KEYS = ("source", "priority", "parent")


def resolve_recipe_path(reference: str, base_dir: Optional[Path] = None) -> Path:
	"""Acepta una ruta explícita o un nombre corto buscado en el workspace.

	El nombre corto se resuelve subiendo desde el directorio actual, igual que
	hacen el resto de convenciones de proyecto (`.agent/`, `.red-pill/memory/`):
	así `--recipe school` funciona desde cualquier punto del repo satélite.
	"""
	candidate = Path(reference).expanduser()
	if candidate.suffix in (".yaml", ".yml") or candidate.is_file():
		if not candidate.is_file():
			raise FileNotFoundError(f"receta no encontrada: {candidate}")
		return candidate.resolve()

	start = (base_dir or Path.cwd()).resolve()
	for directory in [start, *start.parents]:
		for suffix in (".yaml", ".yml"):
			found = directory / RECIPE_DIR / f"{reference}{suffix}"
			if found.is_file():
				return found.resolve()
	raise FileNotFoundError(f"no hay ninguna receta '{reference}' en {RECIPE_DIR} subiendo desde {start}")


def load_recipe(reference: str, base_dir: Optional[Path] = None) -> Tuple[str, Dict[str, Any], int, Optional[str]]:
	"""Lee una receta y devuelve (source, payload, priority, parent).

	`source`, `priority` y `parent` son metadatos del encolado; todo lo demás es
	el payload tal cual. Un `cwd` ausente o relativo se resuelve contra la raíz
	del proyecto que aloja la receta, de modo que la receta es portable y no
	repite rutas absolutas.
	"""
	import yaml

	path = resolve_recipe_path(reference, base_dir)
	with open(path, "r", encoding="utf-8") as f:
		data = yaml.safe_load(f) or {}

	if not isinstance(data, dict):
		raise ValueError(f"la receta {path} debe ser un mapa YAML de claves")

	source = data.get("source")
	if not source:
		raise ValueError(f"la receta {path} no declara `source` (p.ej. script_job)")

	payload = {k: v for k, v in data.items() if k not in _META_KEYS}

	# `.red-pill/jobs/x.yaml` → la raíz del proyecto son dos niveles por encima.
	project_root = path.parent.parent.parent if path.parent.parent.name == ".red-pill" else path.parent
	cwd = payload.get("cwd")
	payload["cwd"] = str(project_root) if not cwd else str((project_root / cwd).resolve() if not Path(cwd).is_absolute() else Path(cwd).expanduser())

	payload.setdefault("title", path.stem)
	return str(source), payload, int(data.get("priority", 5)), data.get("parent")
