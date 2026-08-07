"""Recetas de job en YAML — la forma humana de encolar un trabajo.

Un payload declarativo completo es correcto para la máquina e ilegible para una
persona: nadie debería escribir a mano un JSON de veinte claves en una línea de
terminal. La receta es ese mismo payload en YAML, con comentarios, y viviendo
DONDE le corresponde: en el repositorio del proyecto satélite, junto al script
que describe (`<proyecto>/.red-pill/jobs/<nombre>.yaml`).

Eso completa la doctrina del RFC: si el kernel no debe conocer al satélite, la
receta para ejecutarlo tampoco es del kernel — es del satélite, versionada con
su código.

	red-pill job submit --recipe ~/Documents/IA/frankenswarm/configs/jobs/school.yaml
	red-pill job submit --recipe school          # busca subiendo directorios
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Orden de búsqueda deliberado: primero el directorio de estado local del kernel
# (sin versionar — sirve para ajustes puntuales sin ensuciar el repo), después
# los sitios VERSIONADOS, que son el hogar natural de la receta: describe cómo
# se ejecuta el proyecto, así que pertenece al proyecto y viaja con su historia.
RECIPE_DIRS = (Path(".red-pill") / "jobs", Path("configs") / "jobs", Path("jobs"))
# 'seed': True marca una receta PLANTILLA por-instalación (no una config activa).
# No viaja al payload: es metadata para que el caller distinga seeds de config real.
_META_KEYS = ("source", "priority", "parent", "seed")


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
		for recipe_dir in RECIPE_DIRS:
			for suffix in (".yaml", ".yml"):
				found = directory / recipe_dir / f"{reference}{suffix}"
				if found.is_file():
					return found.resolve()
	searched = ", ".join(str(d) for d in RECIPE_DIRS)
	raise FileNotFoundError(f"no hay ninguna receta '{reference}' en [{searched}] subiendo desde {start}")


def load_recipe(reference: str, base_dir: Optional[Path] = None) -> Tuple[str, Dict[str, Any], int, Optional[str], bool]:
	"""Lee una receta y devuelve (source, payload, priority, parent, is_seed).

	`source`, `priority` y `parent` son metadatos del encolado; todo lo demás es
	el payload tal cual. Un `cwd` ausente o relativo se resuelve contra la raíz
	del proyecto que aloja la receta, de modo que la receta es portable y no
	repite rutas absolutas.

	`is_seed` es True cuando la receta declara `seed: true` — una PLANTILLA
	genérica por-instalación, NO una config activa. El caller debe bloquear (o
	avisar) cuando una receta seed llega a producción sin config real activa.
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

	is_seed = bool(data.get("seed", False))
	payload = {k: v for k, v in data.items() if k not in _META_KEYS}

	# `<raíz>/<dir de recetas>/x.yaml` → la raíz está por encima del directorio
	# conocido (`configs/jobs`, `.red-pill/jobs`, `jobs`). Si la receta vive en
	# otro sitio, su propio directorio hace de raíz.
	project_root = path.parent
	for recipe_dir in RECIPE_DIRS:
		suffix_parts = recipe_dir.parts
		if path.parent.parts[-len(suffix_parts) :] == suffix_parts:
			project_root = Path(*path.parent.parts[: -len(suffix_parts)])
			break
	cwd = payload.get("cwd")
	payload["cwd"] = str(project_root) if not cwd else str((project_root / cwd).resolve() if not Path(cwd).is_absolute() else Path(cwd).expanduser())

	payload.setdefault("title", path.stem)
	return str(source), payload, int(data.get("priority", 5)), data.get("parent"), is_seed
