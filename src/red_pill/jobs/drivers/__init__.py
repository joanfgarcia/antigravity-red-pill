"""Registro source → ResumableJobDriver.

El runner consulta este registro para saber qué sources son suyos
(`registered_sources()` alimenta su `allowed_sources` — carril mecánico)
y con qué driver ejecutar cada job. Los sources ajenos (drive_evaluator,
samantha...) nunca aparecen aquí: son carriles de otros consumidores.
"""

from __future__ import annotations

from typing import Dict, List, Type

from red_pill.jobs.drivers.base import JobDeferred, ResumableJobDriver, StepOutcome

__all__ = ["JobDeferred", "ResumableJobDriver", "StepOutcome", "register_driver", "get_driver", "registered_sources"]

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


def registered_sources() -> List[str]:
	"""Sources del carril mecánico (el `allowed_sources` del runner)."""
	return list(_REGISTRY.keys())


# Drivers de serie (importados al final para que se auto-registren sin ciclos).
from red_pill.jobs.drivers.agentic import AgenticJobDriver  # noqa: E402
from red_pill.jobs.drivers.flow import FlowJobDriver  # noqa: E402

register_driver(FlowJobDriver)
register_driver(AgenticJobDriver)

