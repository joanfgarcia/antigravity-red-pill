"""Manifest tree of a dag_job (RFC-JOB_DAG): stage types, id mapping and pure
helpers over the `stages` tree. Extracted from `dag.py` (SHARD-PS-04) — no
dependency on the driver or the runtime, only on the manifest shape.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

# Tipos de etapa del manifest (ampliados por decisión de operador 2026-08-07:
# `type` explícito + `minion` con validación cruzada — la redundancia sirve para
# detectar divergencias en el submit, no para definir el comportamiento).
_TYPE_AGENT = "agent"
_TYPE_COMMAND = "command"
_TYPE_COMPOUND = "compound"
_TYPE_DAG = "dag"  # cuarto tipo (RFC_JOB_DAG §4.5): composición por referencia
_VALID_TYPES = (_TYPE_AGENT, _TYPE_COMMAND, _TYPE_COMPOUND, _TYPE_DAG)

# Scheduling ceilings (used by the step scheduler; overridable per payload).
_MAX_PARALLEL_LEVEL_DEFAULT = 2
_MAX_CONCURRENCY_DEFAULT = 4

# A stage `id` becomes a path component under .cell/reports — restrict the charset
# so it can never traverse out of the confín (§7; SHARD-PSEC-02).
_SAFE_STAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# `stage.params` is a legitimate per-stage override channel, but it must NOT carry
# the runner's policy/path keys: an unfiltered `params` could widen MemoryMax to
# `infinity` or divert `job_id` (re-orphaning what `job kill` reaps) — SHARD-PSEC-01.
_PROTECTED_STAGE_PARAMS = frozenset({"job_id", "memory_max", "env", "cwd", "command", "timeout", "pause_probe", "sleep_cutoff_ts", "item"})


def _resolve_minion_kind(minion_id: str) -> Optional[str]:
	"""Resuelve el minion vía MinionFactory y devuelve 'agent' | 'command' | 'logic' | None.

	None = minion_id no registrado. 'logic' = minion de lógica pura (echo, janitor,
	healer, smith, samantha) — no-agéntico pero sin comando externo. Distinción
	crítica para el fail-safe de modelos: solo 'agent' exige `model`+`prompt`.
	"""
	from red_pill.swarm.factory import MinionFactory

	minion = MinionFactory.create(minion_id)
	if minion is None:
		return None
	return getattr(minion, "kind", "logic")


def _collect_ids(stages: List[Dict[str, Any]]) -> Set[str]:
	"""Todos los ids de etapa del árbol (únicos globalmente), para validar referencias."""
	out: Set[str] = set()
	for s in stages:
		sid = s.get("id")
		if isinstance(sid, str):
			out.add(sid)
		if s.get("type") == _TYPE_COMPOUND:
			out |= _collect_ids(s.get("sub_etapas", []))
	return out


def _iter_leaves(stages: List[Dict[str, Any]], prefix: str = ""):
	"""Itera las etapas ATOMICAS (hojas) del árbol como (ruta, etapa), DFS estable."""
	for s in stages:
		path = f"{prefix}/{s['id']}" if prefix else s["id"]
		if s.get("type") == _TYPE_COMPOUND:
			yield from _iter_leaves(s.get("sub_etapas", []), path)
		else:
			yield path, s


def _flatten_ids(stages: List[Dict[str, Any]], prefix: str = "") -> List[str]:
	"""Todos los ids aplanados por ruta (incluidos compuestos), orden DFS."""
	out: List[str] = []
	for s in stages:
		path = f"{prefix}/{s['id']}" if prefix else s["id"]
		out.append(path)
		if s.get("type") == _TYPE_COMPOUND:
			out.extend(_flatten_ids(s.get("sub_etapas", []), path))
	return out


def _count_leaves(stages: List[Dict[str, Any]]) -> int:
	return sum(1 for _ in _iter_leaves(stages))


def _fanout_subprogress(stages: List[Dict[str, Any]], completed: List[str]) -> Optional[Dict[str, Any]]:
	"""Sub-progress of the FIRST fan-out group (done instances/total), to
	expose it as `stage_*` in the job list (RFC-JOBDAG-002 Phase 3): the job
	shows "· <label> k/N" alongside the global leaf counter. None if there is no
	expanded fan-out."""
	done_set = set(completed)
	for node_path in _flatten_ids(stages):
		node = _find_node_by_path(stages, node_path)
		if not node or not node.get("_fanout"):
			continue
		leaves = list(_iter_leaves(node.get("sub_etapas", []), node_path))
		done = sum(1 for lp, _ in leaves if lp in done_set)
		label = node.get("_fanout_label") or node_path.rsplit("/", 1)[-1]
		return {"label": label, "current": done, "total": len(leaves)}
	return None


def _stage_fields(stages: List[Dict[str, Any]], completed: List[str]) -> Dict[str, Any]:
	"""Campos `stage_*` a fusionar en el `progress` ({} si no hay fan-out)."""
	fp = _fanout_subprogress(stages, completed)
	if not fp:
		return {}
	return {"stage_label": fp["label"], "stage_current": fp["current"], "stage_total": fp["total"]}


def _id_path_map(stages: List[Dict[str, Any]], prefix: str = "") -> Dict[str, str]:
	"""Mapa id→path (DFS estable, primer match). Los ids son únicos globalmente
	por validación; si no lo fueran, el primer match es determinista."""
	out: Dict[str, str] = {}
	for s in stages:
		path = f"{prefix}/{s['id']}" if prefix else s["id"]
		out.setdefault(s["id"], path)
		if s.get("type") == _TYPE_COMPOUND:
			out.update(_id_path_map(s.get("sub_etapas", []), path))
	return out


def _render_item(text: Any, item: Any) -> Any:
	"""Sustituye `{{item}}` y `{{item.<clave>}}` en strings (prompt/command/params)
	por el item del fan-out. Los no-strings se devuelven intactos."""
	if not isinstance(text, str) or "{{item" not in text:
		return text
	if isinstance(item, dict):
		for k, v in item.items():
			text = text.replace("{{item." + str(k) + "}}", str(v))
		return text.replace("{{item}}", json.dumps(item, ensure_ascii=False))
	return text.replace("{{item}}", str(item))


def _apply_recipe_defaults(stages: List[Dict[str, Any]], defaults: Dict[str, Any]) -> None:
	"""Copia los defaults agénticos top-level de una RECETA referenciada a sus
	etapas `agent` sin valor propio. Sin esto, validate() aprobaba la etapa
	contra el payload de la receta y el runtime la ejecutaba contra el payload
	del PADRE — el fail-safe de modelos quedaba burlado por composición."""
	for s in stages:
		if s.get("type") == _TYPE_AGENT:
			for key in ("backend", "model", "effort"):
				if not s.get(key) and defaults.get(key):
					s[key] = defaults[key]
		elif s.get("type") == _TYPE_COMPOUND:
			_apply_recipe_defaults(s.get("sub_etapas", []), defaults)


def _resolve_on_fail(stages: List[Dict[str, Any]], leaf_path: str) -> str:
	"""`on_fail` efectivo de una hoja: el suyo, o el del ancestro más cercano.

	`on_fail` en una etapa COMPUESTA era letra muerta (solo se leía en hojas):
	un `on_fail: stop` de fase se aceptaba en el manifest y no acotaba nada. Con
	recetas que el propio sistema puede escribir (REP-RAP), un campo que el
	validador admite y el motor ignora es una vía de deriva silenciosa. Lo más
	específico gana: la hoja pisa a su ancestro. La resolución es POR RUTA — un
	homónimo de otra rama jamás decide el on_fail de esta.
	"""
	parts = leaf_path.split("/")
	node = _find_node_by_path(stages, leaf_path)
	if node and node.get("on_fail"):
		return str(node["on_fail"])
	for i in range(len(parts) - 1, 0, -1):  # ancestros por ruta, del más cercano al raíz
		ancestor = _find_node_by_path(stages, "/".join(parts[:i]))
		if ancestor and ancestor.get("on_fail"):
			return str(ancestor["on_fail"])
	return "warn"


def _find_node_by_path(stages: List[Dict[str, Any]], path: str) -> Optional[Dict[str, Any]]:
	"""Resuelve una etapa por su RUTA aplanada (`panel/lens-a`), descendiendo nivel
	a nivel. Las RUTAS son únicas (validate); los ids sueltos NO lo son entre
	ramas (F1/implementor y F2/implementor conviven) — resolver por id global
	devolvía el homónimo de otra rama, con su on_fail/parallel equivocados."""
	nodes = stages
	node: Optional[Dict[str, Any]] = None
	for part in path.split("/"):
		node = next((s for s in nodes if s.get("id") == part), None)
		if node is None:
			return None
		nodes = node.get("sub_etapas", []) if node.get("type") == _TYPE_COMPOUND else []
	return node
