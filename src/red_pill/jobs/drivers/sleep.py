"""SleepJobDriver — el ciclo de sueño como job reanudable paso a paso.

Ejecuta el ciclo de sueño en proceso por UNIDADES atómicas (RFC_SLEEP_JOB_DRIVER,
APROBADO PARA DISEÑO 2026-08-04): un ritual o una fase por step. El checkpoint en
la BD de la cola es AUTORITATIVO para resume; el fichero público
`sleep_phase_status.json` queda como TELECOMETRÍA en vivo (auditoría A2).

Unidades (replican fielmente `trigger_pulse.py --cycle sleep`):

	idx  unidad                  fuente                          GPU
	0    maintenance             rituals.maintenance_ritual       no
	1    usp                     rituals.usp_ritual               no
	2    dream                   rituals.dream_ritual             no
	3..12 consolidation:1..10    SLEEP_PHASES por índice          sí (1ª fase)
	13   thread                  rituals.thread_ritual            no

Semántica de fallo por unidad (fiel al pulso actual): best-effort, try/except,
skip marcado y avanza `resume_unit` — el job NUNCA falla por una unidad que
revienta (no quema attempts ni dispara el disyuntor).

Política de GPU por unidad: solo inferencia en GPU; espera via `JobDeferred`
(R1, sin fallback a CPU) cuando la GPU no está usable. Las unidades CPU corren
siempre.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from typing import Any, Dict, List, Tuple

from red_pill.jobs.drivers.base import JobDeferred, ResumableJobDriver, StepOutcome

logger = logging.getLogger(__name__)


def _gpu_health_probe() -> Tuple[bool, int, int]:
	"""Probe de salud GPU real (D7): nvidia-smi exit 0 + VRAM efectiva + -ngl efectivo.

	Devuelve (usable, free_mb, ngl). `ngl` = -ngl efectivo del llama-server en
	marcha (0 = sirve en CPU disfrazada). Un `nvidia-smi` que falla es GPU NO
	disponible, nunca 0 MB silencioso.
	"""
	# 1. nvidia-smi con exit code 0 (no solo presencia de binario).
	if not shutil.which("nvidia-smi"):
		return False, 0, 0
	try:
		free_out = subprocess.run(
			["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
			capture_output=True, text=True, timeout=5,
		)
		if free_out.returncode != 0:
			return False, 0, 0
		free_mb = int(free_out.stdout.strip().split("\n")[0].strip())
	except Exception:
		return False, 0, 0

	# 2. -ngl efectivo del llama-server (si está en marcha): ngl=0 → CPU-disfrazada.
	ngl = -1  # -1 = sin proceso llama observado (no bloquea)
	try:
		ps = subprocess.run(["pgrep", "-af", "llama-server"], capture_output=True, text=True, timeout=5)
		for line in (ps.stdout or "").splitlines():
			low = line.lower()
			if "-ngl" in low:
				parts = line.split()
				for i, part in enumerate(parts):
					if part.startswith("-ngl"):
						try:
							# Soporta `-ngl=33`, `-ngl33` y `-ngl 33` (valor en el
							# siguiente token).
							if "=" in part:
								ngl = int(part.split("=")[-1])
							elif part != "-ngl" and part[4:].lstrip("-").isdigit():
								ngl = int(part[4:])
							elif i + 1 < len(parts):
								ngl = int(parts[i + 1])
						except Exception:
							ngl = 0
						break
	except Exception:
		pass

	return True, free_mb, ngl


class SleepJobDriver(ResumableJobDriver):
	source = "sleep_job"
	min_vram_mb = 0  # la GPU se gestiona por unidad en preflight; el gate genérico
	# del runner no debe re-bloquear unidades CPU.

	# Unidades que necesitan inferencia LLM: SOLO GPU, esperan via deferral.
	_GPU_UNITS = {"consolidation", "revision", "operator_profile", "recent_activity"}

	@classmethod
	def validate(cls, payload: Dict[str, Any]) -> None:
		mode = payload.get("mode", "lazy")
		if mode not in ("lazy", "deep"):
			raise ValueError(f"sleep_job payload 'mode' debe ser 'lazy' o 'deep', no '{mode}'.")
		total = int(payload.get("total_units", 14))
		if total < 1:
			raise ValueError("sleep_job payload 'total_units' debe ser >= 1.")

	def _unit_table(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""Tabla de unidades del ciclo (fiel al pulso `--cycle sleep`)."""
		units: List[Dict[str, Any]] = [
			{"unit": "maintenance", "kind": "ritual", "ritual": "maintenance", "requires_gpu": False},
			{"unit": "usp", "kind": "ritual", "ritual": "usp", "requires_gpu": False},
			{"unit": "dream", "kind": "ritual", "ritual": "dream", "requires_gpu": False},
		]
		from red_pill.metabolism.phases import SLEEP_PHASES

		for i, phase in enumerate(SLEEP_PHASES):
			units.append({
				"unit": f"{phase.name}:{i + 1}",
				"kind": "phase",
				"phase_index": i,
				"phase_name": phase.name,
				"requires_gpu": phase.requires_gpu,
			})
		units.append({"unit": "thread", "kind": "ritual", "ritual": "thread", "requires_gpu": False})
		return units

	def _preflight_unit_gpu(self, unit: Dict[str, Any], payload: Dict[str, Any]) -> None:
		"""Probe de salud GPU real por unidad (D7) — espera, nunca CPU-disfrazada."""
		if not unit.get("requires_gpu"):
			return
		# LLM residente online Y en backend GPU real → adelante sin más probes.
		from red_pill.metabolism.ephemeral_server import _check_llm_available

		if _check_llm_available():
			usable, _free, ngl = _gpu_health_probe()
			if usable and (ngl == -1 or ngl > 0):
				return
		usable, free_mb, ngl = _gpu_health_probe()
		if not usable:
			raise JobDeferred(f"GPU no disponible para {unit['unit']} (nvidia-smi no responde).")
		if ngl == 0:
			raise JobDeferred(f"LLM sirve en CPU disfrazada (-ngl 0) para {unit['unit']}: esperando GPU.")
		import red_pill.config as cfg

		min_free = int(payload.get("min_vram_mb", getattr(cfg, "SLEEP_MIN_FREE_VRAM_MB", 3500)))
		if free_mb < min_free:
			raise JobDeferred(f"VRAM insuficiente para {unit['unit']} ({free_mb}MB libres < {min_free}MB).")

	def _run_ritual(self, mm, ritual: str) -> None:
		"""Ejecuta un ritual (coroutine) en un hilo, como el pulso real."""
		from red_pill import rituals

		fn = getattr(rituals, f"{ritual}_ritual", None)
		if fn is None:
			raise ValueError(f"ritual '{ritual}' no existe.")
		asyncio.run(fn(mm))

	def _run_phase(self, ctx, phase_index: int) -> None:
		"""Ejecuta UNA fase del pipeline (unidad atómica)."""
		from red_pill.metabolism.sleep import run_sleep_phase

		run_sleep_phase(ctx, phase_index)

	def _run_thread(self) -> None:
		"""Unidad thread: ritual thread (subproceso, idempotente por naturaleza)."""
		from red_pill import rituals

		asyncio.run(rituals.thread_ritual())

	def _write_public_status(self, payload: Dict[str, Any], unit: Dict[str, Any], ctx, new_index: int, total_units: int, status: str, total_phases: int = 1) -> None:
		"""Telemetría en vivo (espejo del checkpoint en BD — auditoría A2)."""
		try:
			ctx.update_status(
				unit.get("phase_name") or unit.get("unit"),
				status=status,
				phase_index=(unit.get("phase_index") or 0) + 1 if unit.get("kind") == "phase" else 0,
				total_phases=total_phases,
				unit=unit.get("unit"),
				unit_index=new_index,
				total_units=total_units,
			)
		except Exception as e:
			logger.warning(f"[SleepJob] telemetría no escrita: {e}")

	def preflight(self, payload: Dict[str, Any]) -> None:
		"""Entorno básico del ciclo (MemoryManager) → deferral R1, no fallo."""
		try:
			from red_pill.memory import MemoryManager

			MemoryManager()
		except Exception as e:
			raise JobDeferred(f"MemoryManager no disponible: {e}") from e

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		from red_pill.memory import MemoryManager
		from red_pill.metabolism.phases import SLEEP_PHASES
		from red_pill.metabolism.phases.base import SleepContext

		units = self._unit_table(payload)
		total_units = len(units)
		resume_unit = int(checkpoint_data.get("resume_unit", 0))
		total_processed = int(checkpoint_data.get("total_processed", 0))
		mode = payload.get("mode", "lazy")

		if resume_unit >= total_units:
			# Ciclo ya completo: el finalizador corre una única vez (unidad 14).
			if checkpoint_data.get("finalized"):
				return StepOutcome(completed=True, new_checkpoint=checkpoint_data, summary="sleep cycle already complete")
			return self._run_finalize(payload, checkpoint_data, total_units)

		unit = units[resume_unit]

		# Preflight GPU por unidad (D7): espera via deferral, jamás CPU-disfrazada.
		self._preflight_unit_gpu(unit, payload)

		mm = MemoryManager()
		ctx = SleepContext(memory_manager=mm, mode=mode, total_processed=total_processed)

		unit_failed = False
		try:
			if unit["kind"] == "ritual":
				if unit["ritual"] == "thread":
					self._run_thread()
				else:
					self._run_ritual(mm, unit["ritual"])
			else:
				self._run_phase(ctx, unit["phase_index"])
		except Exception as e:
			# Fallo de unidad = skip marcado, NUNCA fallo de job (fiel al pulso).
			unit_failed = True
			logger.warning(f"[SleepJob] {self.short_id} unidad {unit['unit']} fallida (skip): {e}")

		new_index = resume_unit + 1
		ctx.total_processed = getattr(ctx, "total_processed", total_processed)
		self._write_public_status(
			payload, unit, ctx, new_index, total_units,
			"deferred" if ctx.deferred else ("failed" if unit_failed else "running"),
			total_phases=len(SLEEP_PHASES) if unit.get("kind") == "phase" else 1,
		)

		checkpoint = {
			"resume_unit": new_index,
			"total_processed": ctx.total_processed,
			"mode": mode,
			"total_units": total_units,
		}
		if unit_failed:
			checkpoint["last_failed_unit"] = unit["unit"]

		progress = {
			"current": new_index,
			"total": total_units,
			"stage_current": (unit.get("phase_index") or 0) + 1 if unit.get("kind") == "phase" else new_index,
			"stage_total": len(SLEEP_PHASES) if unit.get("kind") == "phase" else 1,
			"stage_label": "fase",
			"total_processed": ctx.total_processed,
		}

		if new_index >= total_units:
			return self._run_finalize(payload, checkpoint, total_units, ctx=ctx)

		return StepOutcome(
			completed=False,
			new_checkpoint=checkpoint,
			summary=f"unidad {new_index}/{total_units}: {unit['unit']}",
			progress=progress,
		)

	def _run_finalize(self, payload: Dict[str, Any], checkpoint: Dict[str, Any], total_units: int, ctx=None) -> StepOutcome:
		"""Finalizador del ciclo (solo última unidad): señales, evento, status."""
		from red_pill.metabolism.phases.base import SleepContext
		from red_pill.metabolism.sleep import finalize_sleep_cycle

		if ctx is None:
			from red_pill.memory import MemoryManager

			ctx = SleepContext(
				memory_manager=MemoryManager(),
				mode=payload.get("mode", "lazy"),
				total_processed=int(checkpoint.get("total_processed", 0)),
			)
		finalize_sleep_cycle(ctx, mode=payload.get("mode", "lazy"))
		done = dict(checkpoint)
		done["finalized"] = True
		return StepOutcome(
			completed=True,
			new_checkpoint=done,
			summary=f"ciclo completo ({done.get('total_processed', 0)} engramas)",
			progress={"current": total_units, "total": total_units, "percent": 100},
		)
