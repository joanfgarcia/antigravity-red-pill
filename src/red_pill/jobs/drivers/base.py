"""ResumableJobDriver — contrato de paso atómico del Centralized Job Manager.

Un driver convierte un trabajo pesado en una secuencia de steps atómicos:
pausar = no invocar el siguiente step(); jamás se interrumpe una transacción
a medias. El runner persiste `new_checkpoint` tras cada step, por lo que un
crash entre step y persistencia re-ejecuta como mucho UN step (at-least-once):
cada step() debe ser idempotente o tolerante a re-ejecución.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class StepOutcome:
	"""Resultado de un step atómico."""

	completed: bool
	new_checkpoint: Dict[str, Any] = field(default_factory=dict)
	summary: str = ""
	progress: Optional[Dict[str, Any]] = None  # { current_step, total_steps, percent }


class JobDeferred(Exception):
	"""El entorno no está disponible (VRAM ocupada, IDE cerrado, SIP caído).

	El runner devuelve el job a PENDING SIN incrementar attempts (regla R1):
	el disyuntor de frustración es para fallos reales del job, no del entorno.
	"""

	def __init__(self, reason: str):
		self.reason = reason
		super().__init__(reason)


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

	def preflight(self, payload: Dict[str, Any]) -> None:
		"""Comprobación de entorno previa al step. Lanza JobDeferred si no está listo.

		Default: no-op. Los drivers con requisitos (IDE abierto, SIP arriba,
		modelo residente) lo sobreescriben.
		"""

	@abstractmethod
	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		"""Ejecuta UN paso atómico (1 engrama, 1 etapa de flow) y retorna el nuevo checkpoint."""
