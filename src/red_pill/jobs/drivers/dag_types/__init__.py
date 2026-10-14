"""DAG stage-type registry (RFC-JOB_DAG; CONVENTIONS §10.8.3).

Each node type lives in its own module and self-registers on import. The
validator / composer / executor resolve the handler by `stage["type"]` — no
`if type ==` ladders. Adding a DAG node = write `dag_types/<kind>.py` +
`register(<Kind>StageType())`; nothing else changes.
"""

from __future__ import annotations

from . import agent, command, compound, dag  # noqa: F401  (import → self-register)
from .base import LeafStageType, StageContext, StageType, get_stage_type, register, registered_kinds

__all__ = [
	"StageContext",
	"StageType",
	"LeafStageType",
	"get_stage_type",
	"register",
	"registered_kinds",
]
