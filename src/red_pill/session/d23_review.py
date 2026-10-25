"""D23-SCORE v0.1 — auto-revisor de objeciones (job agéntico).

El revisor es un alma dedicada e independiente (`D23_REVIEWER_CONTINUITY_ID`)
que analiza la D-obj y usa las tools del MCP compartido:

- `review`: `suggest_review` (verdict + confidence + reason), sin mutar la D-obj.
- `semi`: `review_decision` si la confianza es alta; si no, `escalate`.
- `auto`: `review_decision` siempre en low/medium; high/retract → `escalate`.
- `off`: no se encola nada; solo el Operador.

El job se encola como `agentic_job` con una cascade de modelos (OpenRouter por
defecto) y hereda la identidad del revisor por env de confianza.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import red_pill.config as cfg
from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.jobs.drivers import get_driver_class
from red_pill.jobs.recipes import load_recipe
from red_pill.session.store import SessionRegistry

logger = logging.getLogger(__name__)

_REVIEW_MODES = {"off", "review", "semi", "auto"}
_REVIEWER_NAMESPACE = uuid.NAMESPACE_URL
_REVIEWER_NAME = "red-pill:d23-reviewer"
_REVIEW_MISSION = "mission:d23-review"


def reviewer_continuity() -> str:
	"""Alma estable del revisor (independiente del autor y del objetor)."""
	configured = str(getattr(cfg.get_config(), "D23_REVIEWER_CONTINUITY_ID", "") or "").strip()
	if configured:
		return configured
	return str(uuid.uuid5(_REVIEWER_NAMESPACE, _REVIEWER_NAME))


def review_mode() -> str:
	mode = str(getattr(cfg.get_config(), "D23_REVIEW_MODE", "off") or "off").strip().lower()
	return mode if mode in _REVIEW_MODES else "off"


def _repo_root() -> Path:
	# src/red_pill/session/d23_review.py → repo root
	return Path(__file__).resolve().parents[3]


def _recipe_ref() -> Path:
	raw = str(getattr(cfg.get_config(), "D23_REVIEW_RECIPE", "") or "configs/jobs/d23-review.yaml").strip()
	path = Path(raw).expanduser()
	return path if path.is_absolute() else (_repo_root() / path)


def build_prompt(decision: Dict[str, Any], note: Dict[str, Any], mode: str) -> str:
	"""Prompt cerrado del revisor; el modo decide tool y margen de decisión."""
	decision_id = str(decision.get("decision_id") or "")
	note_author = str(note.get("continuity_id") or "desconocido")
	objector = str(decision.get("created_by") or "desconocido")
	claim = str(decision.get("claim") or "")
	evidence = str(decision.get("evidence") or "")
	severity = str(decision.get("severity") or "low")
	proposed = str(decision.get("proposed_action") or "flag")
	state = str(decision.get("state") or "open")
	requires = "sí" if decision.get("requires_operator") else "no"
	note_summary = str(note.get("summary") or "")
	note_ref = str(note.get("ref") or "")
	mission = str(decision.get("mission_id") or "")

	if mode == "review":
		tool_rule = (
			"Llama a `suggest_review` con decision_id, verdict (uphold|dismiss|escalate), "
			"confidence (low|medium|high) y reason. NO llames a `review_decision` y NO "
			"modifiques la nota: el Operador decidirá."
		)
	elif mode == "semi":
		tool_rule = (
			"Si tu confianza es high, llama a `review_decision` con uphold o dismiss. "
			"Si no estás seguro, llama a `review_decision` con escalate. NO modifiques la nota."
		)
	else:
		tool_rule = (
			"Llama a `review_decision` SIEMPRE. En low/medium decide uphold o dismiss. "
			"Si la D-obj requiere Operador (high/retract) o ya está escalated, usa escalate. "
			"NO modifiques la nota."
		)

	return (
		"<d23_review>\n"
		"Eres el revisor independiente de D23-SCORE. Analiza la objeción sobre una nota del coro.\n"
		f"Modo: {mode}\n"
		f"D-obj: {decision_id}\n"
		f"Misión: {mission}\n"
		f"Nota ({note_ref or 'sin ref'}): {note_summary}\n"
		f"Autor de la nota (alma): {note_author}\n"
		f"Objetor (alma): {objector}\n"
		f"Claim: {claim}\n"
		f"Evidencia: {evidence or '(sin evidencia)'}\n"
		f"Severidad: {severity} · Acción propuesta: {proposed} · Requiere Operador: {requires}\n"
		f"Estado actual: {state}\n\n"
		f"{tool_rule}\n\n"
		"Reglas: no modifiques ni ocultes la nota, no publiques eventos, no ejecutes shell. "
		"Sé breve, cita la evidencia y no inventes hechos. Si la objeción es de alto impacto "
		"o no puedes decidir, escala al Operador.\n"
		"</d23_review>"
	)


def enqueue_review(
	decision: Dict[str, Any],
	note: Dict[str, Any],
	mode: Optional[str] = None,
) -> Optional[str]:
	"""Encola el job revisor para una D-obj. Devuelve job_id o None."""
	mode_value = (mode or review_mode()).strip().lower()
	if mode_value not in {"review", "semi", "auto"}:
		return None
	decision_id = str(decision.get("decision_id") or "").strip()
	if not decision_id:
		return None
	recipe = _recipe_ref()
	try:
		source, payload, priority, _parent, is_seed = load_recipe(str(recipe))
	except (FileNotFoundError, ValueError) as e:
		logger.warning("[D23 review] recipe %s no disponible: %s", recipe, e)
		return None
	if is_seed:
		logger.warning("[D23 review] recipe %s es seed; no se encola", recipe)
		return None
	if source != "agentic_job":
		logger.warning("[D23 review] recipe %s source=%s (se esperaba agentic_job)", recipe, source)
		return None

	reviewer = reviewer_continuity()
	payload = dict(payload)
	payload.update(
		{
			"prompt": build_prompt(decision, note, mode_value),
			"continuity_id": reviewer,
			"parent_mission_id": str(decision.get("mission_id") or ""),
			"originator": f"d23-review:{decision_id}",
			"role": "reviewer",
			"title": f"D23 review {decision_id[:8]}",
		}
	)
	payload.setdefault("cwd", str(_repo_root()))
	try:
		driver_cls = get_driver_class(source)
		if driver_cls:
			driver_cls().validate(payload)
	except Exception as e:
		logger.warning("[D23 review] payload inválido: %s", e)
		return None

	try:
		queue = CognitiveQueueManager()
		job_id = queue.enqueue_task(
			source=source,
			payload=payload,
			priority=int(priority or 4),
			mission_id=_REVIEW_MISSION,
		)
	except Exception as e:
		logger.error("[D23 review] no se pudo encolar: %s", e)
		return None

	try:
		SessionRegistry().register_review_job(
			decision_id,
			job_id=job_id,
			reviewer_continuity_id=reviewer,
			mode=mode_value,
		)
	except Exception as e:
		logger.warning("[D23 review] no se pudo registrar el review job %s: %s", job_id, e)
	return job_id
