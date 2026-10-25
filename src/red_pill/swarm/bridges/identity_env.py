"""Env de confianza para arneses externos (RFC-INTEROP-003 S6/D-12).

El hijo opencode/claude/pi hereda el alma por variables de entorno, nunca por
prompt: el modelo no puede declarar ni cambiar su `continuity_id`. Solo se
exportan IDs; jamás tokens, prompts ni credenciales.
"""

from __future__ import annotations

import os
from typing import Dict, Optional


def identity_env(
	*,
	continuity_id: Optional[str] = None,
	mission_id: Optional[str] = None,
	parent_mission_id: Optional[str] = None,
	originator: Optional[str] = None,
	role: Optional[str] = None,
	job_id: Optional[str] = None,
) -> Dict[str, str]:
	"""Variables `REDPILL_*` presentes y no vacías.

	`REDPILL_MISSION_ID` es la misión del alma (`parent_mission_id`) cuando
	existe; la misión de aislamiento del forge no debe suplantarla.
	"""
	env: Dict[str, str] = {}
	values = {
		"REDPILL_CONTINUITY_ID": continuity_id,
		"REDPILL_MISSION_ID": parent_mission_id or mission_id,
		"REDPILL_PARENT_MISSION_ID": parent_mission_id,
		"REDPILL_ORIGINATOR": originator,
		"REDPILL_ROLE": role,
		"REDPILL_JOB_ID": job_id,
	}
	for key, value in values.items():
		text = str(value or "").strip()
		if text:
			env[key] = text
	return env


def merged_env(identity: Dict[str, str], *, base: Optional[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
	"""`os.environ` + identidad; `None` si no hay nada que añadir (no toca el hijo)."""
	if not identity:
		return None
	env = dict(base if base is not None else os.environ)
	env.update(identity)
	return env
