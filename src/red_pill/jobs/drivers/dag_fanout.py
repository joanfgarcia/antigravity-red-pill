"""DAG fan-out expansion (RFC §4.6) + the parallel-group pause gate.

Extracted from `dag.py` (SHARD-PS-04 / option B). `_expand_fanout` turns
`fan_out_from` templates into dynamic `compound`s of N instances (frozen items →
deterministic resume); the gate coordinates mid-stage pause across the parallel
tasks of ONE group.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple

from red_pill.jobs.drivers.dag_manifest import _TYPE_COMPOUND


class _GroupPauseGate:
	"""Puerta de pausa compartida por las etapas de UN grupo paralelo del DAG.

	La sonda de pausa de cada etapa en vuelo registra aquí su solicitud
	(`request_pause`) y consulta si TODAS las etapas aún corriendo son pausables
	(`can_pause`). La regla del operador: la pausa a mitad de un grupo paralelo
	solo se honra cuando todos los que siguen en vuelo son pausables; si alguno
	no lo es, se difiere y se reevalúa en cada frontera de completación, de modo
	que el trabajo ya completado (pausables o no) se preserva en el checkpoint.
	"""

	def __init__(self, group: List[Tuple[str, Dict[str, Any]]]):
		self._lock = threading.Lock()
		self._running = {path for path, _ in group}
		self._pausable = {path: bool(stage.get("pausable", True)) for path, stage in group}
		self._pause_requested = False

	def finished(self, path: str) -> None:
		with self._lock:
			self._running.discard(path)

	def request_pause(self) -> None:
		with self._lock:
			self._pause_requested = True

	def can_pause(self) -> bool:
		with self._lock:
			return all(self._pausable[p] for p in self._running)

	def pause_requested(self) -> bool:
		with self._lock:
			return self._pause_requested


class DagFanoutMixin:
	"""Fan-out hooks mixed into `DagJobDriver` (kept as methods: call sites unchanged)."""

	@staticmethod
	def _read_report_items(workdir: Path, src_path: str) -> List[Any]:
		"""Lee la lista `items` del reporte de la etapa fuente (command → .json,
		agent → .envelope.json). Vacía si el reporte no existe o no trae items."""
		reports_dir = workdir / ".cell" / "reports"
		for suffix in (".json", ".envelope.json"):
			p = reports_dir / f"{src_path}{suffix}"
			if not p.exists():
				continue
			try:
				data = json.loads(p.read_text(encoding="utf-8"))
			except Exception:
				continue
			items = data.get("items") if isinstance(data, dict) else None
			if isinstance(items, list):
				return items
			# command: el minion pudo volcar JSON con `items` en stdout — es el
			# contrato de la etapa fuente del fan-out (RFC §4.6).
			if isinstance(data, dict) and isinstance(data.get("stdout"), str):
				try:
					parsed = json.loads(data["stdout"])
				except Exception:
					parsed = None
				if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
					return list(parsed["items"])
		return []

	@classmethod
	def _expand_fanout(
		cls,
		stages: List[Dict[str, Any]],
		completed: List[str],
		fanout_items: Dict[str, List[Any]],
		id_map: Dict[str, str],
		workdir: Path,
	) -> Tuple[List[Dict[str, Any]], Dict[str, List[Any]], List[str]]:
		"""Expande las hojas `fan_out_from` cuyas fuentes ya están completadas.

		Mutación ACOTADA por contrato (RFC §4.6): la hoja plantilla se convierte
		en un compuesto dinámico con N instancias idénticas (path `<plantilla>/<i>`),
		cada una con `_item` para que `_run_atomic` la inyecte. La lista de items se
		CONGELA en `fanout_items[<plantilla>]` la primera vez (del reporte de la
		fuente); el resume re-expande desde ahí, sin re-leer el reporte → determinista.

		Devuelve (árbol expandido, fanout_items actualizado, paths de plantillas con
		lista vacía que se marcan done sin ejecutar).
		"""
		new_stages: List[Dict[str, Any]] = []
		skipped: List[str] = []
		for s in stages:
			path = s["id"]
			if s.get("type") == _TYPE_COMPOUND:
				sub, sub_items, sub_skip = cls._expand_fanout(s.get("sub_etapas", []), completed, fanout_items, id_map, workdir)
				ns = dict(s)
				ns["sub_etapas"] = sub
				new_stages.append(ns)
				skipped.extend(sub_skip)
				continue
			fof = s.get("fan_out_from")
			if not fof:
				new_stages.append(s)
				continue
			src_path = id_map.get(fof, fof)
			if src_path not in completed:
				# la fuente aún no terminó: la plantilla queda como hoja BLOQUEADA
				# (el frente la ignora) para que el DAG no la ejecute ni finalice
				# antes de tiempo; el próximo step la expandirá.
				ns = dict(s)
				ns["_awaiting_fanout_src"] = True
				new_stages.append(ns)
				continue
			if path not in fanout_items:
				fanout_items[path] = cls._read_report_items(workdir, src_path)
			items = fanout_items[path]
			if not items:
				skipped.append(path)
				continue
			stepwise = bool(s.get("fanout_stepwise"))
			instances = []
			for i, item in enumerate(items):
				inst = dict(s)
				inst["id"] = f"{s['id']}-{i}"
				inst["_item"] = item
				# las deps las resuelve el compuesto padre (ancestor deps met), no
				# cada instancia como hermano: si se heredaran, "discover" se
				# buscaría como "plantilla/discover" y el frente nunca la lanzaría.
				inst.pop("depends_on", None)
				inst.pop("fan_out_from", None)
				inst.pop("sub_etapas", None)
				inst.pop("fanout_stepwise", None)
				# `fanout_stepwise`: encadena (i depende de i-1) para que el frente
				# tenga UNA instancia por step → el progreso del job avanza por item
				# (RFC-JOBDAG-002). Sin esto, TODO el frente corre en un solo step y
				# el contador queda congelado hasta que terminan todas.
				if stepwise and i > 0:
					inst["depends_on"] = [f"{s['id']}-{i - 1}"]
				instances.append(inst)
			comp = dict(s)
			comp["type"] = _TYPE_COMPOUND
			comp["sub_etapas"] = instances
			# Fan-out marker (for the `stage_*` sub-progress, Phase 3): survives the
			# deterministic re-expansion and feeds _fanout_subprogress.
			comp["_fanout"] = True
			comp["_fanout_label"] = s.get("fanout_label") or s.get("id")
			comp.pop("_item", None)
			comp.pop("fan_out_from", None)
			comp.pop("command", None)
			comp.pop("prompt", None)
			comp.pop("minion", None)
			new_stages.append(comp)
		return new_stages, fanout_items, skipped
