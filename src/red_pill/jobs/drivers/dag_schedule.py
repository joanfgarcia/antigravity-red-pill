"""DAG step scheduling: pick the next runnable front, run parallel groups, pause.

Extracted from `dag.py` (SHARD-PS-04 / option B) as `DagScheduleMixin`. The
structural tree helpers it needs (`_stages`/`_workdir`/`_ancestor_deps_met`/
`_status_file`/`_write_status`) live here too, since only `step` uses them.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from red_pill.jobs.drivers.base import JobDeferred, JobPauseRequested, StepOutcome
from red_pill.jobs.drivers.dag_fanout import _GroupPauseGate
from red_pill.jobs.drivers.dag_manifest import (
	_MAX_CONCURRENCY_DEFAULT,
	_MAX_PARALLEL_LEVEL_DEFAULT,
	_TYPE_COMPOUND,
	_count_leaves,
	_find_node_by_path,
	_flatten_ids,
	_id_path_map,
	_iter_leaves,
	_resolve_on_fail,
	_stage_fields,
)

logger = logging.getLogger(__name__)


class DagScheduleMixin:
	"""Scheduling hooks mixed into `DagJobDriver` (methods keep `self` access)."""

	if TYPE_CHECKING:
		# Members provided by the sibling mixins / ResumableJobDriver at runtime.
		short_id: str
		_step_started: Optional[float]
		_sleep_cutoff_ts: float

		def _expand_fanout(
			self,
			stages: List[Dict[str, Any]],
			completed: List[str],
			fanout_items: Dict[str, List[Any]],
			id_map: Dict[str, str],
			workdir: Path,
		) -> Tuple[List[Dict[str, Any]], Dict[str, List[Any]], List[str]]: ...
		def _run_atomic(self, payload: Dict[str, Any], stage: Dict[str, Any], stage_path: str, gate: Any = None) -> str: ...
		def _budget_spent(self) -> bool: ...

	# ── Utilidades ─────────────────────────────────────────────────────────────
	def _stages(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
		stages = payload["manifest"].get("stages")
		return list(stages) if isinstance(stages, list) else []

	def _workdir(self, payload: Dict[str, Any]) -> Path:
		"""workdir del manifest, anclado a payload['cwd'] si es relativo.

		`load_recipe` ancla `cwd` a la raíz del proyecto de la receta; sin este
		anclaje, un `workdir: "."` dependía del CWD del proceso runner (frágil
		si el servicio cambia de WorkingDirectory)."""
		raw = Path(payload["manifest"]["workdir"])
		if raw.is_absolute():
			return raw
		base = payload.get("cwd")
		return (Path(base) / raw).resolve() if base else raw.resolve()

	def _ancestor_deps_met(self, stages: List[Dict[str, Any]], prefix: str, completed: List[str]) -> bool:
		"""Todas las deps de los ancestros compuestos de `prefix` satisfechas.

		Una hoja solo puede ejecutarse si TODOS sus ancestros compuestos tienen
		sus `depends_on` completados (el panel con `depends_on: [impl]` no puede
		ejecutar sus lentes antes de `impl`).
		"""
		if not prefix:
			return True
		parts = prefix.split("/")
		level_path = ""
		for i, part in enumerate(parts):
			level_path = f"{level_path}/{part}" if level_path else part
			# nivel en el que vive el ancestro = parte i+1 de la ruta
			parent_prefix = "/".join(parts[:i]) if i else ""
			ancestor = _find_node_by_path(stages, level_path)
			if ancestor is None:
				continue
			for dep in ancestor.get("depends_on", []):
				dep_path = f"{parent_prefix}/{dep}" if parent_prefix else dep
				if dep_path not in completed:
					return False
		return True

	def _status_file(self, payload: Dict[str, Any]) -> Path:
		return self._workdir(payload) / ".cell" / "dag_status.json"

	def _write_status(self, payload: Dict[str, Any], data: Dict[str, Any]) -> None:
		try:
			path = self._status_file(payload)
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
		except OSError as e:
			logger.warning(f"[DagJob] telemetría no escrita: {e}")

	# ── step: ejecutar el siguiente frente del árbol ──────────────────────────
	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		self._step_started = time.monotonic()
		stages = self._stages(payload)
		completed = list(checkpoint_data.get("completed_stage_ids", []))
		results = dict(checkpoint_data.get("results", {}))
		flags = dict(checkpoint_data.get("stage_flags", {}))
		fanout_items = dict(checkpoint_data.get("fanout_items", {}))
		# Fan-out por items (RFC §4.6): expandir las plantillas `fan_out_from`
		# cuyas fuentes ya completaron; las de lista vacía se marcan done sin
		# ejecutar. El árbol resultante alimenta todo lo demás (frente, progreso,
		# propagación) sin cambios en la mecánica de step.
		stages, fanout_items, _skip_empty = self._expand_fanout(stages, completed, fanout_items, _id_path_map(stages), self._workdir(payload))
		completed = list(completed) + _skip_empty
		total_leaves = _count_leaves(stages)

		# Drain cutoff del ciclo de sueño: anclado en el PRIMER step del job y
		# persistido en el checkpoint — un pause/resume no desliza la ventana y
		# no traga engrams escritos mientras el ciclo estuvo detenido. Lo reciben
		# los minions de fase via _run_atomic (kwargs.sleep_cutoff_ts).
		self._sleep_cutoff_ts = float(checkpoint_data.get("sleep_cutoff_ts") or 0)
		if not checkpoint_data:
			self._sleep_cutoff_ts = float(time.time())
			logger.info(
				f"[DagJob] {self.short_id} drain cutoff pinned at {self._sleep_cutoff_ts:.0f} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._sleep_cutoff_ts))})"
			)

		# Re-derivar compuestos completados desde sus hojas: un checkpoint de
		# handoff (job_checkpoint) puede listar solo hojas; sin esto, un
		# depends_on sobre el compuesto nunca se satisface y el runner llamaría
		# a step() para siempre con el mismo checkpoint (bucle estéril).
		for node_path in _flatten_ids(stages):
			if node_path in completed:
				continue
			node = _find_node_by_path(stages, node_path)
			if not node or node.get("type") != _TYPE_COMPOUND:
				continue
			node_leaves = list(_iter_leaves(node.get("sub_etapas", []), node_path))
			if node_leaves and all(lp in completed for lp, _ in node_leaves):
				completed.append(node_path)

		# Frente: hojas (etapas atómicas) no completadas con deps satisfechas.
		front: List[Tuple[str, Dict[str, Any], str]] = []  # (path, stage, prefix)

		for leaf_path, leaf in _iter_leaves(stages):
			if leaf_path in completed:
				continue
			if leaf.get("_awaiting_fanout_src"):
				# plantilla de fan-out cuya fuente aún no completa: bloqueada, no
				# es ejecutable todavía (RFC §4.6). Sí cuenta para el total.
				continue
			prefix = leaf_path.rsplit("/", 1)[0] if "/" in leaf_path else ""
			if not self._ancestor_deps_met(stages, prefix, completed):
				continue
			deps_ok = all(((f"{prefix}/{d}" if prefix else d) in completed) for d in leaf.get("depends_on", []))
			if deps_ok:
				front.append((leaf_path, leaf, prefix))

		if not front:
			leaves_done = sum(1 for lp, _ in _iter_leaves(stages) if lp in completed)
			done = leaves_done >= total_leaves
			if not done:
				# Sin frente y sin terminar = deps insatisfacibles o checkpoint
				# corrupto. Devolver completed=False con el mismo checkpoint
				# metería al runner en un bucle caliente infinito — mejor fallar
				# con diagnóstico (el disyuntor del runner corta los reintentos).
				raise RuntimeError(
					f"dag sin frente ejecutable: {leaves_done}/{total_leaves} hojas completas "
					f"y ninguna dependencia satisfecha (deps imposibles o checkpoint corrupto)"
				)
			return StepOutcome(
				completed=True,
				# el árbol ya no incluye las plantillas skipped (lista vacía):
				# persistir el skip y la lista congelada en el checkpoint final
				# para que el estado sea consistente con lo ejecutado.
				new_checkpoint={
					**checkpoint_data,
					"completed_stage_ids": list(completed),
					"fanout_items": fanout_items,
				},
				summary="dag complete",
				progress={
					"current": leaves_done,
					"total": total_leaves,
					"percent": round(100 * leaves_done / total_leaves) if total_leaves else 0,
					**_stage_fields(stages, completed),
				},
				concurrency={
					"parallel_groups": 0,
					"parallel_stages": 0,
					"max_parallel_level": int(payload.get("max_parallel_level", _MAX_PARALLEL_LEVEL_DEFAULT)),
					"actually_parallel": False,
				},
			)

		def _exec_one(path: str, stage: Dict[str, Any], gate: Any = None) -> Tuple[str, str, bool]:
			"""Devuelve (path, summary, failed). El fallo se controla por on_fail."""
			try:
				return path, self._run_atomic(payload, stage, path, gate), False
			except JobPauseRequested:
				# Pausa del operador a mitad de fase (sonda del drenaje): NUNCA es
				# un fallo de etapa — propaga al runner, que sella PAUSED con el
				# checkpoint intacto y reanuda la etapa en el siguiente ciclo.
				raise
			except JobDeferred:
				# Espera de entorno (GPU ocupada, VRAM insuficiente), NO fallo de
				# etapa: se propaga al bucle del step, que cede con lo ya
				# completado o, sin progreso, la re-lanza al runner para
				# re-encolar sin quemar attempts (R1). Capturarla como fallo
				# convertía el deferral en etapa 'done' (warn) o en disyuntor (stop).
				raise
			except Exception as e:
				if _resolve_on_fail(stages, path) == "stop":
					return path, str(e), True
				logger.warning(f"[DagJob] {self.short_id} etapa {path} fallida (warn): {e}")
				return path, f"{path}: FAILED ({str(e)[:80]})", False

		# Agrupar el frente por compuesto padre (prefix) para el paralelismo.
		# Sub-etapas del MISMO nodo compuesto `parallel: true` (nivel ≤ cota) se
		# lanzan juntas; el resto secuencial. Grupos independientes también juntos.
		groups: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
		for leaf_path, leaf, prefix in front:
			groups.setdefault(prefix, []).append((leaf_path, leaf))

		max_conc = int(payload.get("max_concurrency", _MAX_CONCURRENCY_DEFAULT))
		max_parallel_level = int(payload.get("max_parallel_level", _MAX_PARALLEL_LEVEL_DEFAULT))
		all_tasks: List[Tuple[str, str, bool]] = []
		parallel_groups = 0
		parallel_stages = 0

		def _run_group(group: List[Tuple[str, Dict[str, Any]]]) -> Tuple[List[Tuple[str, str, bool]], bool, Optional[str]]:
			"""Corre un grupo paralelo con la puerta de pausa compartida.

			Devuelve (tareas_completadas, pausa_honrada, motivo_deferral). La
			sonda de cada etapa en vuelo registra la solicitud en el gate; la
			pausa se honra SOLO cuando todas las etapas aún en vuelo son
			pausables, reevaluando en cada frontera de completación. Un
			JobDeferred de UNA etapa no descarta a sus hermanas: se sigue
			recogiendo lo que complete y el deferral se decide en el cierre del
			step (ceder con lo hecho, o re-lanzar si no hubo progreso).
			"""
			gate = _GroupPauseGate(group)
			tasks: List[Tuple[str, str, bool]] = []
			paused = False
			deferred: Optional[str] = None
			with concurrent.futures.ThreadPoolExecutor(max_workers=max_conc) as pool:
				futures = {pool.submit(_exec_one, p, s, gate): p for p, s in group}
				for fut in concurrent.futures.as_completed(futures):
					path = futures[fut]
					try:
						tasks.append(fut.result())
					except JobPauseRequested:
						# La sonda la honró en vuelo (todas las restantes en vuelo
						# eran pausables): preservar lo ya completado.
						paused = True
						break
					except JobDeferred as e:
						deferred = str(e)
						gate.finished(path)
						continue
					gate.finished(path)
					if gate.pause_requested() and gate.can_pause():
						# Un no-pausable terminó y los restantes en vuelo son
						# pausables: la pausa diferida se honra aquí.
						paused = True
						break
			return tasks, paused, deferred

		# Cota del step en las fronteras: al agotarse NO se abate el step (eso
		# tiraría las etapas ya hechas y las re-ejecutaría con sus efectos), se
		# CEDE con lo completado. El runner persiste el checkpoint (R4) y vuelve
		# a entrar con presupuesto nuevo, pasando además por pausa/kill/prioridad.
		stopped_on_budget = False
		paused = False
		deferred_reason: Optional[str] = None
		try:
			for prefix, group in groups.items():
				if stopped_on_budget or paused or deferred_reason:
					break
				level = len(prefix.split("/")) if prefix else 0
				parent_parallel = False
				if prefix:
					node = _find_node_by_path(stages, prefix)
					parent_parallel = bool(node and node.get("type") == _TYPE_COMPOUND and node.get("parallel"))
				parallel = parent_parallel and level <= max_parallel_level and len(group) > 1
				if parallel:
					parallel_groups += 1
					parallel_stages += len(group)
					group_tasks, group_paused, group_deferred = _run_group(group)
					all_tasks.extend(group_tasks)
					if group_deferred:
						deferred_reason = group_deferred
					if group_paused:
						paused = True
						break
				else:
					for path, stage in group:
						if all_tasks and self._budget_spent():
							stopped_on_budget = True
							break
						try:
							all_tasks.append(_exec_one(path, stage))
						except JobDeferred as e:
							# No lanzar la siguiente etapa (el entorno no está);
							# lo ya completado se preserva cediendo en el cierre.
							deferred_reason = str(e)
							break
				if all_tasks and self._budget_spent():
					stopped_on_budget = True
		except JobPauseRequested:
			# Etapa secuencial pausable con sonda en vuelo: honrar la pausa
			# preservando las etapas secuenciales ya completadas de este step.
			paused = True

		if deferred_reason and not all_tasks:
			# Sin progreso en este step: deferral limpio al runner (R1, sin attempts).
			raise JobDeferred(deferred_reason)
		if deferred_reason:
			logger.info(
				f"[DagJob] {self.short_id} deferral a mitad de frente ({deferred_reason}): "
				f"cede con {len(all_tasks)} etapa(s) completada(s) en el checkpoint; el runner reentra."
			)

		if stopped_on_budget:
			logger.info(
				f"[DagJob] {self.short_id} cota del step agotada tras {len(all_tasks)} etapa(s): "
				f"cede en frontera con el checkpoint persistido (el runner reentra con presupuesto nuevo)."
			)

		new_results = dict(results)
		new_flags = dict(flags)
		new_completed = list(completed)
		for path, summary, failed in all_tasks:
			if failed:
				raise RuntimeError(f"dag stage '{path}' failed with on_fail=stop: {summary}")
			new_results[path] = summary
			new_flags[path] = "done"
			new_completed.append(path)

		# Propagar completitud de los compuestos: un nodo compuesto se marca done
		# cuando todas sus hojas descendientes lo están.
		for node_path in _flatten_ids(stages):
			if node_path in new_completed:
				continue
			node = _find_node_by_path(stages, node_path)
			if not node or node.get("type") != _TYPE_COMPOUND:
				continue
			if all(leaf_path in new_completed for leaf_path, _ in _iter_leaves(node.get("sub_etapas", []), node_path)):
				new_completed.append(node_path)

		# Orden estable y determinista (crítico para resume/control transferible).
		flat_order = _flatten_ids(stages)
		new_completed = [sid for sid in flat_order if sid in new_completed]

		# Progreso basado SOLO en hojas (los compuestos marcados done no cuentan):
		# si no, un árbol con compuestos inflaría el porcentaje.
		leaves_done = sum(1 for lp, _ in _iter_leaves(stages) if lp in new_completed)

		self._write_status(
			payload,
			{
				"mission_id": payload.get("mission_id"),
				"completed": leaves_done,
				"total": total_leaves,
				"status": "running" if leaves_done < total_leaves else "completed",
				"updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
			},
		)

		done = leaves_done >= total_leaves
		checkpoint = {
			"completed_stage_ids": new_completed,
			"results": new_results,
			"stage_flags": new_flags,
			"sleep_cutoff_ts": self._sleep_cutoff_ts,
			"fanout_items": fanout_items,
		}
		if paused:
			logger.info(
				f"[DagJob] {self.short_id} pausa del operador honrada a mitad de step: "
				f"{leaves_done}/{total_leaves} hojas completas preservadas en el checkpoint."
			)
		return StepOutcome(
			completed=done and not paused,
			new_checkpoint=checkpoint,
			summary=f"dag {leaves_done}/{total_leaves}" + (" (pausado a mitad de step)" if paused else ""),
			progress={
				"current": leaves_done,
				"total": total_leaves,
				"percent": round(100 * leaves_done / total_leaves) if total_leaves else 0,
				**_stage_fields(stages, new_completed),
			},
			concurrency={
				"parallel_groups": parallel_groups,
				"parallel_stages": parallel_stages,
				"max_parallel_level": max_parallel_level,
				"actually_parallel": parallel_groups > 0,
			},
			pause_requested=paused,
		)
