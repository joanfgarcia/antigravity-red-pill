"""Minions de sleep (lógica pura) — encapsulan cada unidad atómica del ciclo de
sueño como un Minion del MinionFactory (RFC_JOB_DAG §4.2 fleco 2).

Reducir cada unidad del antiguo driver del sueño (sleep_job, retirado) a un
minion permite que el ciclo de
sueño se declare como una RECETA del dag_job (árbol de etapas) en vez de un
driver con mecánica propia. El estado `total_processed` cruza entre fases: se
reconstruye leyendo `sleep_phase_status.json` (el contrato público que ya
escribe `SleepContext.update_status`) — cada minion parte del total previo y
devuelve el nuevo en su dict.

Los minions no escriben `.cell/reports/<id>.json`: eso lo hace el DAG
(serialización uniforme, opción 3 del RFC). Aquí solo ejecutan y devuelven.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

from red_pill.swarm.base import Minion

# Estados públicos que escriben los rituales/fases del ciclo (te hace falta en
# la memoria de largo plazo; ver red_pill.metabolism.phases.base).
_STATUS_FILE_NAMES = ("sleep_phase_status.json",)

# Fichero donde `memento_agentic.py` deja la producción de su pase (ascensiones
# estáticas incluidas). El finalize lo lee para que el resumen del ciclo no
# oculte lo que el pase Memento sí ingresó.
_MEMENTO_STATE_FILE = "memento_agentic_state.json"
_MEMENTO_STATE_MAX_AGE_S = 12 * 3600


def _read_state() -> tuple[int, Dict[str, int]]:
	"""Total + métricas acumuladas de la noche, del fichero de telemetría.

	`SleepContext.update_status` escribe `total_processed`/`metrics` en vivo en
	`sleep_phase_status.json`; un minion de fase parte de ese estado previo para
	que la acumulación cruce el límite entre etapas del DAG.
	"""
	from red_pill.core.paths import get_state_dir

	for name in _STATUS_FILE_NAMES:
		path = get_state_dir() / name
		try:
			data = json.loads(path.read_text(encoding="utf-8"))
			# Un estado con status=cycle_completed es el remanente de la noche
			# ANTERIOR (finalize lo deja escrito); partir de él inflaría el
			# acumulado indefinidamente noche tras noche.
			if str(data.get("status", "")) == "cycle_completed":
				return 0, {}
			metrics = data.get("metrics") or {}
			if not isinstance(metrics, dict):
				metrics = {}
			return int(data.get("total_processed", 0)), {str(k): int(v) for k, v in metrics.items() if isinstance(v, (int, float))}
		except Exception:
			continue
	return 0, {}


def _read_total_processed() -> int:
	"""Total procesado acumulado de la noche (contrato previo, se conserva)."""
	return _read_state()[0]


def _read_memento_ascended() -> int:
	"""Ascensiones estáticas del último pase Memento, si es de esta noche.

	Best-effort: sin fichero, ilegible o viejo → 0. El pase Memento corre ANTES
	del sueño en el nightly (chronicle → sleep); si su marca es fresca, el
	finalize la reporta para no dar la impresión de que el ciclo no ingresó nada.
	"""
	from red_pill.core.paths import get_state_dir

	try:
		data = json.loads((get_state_dir() / _MEMENTO_STATE_FILE).read_text(encoding="utf-8"))
	except Exception:
		return 0
	try:
		age = time.time() - float(data.get("ran_at", 0))
	except (TypeError, ValueError):
		return 0
	if age < 0 or age > _MEMENTO_STATE_MAX_AGE_S:
		return 0
	try:
		return max(int(data.get("static_ascended", 0) or 0), 0)
	except (TypeError, ValueError):
		return 0


def _format_metrics(metrics: Dict[str, int]) -> str:
	"""Desglose compacto de las métricas de fase (solo claves de fase, no sub)."""
	rows = [(k, int(v)) for k, v in (metrics or {}).items() if "." not in k and int(v) > 0]
	rows.sort(key=lambda t: t[1], reverse=True)
	return " · ".join(f"{k}={v}" for k, v in rows)


class SleepRitualMinion(Minion):
	"""Un ritual del ciclo (maintenance, usp, dream, thread) como minion."""

	name: str = "Sleep-Ritual"
	specialization: str = "sleep_cycle_ritual"

	async def execute(self, task: str, **kwargs: Any) -> Dict[str, Any]:
		from red_pill import rituals

		ritual = kwargs.get("ritual") or task
		fn = getattr(rituals, f"{ritual}_ritual", None)
		if fn is None:
			return {"status": "failed", "error": f"ritual '{ritual}' no existe."}
		start = time.time()
		try:
			from red_pill.memory import MemoryManager

			if ritual == "thread":
				await fn()
			else:
				await fn(MemoryManager())
			return {"status": "success", "ritual": ritual, "summary": f"ritual {ritual} ok", "duration": round(time.time() - start, 3)}
		except Exception as e:
			return {"status": "failed", "error": str(e), "ritual": ritual, "duration": round(time.time() - start, 3)}


class SleepPhaseMinion(Minion):
	"""Una fase del pipeline (SLEEP_PHASES[phase_index]) como minion.

	`phase_index` viaja en kwargs (campo `params` de la etapa del DAG). El
	`total_processed` se lee del fichero público previo y se devuelve en el
	dict para que la siguiente fase lo herede.
	"""

	name: str = "Sleep-Phase"
	specialization: str = "sleep_cycle_phase"

	async def execute(self, task: str, **kwargs: Any) -> Dict[str, Any]:
		from red_pill.jobs.drivers.base import JobPauseRequested
		from red_pill.memory import MemoryManager
		from red_pill.metabolism.phases import SLEEP_PHASES
		from red_pill.metabolism.phases.base import SleepContext
		from red_pill.metabolism.sleep import run_sleep_phase

		phase_index = int(kwargs.get("phase_index", 0))
		if not (0 <= phase_index < len(SLEEP_PHASES)):
			return {"status": "failed", "error": f"phase_index {phase_index} fuera de rango ({len(SLEEP_PHASES)} fases)."}
		phase = SLEEP_PHASES[phase_index]
		mode = kwargs.get("mode", "lazy")
		start = time.time()
		try:
			prev_total, prev_metrics = _read_state()
			ctx = SleepContext(
				memory_manager=MemoryManager(),
				mode=mode,
				total_processed=prev_total,
				metrics=prev_metrics,
				sleep_cutoff_ts=float(kwargs.get("sleep_cutoff_ts") or 0),
				# Sonda de pausa a mitad de fase inyectada por el dag_job (solo si
				# la etapa es `pausable`): el drenaje la consulta por batch y lanza
				# JobPauseRequested si el operador pausó el job a medias.
				pause_probe=kwargs.get("pause_probe"),
			)
			run_sleep_phase(ctx, phase_index)
			metrics = dict(getattr(ctx, "metrics", {}) or {})
			produced = int(metrics.get(phase.name, 0) or 0)
			return {
				"status": "success",
				"phase": phase.name,
				"phase_index": phase_index,
				"total_processed": ctx.total_processed,
				"metrics": metrics,
				"summary": f"fase {phase.name} ok (+{produced} ops · acum {ctx.total_processed})",
				"duration": round(time.time() - start, 3),
			}
		except JobPauseRequested:
			# Pausa del operador a mitad de fase: propaga al runner (PAUSED con
			# checkpoint intacto), jamás un fallo de etapa ni un warn-skip.
			raise
		except Exception as e:
			return {"status": "failed", "error": str(e), "phase": phase.name, "phase_index": phase_index}


class SleepFinalizeMinion(Minion):
	"""Finalizador del ciclo: señales, evento y estado — como minion."""

	name: str = "Sleep-Finalize"
	specialization: str = "sleep_cycle_finalize"

	async def execute(self, task: str, **kwargs: Any) -> Dict[str, Any]:
		from red_pill.memory import MemoryManager
		from red_pill.metabolism.phases.base import SleepContext
		from red_pill.metabolism.sleep import finalize_sleep_cycle

		mode = kwargs.get("mode", "lazy")
		try:
			prev_total, prev_metrics = _read_state()
			ctx = SleepContext(
				memory_manager=MemoryManager(),
				mode=mode,
				total_processed=prev_total,
				metrics=prev_metrics,
			)
			total = finalize_sleep_cycle(ctx, mode=mode)
			metrics = dict(getattr(ctx, "metrics", {}) or {})
			breakdown = _format_metrics(metrics)
			ascended = _read_memento_ascended()
			summary = f"ciclo completo ({total} ops"
			if breakdown:
				summary += f": {breakdown}"
			summary += ")"
			if ascended:
				summary += f" · memento ascendidos={ascended}"
			return {
				"status": "success",
				"total_processed": total,
				"metrics": metrics,
				"memento_ascended": ascended,
				"summary": summary,
			}
		except Exception as e:
			return {"status": "failed", "error": str(e)}
