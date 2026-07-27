"""Registro source → ResumableJobDriver.

El runner consulta este registro para saber qué sources son suyos
(`registered_sources()` alimenta su `allowed_sources` — carril mecánico)
y con qué driver ejecutar cada job. Los sources ajenos (drive_evaluator,
samantha...) nunca aparecen aquí: son carriles de otros consumidores.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from red_pill.jobs.drivers.base import (
	JobDeferred,
	JobStepTimeout,
	ResumableJobDriver,
	StepOutcome,
	append_job_log,
	compute_step_timeout,
	human_duration,
	job_log_path,
	update_step_ema,
)

__all__ = [
	"JobDeferred",
	"JobStepTimeout",
	"ResumableJobDriver",
	"StepOutcome",
	"append_job_log",
	"compute_step_timeout",
	"human_duration",
	"job_log_path",
	"update_step_ema",
	"register_driver",
	"get_driver",
	"get_driver_class",
	"registered_sources",
]

_REGISTRY: Dict[str, Type[ResumableJobDriver]] = {}


def register_driver(driver_cls: Type[ResumableJobDriver]) -> Type[ResumableJobDriver]:
	"""Registra un driver por su `source`. Usable como decorador de clase."""
	if not driver_cls.source:
		raise ValueError(f"{driver_cls.__name__} must define a non-empty `source`.")
	existing = _REGISTRY.get(driver_cls.source)
	if existing is not None and existing is not driver_cls:
		raise ValueError(f"Source '{driver_cls.source}' already registered by {existing.__name__}.")
	_REGISTRY[driver_cls.source] = driver_cls
	return driver_cls


def get_driver(source: str) -> ResumableJobDriver:
	"""Instancia el driver del source dado. KeyError si no hay driver registrado."""
	return _REGISTRY[source]()


def get_driver_class(source: str) -> Optional[Type[ResumableJobDriver]]:
	"""Clase del driver (sin instanciar) — la usa el CLI para `validate()` en el submit."""
	return _REGISTRY.get(source)


def registered_sources() -> List[str]:
	"""Sources del carril mecánico (el `allowed_sources` del runner)."""
	return list(_REGISTRY.keys())


# Drivers de serie (importados al final para que se auto-registren sin ciclos).
from red_pill.jobs.drivers.agentic import AgenticJobDriver  # noqa: E402
from red_pill.jobs.drivers.bit_training import BitTrainingDriver  # noqa: E402
from red_pill.jobs.drivers.distill import DistillJobDriver  # noqa: E402
from red_pill.jobs.drivers.flow import FlowJobDriver  # noqa: E402
from red_pill.jobs.drivers.script import ScriptJobDriver  # noqa: E402

register_driver(FlowJobDriver)
register_driver(AgenticJobDriver)
register_driver(DistillJobDriver)
register_driver(ScriptJobDriver)
# BitTrainingDriver queda registrado a propósito hasta que el camino genérico
# (ScriptJobDriver) complete una fase real del curriculum: es la red de
# seguridad y la vía de rollback del entrenamiento en curso (D3 del RFC).
register_driver(BitTrainingDriver)
