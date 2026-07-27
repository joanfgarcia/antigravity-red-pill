"""ResumableJobDriver — contrato de paso atómico del Centralized Job Manager.

Un driver convierte un trabajo pesado en una secuencia de steps atómicos:
pausar = no invocar el siguiente step(); jamás se interrumpe una transacción
a medias. El runner persiste `new_checkpoint` tras cada step, por lo que un
crash entre step y persistencia re-ejecuta como mucho UN step (at-least-once):
cada step() debe ser idempotente o tolerante a re-ejecución.

Política de timeout (RFC ScriptJobDriver §4c): vive AQUÍ, no en cada driver.
Es un detector de cuelgue, no un SLA — cotas generosas, adaptativas al
historial del propio job y duplicadas por intento.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class StepOutcome:
	"""Resultado de un step atómico."""

	completed: bool
	new_checkpoint: Dict[str, Any] = field(default_factory=dict)
	summary: str = ""
	progress: Optional[Dict[str, Any]] = None  # { current, total, percent, ... }


class JobDeferred(Exception):
	"""El entorno no está disponible (VRAM ocupada, IDE cerrado, SIP caído).

	El runner devuelve el job a PENDING SIN incrementar attempts (regla R1):
	el disyuntor de frustración es para fallos reales del job, no del entorno.
	"""

	def __init__(self, reason: str):
		self.reason = reason
		super().__init__(reason)


class JobStepTimeout(Exception):
	"""El step excedió su cota de tiempo y fue abatido como cgroup completo.

	Es un fallo real (attempts++), pero con rastro forense: el runner escribe
	la cota, la media observada y el intento en el log del job, en `error_log`
	y en la marca `dirty_kill` del checkpoint, para poder recalibrar después.
	"""

	def __init__(self, elapsed_s: float, bound_s: int, ema_s: float, attempt: int):
		self.elapsed_s = elapsed_s
		self.bound_s = bound_s
		self.ema_s = ema_s
		self.attempt = attempt
		super().__init__(f"step abatido por timeout tras {elapsed_s / 60:.1f} min (cota {bound_s / 60:.1f} min, media {ema_s / 60:.1f} min, intento {attempt})")

	def forensics(self) -> Dict[str, Any]:
		"""Datos para la marca `dirty_kill` — con esto se recalibra la cota."""
		return {
			"reason": "timeout",
			"elapsed_s": round(self.elapsed_s),
			"bound_s": self.bound_s,
			"ema_s": round(self.ema_s),
			"attempt": self.attempt,
		}


def human_duration(seconds: float) -> str:
	"""Duración legible sin mentir por redondeo: segundos, minutos u horas."""
	seconds = float(seconds or 0)
	if seconds < 90:
		return f"{seconds:.0f} s"
	if seconds < 5400:
		return f"{seconds / 60:.1f} min"
	return f"{seconds / 3600:.1f} h"


def job_log_path(job_id: str) -> Path:
	"""Log por job. Un driver genérico no puede tragarse la salida del hijo:
	sin esto, el error real se pierde detrás del banner del envoltorio."""
	from red_pill.core.paths import get_state_dir

	return get_state_dir() / "jobs" / f"{(job_id or 'unbound')[:8]}.log"


def append_job_log(job_id: str, message: str) -> None:
	"""Anota una línea del runner en el log del job (best-effort, nunca rompe el step)."""
	try:
		path = job_log_path(job_id)
		path.parent.mkdir(parents=True, exist_ok=True)
		with open(path, "a", encoding="utf-8") as log_file:
			log_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
	except Exception:
		pass


def compute_step_timeout(payload: Dict[str, Any], progress: Optional[Dict[str, Any]], attempts: int = 0) -> int:
	"""Cota de tiempo para el próximo step, en segundos (detector de cuelgue).

	Sin historial: `control.max_step_minutes` del payload, o el default generoso.
	Con historial: `max(FACTOR × EMA, FLOOR)` — la media viaja con el job, así que
	un cambio de hardware o un fallback GPU→CPU no contamina a otros jobs.
	Cada intento previo duplica la cota: un step legítimamente degradado a CPU
	sobrevive al segundo intento; un cuelgue real agota el disyuntor igual.
	"""
	import red_pill.config as cfg

	declared = (payload.get("control") or {}).get("max_step_minutes")
	ema = (progress or {}).get("step_seconds_ema")

	if ema:
		bound = max(int(cfg.JOB_STEP_TIMEOUT_FACTOR * float(ema)), int(cfg.JOB_STEP_TIMEOUT_FLOOR))
	elif declared:
		bound = int(declared) * 60
	else:
		bound = int(cfg.JOB_STEP_TIMEOUT_DEFAULT)

	return bound * (2 ** max(0, int(attempts)))


def update_step_ema(progress: Optional[Dict[str, Any]], elapsed_s: float) -> Dict[str, Any]:
	"""Mezcla la duración observada del step en el progreso (media móvil + ETA).

	La EMA alimenta dos cosas a la vez: la cota de timeout del siguiente step y
	el ETA de los jobs con total conocido. Se calcula en el runner para que
	ningún driver tenga que reimplementarla.
	"""
	import red_pill.config as cfg

	merged = dict(progress or {})
	previous = merged.get("step_seconds_ema")
	alpha = float(cfg.JOB_STEP_EMA_ALPHA)
	merged["step_seconds_last"] = round(elapsed_s, 1)
	merged["step_seconds_ema"] = round(elapsed_s if not previous else alpha * elapsed_s + (1 - alpha) * float(previous), 1)

	current, total = merged.get("current"), merged.get("total")
	if isinstance(current, (int, float)) and isinstance(total, (int, float)) and total > current:
		merged["eta_seconds"] = round((total - current) * merged["step_seconds_ema"])
	else:
		merged.pop("eta_seconds", None)

	return merged


class ResumableJobDriver(ABC):
	"""Contrato de ejecución reanudable.

	Atributos de clase:
	- source: source de la cola que este driver consume (carril propio).
	- min_vram_mb: VRAM mínima para un step (0 = CPU-only / backend remoto).
		El runner comprueba VramProbe ANTES de cada step y difiere si no hay
		margen — salvo que el modelo ya esté residente (preflight del driver).
	"""

	source: str = ""
	min_vram_mb: int = 0

	# Contexto de la ejecución en curso, inyectado por el runner vía bind().
	job_id: str = ""
	attempts: int = 0
	step_timeout_s: int = 0

	def bind(self, job_id: str, attempts: int = 0, step_timeout_s: int = 0) -> None:
		"""Ata el driver al job concreto antes de preflight/step.

		El scope de systemd y el log por job se nombran con este id. La cota de
		timeout la calcula el RUNNER (política uniforme, `compute_step_timeout`)
		y el driver solo la aplica: ningún driver reinventa la política.
		"""
		self.job_id = job_id
		self.attempts = attempts
		self.step_timeout_s = step_timeout_s

	@property
	def short_id(self) -> str:
		"""Id corto — nombra el scope de systemd y el fichero de log del job."""
		return (self.job_id or "unbound")[:8]

	@classmethod
	def validate(cls, payload: Dict[str, Any]) -> None:
		"""Valida el payload EN EL SUBMIT. Lanza ValueError con motivo claro.

		Un payload malformado debe fallar al encolar, no tres intentos después
		y FRUSTRATED a las 3 de la mañana. Default: no-op.
		"""

	def preflight(self, payload: Dict[str, Any]) -> None:
		"""Comprobación de entorno previa al step. Lanza JobDeferred si no está listo.

		Default: no-op. Los drivers con requisitos (IDE abierto, SIP arriba,
		modelo residente) lo sobreescriben.
		"""

	def teardown(self, payload: Dict[str, Any]) -> None:
		"""Restaura lo que preflight alteró. Se invoca en TODAS las salidas.

		Fin, pausa, kill, deferral y fallo — nunca entre steps consecutivos
		(recargar un modelo residente entre épocas es thrash puro). El caso
		crítico es el deferral: sin teardown, un job que cede ante el ciclo de
		sueño dejaría el residente descargado toda la noche. Default: no-op.
		"""

	@abstractmethod
	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		"""Ejecuta UN paso atómico (1 engrama, 1 etapa de flow) y retorna el nuevo checkpoint."""
