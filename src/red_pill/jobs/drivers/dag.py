"""DagJobDriver — resumable job driver for a DAG manifest (RFC-JOB_DAG).

This module is the thin spine of the DAG driver. The heavy lifting lives in
cohesive modules, and each is mixin-composed so the call sites stay unchanged:

- `dag_manifest.py`: pure tree helpers + type/ceiling constants.
- `dag_types/`: the stage-type REGISTRY (agent/command/compound/dag); one module
per node type (adding a node = write its module and register it).
- `dag_validate.py`: payload/tree validation (dispatched via the registry).
- `dag_compose.py`: `type: dag` composition-by-reference expansion.
- `dag_fanout.py`: fan-out-by-items expansion + the parallel pause gate.
- `dag_exec.py`: atomic-stage execution (GPU probe, timeout/budget, minion).
- `dag_schedule.py`: step scheduling (front, parallel groups, pause, progress).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

from red_pill.jobs.drivers.base import ResumableJobDriver
from red_pill.jobs.drivers.dag_exec import DagExecMixin, _gpu_health_probe  # noqa: F401  (re-exported: tests)
from red_pill.jobs.drivers.dag_fanout import DagFanoutMixin, _GroupPauseGate  # noqa: F401  (re-exported: tests)
from red_pill.jobs.drivers.dag_manifest import _resolve_minion_kind, _resolve_on_fail  # noqa: F401  (re-exported: tests)
from red_pill.jobs.drivers.dag_schedule import DagScheduleMixin

logger = logging.getLogger(__name__)


class DagJobDriver(DagScheduleMixin, DagExecMixin, DagFanoutMixin, ResumableJobDriver):
	source = "dag_job"
	min_vram_mb = 0  # los recursos se gestionan por etapa en preflight (GPU probe)

	# Marca de inicio del step en curso (monotónica) — base de la cota de tiempo.
	_step_started: Optional[float] = None
	_mission_beat_stop: Any = None
	_mission_beat_thread: Any = None

	# ── Validación en el submit (recursiva sobre el árbol) ─────────────────────
	@classmethod
	def _load_recipe(cls, reference: str) -> Tuple[str, Dict[str, Any], int, Optional[str], bool]:
		"""Resuelve una receta con el MISMO mecanismo del CLI (RECIPE_DIRS).

		Indirección inyectable: `validate`/`expand_manifest` pasan `cls._load_recipe`
		a sus módulos, así un test (o un backend alternativo) sustituye la resolución
		de recetas sin tocar la lógica de validación/composición.
		"""
		from red_pill.jobs.recipes import load_recipe

		return load_recipe(reference, base_dir=None)

	@classmethod
	def validate(cls, payload: Dict[str, Any]) -> None:
		from red_pill.jobs.drivers.dag_validate import validate_payload

		validate_payload(payload, cls._load_recipe)

	@classmethod
	def expand_manifest(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
		"""Aplana las etapas `type: dag` a `compound` (RFC_JOB_DAG §4.5).

		Se llama en el SUBMIT (CLI/MCP) tras validate: el job se persiste con el
		árbol ya expandido, de modo que step()/checkpoint/resume trabajan SIEMPRE
		sobre compounds y hojas — el determinismo del resume no depende de que la
		receta siga igual en disco. Devuelve un payload nuevo (sin mutar el original).
		"""
		from red_pill.jobs.drivers.dag_compose import expand_manifest

		return expand_manifest(payload, cls._load_recipe)

	def begin_step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> Dict[str, Any]:
		"""RFC-INTEROP-003 S2: registra el leg `dag:<job_id>` si hay alma."""
		checkpoint = super().begin_step(payload, checkpoint_data)
		c_saved = str(checkpoint.get("continuity_id") or "")
		c_payload = str(payload.get("continuity_id") or "")
		if c_saved and c_payload and c_saved != c_payload:
			raise ValueError("dag_job continuity_id cambió a mitad de job (checkpoint inconsistente)")
		continuity = c_payload or c_saved
		if not continuity or not getattr(self, "job_id", None):
			return checkpoint
		trusted = os.getenv("REDPILL_CONTINUITY_ID")
		if trusted and str(continuity) != str(trusted):
			raise ValueError("dag_job continuity_id no coincide con REDPILL_CONTINUITY_ID")
		m_saved = str(checkpoint.get("parent_mission_id") or "")
		m_payload = str(payload.get("parent_mission_id") or "")
		if m_saved and m_payload and m_saved != m_payload:
			raise ValueError("dag_job parent_mission_id cambió a mitad de job (checkpoint inconsistente)")
		mission = m_payload or m_saved
		if mission:
			checkpoint["parent_mission_id"] = mission
			checkpoint["continuity_id"] = str(continuity)
			lease = self._mission_lease_for_job(mission, str(continuity))
			if lease is not None:
				self._start_mission_heartbeat(mission, str(continuity))
		try:
			from red_pill.core.affinity import derive_affinity
			from red_pill.session.store import SessionRegistry

			SessionRegistry().upsert_session(
				originator=f"dag:{self.job_id}",
				continuity_id=str(continuity),
				mission_id=mission or f"mission:job-{str(self.job_id)[:8]}",
				role="job",
				lineage_id=payload.get("lineage_id"),
				affinity=derive_affinity(workdir=str(self._workdir(payload)), mission_id=mission or None),
				title=str(payload.get("title") or f"dag {str(self.job_id)[:8]}"),
			)
			checkpoint["leg_originator"] = f"dag:{self.job_id}"
		except Exception as exc:
			logger.warning(f"[DagJob] no se pudo registrar leg dag:{self.job_id}: {exc}")
		return checkpoint

	def on_terminal(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any], status: str, reason: str = "") -> None:
		"""S2: el leg del job expira al terminar; no deja jobs muertos en el tablón."""
		if not getattr(self, "job_id", None):
			return
		if str(status) == "failed":
			try:
				from red_pill.cognitive.queue_manager import CognitiveQueueManager

				current = CognitiveQueueManager().get_task(self.job_id)
				if current and str(current.get("status") or "") != "FRUSTRATED":
					return  # fallo reintentable: el mando sigue vivo
			except Exception:
				pass
		self._finish_mission_lease(checkpoint_data, status, reason)
		try:
			from red_pill.session.store import SessionRegistry

			SessionRegistry().unregister_session(f"dag:{self.job_id}")
		except Exception as exc:
			logger.warning(f"[DagJob] no se pudo expirar leg dag:{self.job_id}: {exc}")

	def abort_step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any], reason: str) -> Dict[str, Any]:
		"""S4.1: un kill del Operador libera el mando; un timeout/reintento no."""
		checkpoint = super().abort_step(payload, checkpoint_data, reason)
		if "operator_kill" in str(reason or ""):
			self._finish_mission_lease(checkpoint, "aborted", reason)
		return checkpoint

	@staticmethod
	def _mission_key(mission_id: str) -> str:
		return f"mission:{mission_id}"

	def _start_mission_heartbeat(self, mission_id: str, continuity_id: str) -> None:
		"""Late cada 5 min mientras el step (posiblemente largo) sigue vivo.

		Sin esto, un step de 20 min dejaría el lease idle y otra alma podría
		arrebatar la misión a mitad de ejecución.
		"""
		import threading

		if self._mission_beat_thread is not None and self._mission_beat_thread.is_alive():
			return
		stop = threading.Event()
		key = self._mission_key(mission_id)

		def _beat() -> None:
			from red_pill.session.lease import LeaseError, LeaseHeld, LeaseStore

			while not stop.wait(300):
				try:
					row = LeaseStore().heartbeat(key, source="job", continuity_id=continuity_id)
				except (LeaseHeld, LeaseError):
					return
				except Exception:
					# DB locked transitorio: el siguiente latido reintenta; matar el
					# hilo aquí convertiría un lock de ms en un split-brain de 15 min.
					continue
				if str(row.get("state") or "") != "active":
					return

		self._mission_beat_stop = stop
		self._mission_beat_thread = threading.Thread(target=_beat, name=f"mission-heartbeat-{self.short_id}", daemon=True)
		self._mission_beat_thread.start()

	def _stop_mission_heartbeat(self) -> None:
		stop = self._mission_beat_stop
		if stop is not None:
			stop.set()
		self._mission_beat_stop = None
		self._mission_beat_thread = None

	def _mission_lease_for_job(self, mission_id: str, continuity_id: str) -> Optional[dict]:
		"""S4.1/D-03: el job NO reclama la misión; solo observa y late si es su alma.

		- Sin lease: el job ejecuta igual (el alma aún no reclamó; D-02).
		- Lease de la misma alma: renueva el latido del alma y arranca el hilo.
		- Lease de otra alma: spectator, sigue ejecutando como ejecutor y NO publica como orquestador. Nunca roba ni difiere por esto (5.7.3).
		"""
		import time

		from red_pill.session.lease import LeaseStore

		try:
			leases = LeaseStore()
			row = leases.active_mission_lease(mission_id)
			if not row:
				return None
			deadline = min(
				float(row["last_heartbeat_at"]) + int(row["idle_ttl_s"]),
				float(row["started_at"]) + int(row["max_wall_s"]),
			)
			if time.time() > deadline:
				return None
			if str(row["continuity_id"]) != str(continuity_id):
				logger.warning(
					f"[DagJob] misión {mission_id} en manos de {str(row['continuity_id'])[:8]}; "
					f"job {self.short_id} ejecuta como spectator (no orquesta)."
				)
				return None
			row = leases.heartbeat(self._mission_key(mission_id), source="job", continuity_id=continuity_id)
			return row if str(row.get("state") or "") == "active" else None
		except Exception as exc:
			logger.warning(f"[DagJob] no se pudo leer el lease de misión {mission_id}: {exc}")
			return None

	def _finish_mission_lease(self, checkpoint_data: Dict[str, Any], status: str, reason: str = "") -> None:
		"""Cierra el lease solo si lo sostiene ESTE job (no el de una misión hermana)."""
		self._stop_mission_heartbeat()
		mission = str((checkpoint_data or {}).get("parent_mission_id") or "")
		continuity = str((checkpoint_data or {}).get("continuity_id") or "")
		if not mission or not continuity or not getattr(self, "job_id", None):
			return
		try:
			import json

			from red_pill.session.lease import LeaseError, LeaseStore

			leases = LeaseStore()
			key = self._mission_key(mission)
			row = leases.get(key)
			if not row:
				return
			try:
				meta = json.loads(row.get("metadata_json") or "{}")
			except (TypeError, ValueError):
				meta = {}
			if str(row.get("continuity_id") or "") != continuity:
				return
			if str(meta.get("job_id") or "") != str(self.job_id):
				return
			from red_pill.cognitive.queue_manager import CognitiveQueueManager

			live = CognitiveQueueManager().list_tasks(
				statuses=["PENDING", "PROCESSING", "PAUSING", "PAUSED", "BLOCKED"],
				continuity_id=continuity,
				limit=200,
			)
			if any(str(t.get("parent_mission_id") or "") == mission and str(t.get("id") or "") != str(self.job_id) for t in live):
				return
			leases.finish(
				key,
				state="completed" if str(status) == "completed" else "aborted",
				reason=str(reason or status)[:500],
				continuity_id=continuity or None,
			)
		except LeaseError:
			pass
		except Exception as exc:
			logger.warning(f"[DagJob] no se pudo cerrar lease de misión {mission}: {exc}")

	def teardown(self, payload: Dict[str, Any]) -> None:
		"""Toda salida no-terminal (pausa/defer/timeout) apaga el hilo de latido."""
		self._stop_mission_heartbeat()
		super().teardown(payload)

	def preflight(self, payload: Dict[str, Any]) -> None:
		from red_pill.jobs.drivers.base import JobDeferred

		workdir = self._workdir(payload)
		if not workdir.is_dir():
			raise JobDeferred(f"workspace {workdir} no disponible")
