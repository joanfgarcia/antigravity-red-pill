"""Ascensión curada Memento → Qdrant (RFC-002 Fase 4, §3).

Memento es el archivo; la memoria curada vive en `work_memories`/`social_memories`.
`ascender()` promociona un `refine/*.md` a engrama curado. Es **idempotente**:
el point id se deriva de `(session_id, source_lines)`, así que re-promover el
mismo refine es un upsert, nunca un duplicado. El sello (`ascended: true`) vive
en el frontmatter del refine — Memento sigue siendo la fuente de verdad.

El gate de curaduría (§4.6) decide *qué* asciende; este módulo solo ejecuta la
promoción. El ascenso por refuerzo (`weave_memento_reinforcement`) y el estático
(umbral de significance) se apoyan en esta misma función.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from red_pill.memento.render import update_frontmatter_fields

logger = logging.getLogger(__name__)

# Claves del frontmatter del refine que sellan el estado de ascensión.
# Se declaran en `refine_session` con defaults para poder actualizarlas in-place
# (sin mover el cuerpo del refine — §4.5.1).
ASCENSION_FIELDS = ("ascended", "ascended_at", "ascended_to", "ascended_point_id")

# Estabilidad de refuerzo (RFC-002 Fase 4 §3.2). Provisionales; el experimento de
# calibración (§6.9) los ajusta antes del enforce.
POLAROID_TAU_DEFAULT = 90.0  # días: un tema silenciado ~3 meses pierde la mayor parte de la estabilidad
POLAROID_GAIN_DEFAULT = 1.0  # incremento por reaparición
POLAROID_REVIVAL_GATE_DEFAULT = 5.0  # umbral de ascenso por refuerzo


def _polaroid_cfg(default: float, key: str) -> float:
	try:
		import red_pill.config as cfg

		return float(getattr(cfg, key, default))
	except Exception:
		return default


def polaroid_decay(stability: float, last_reinforced_at: Any, now: float, tau: float) -> float:
	"""Decaimiento exponencial entre refuerzos: S *= e^(-Δt/τ) (modelo half-life).

	`last_reinforced_at` puede ser None (sin historia → sin decay), epoch float,
	o ISO string (timezone-aware). `tau` en días, `now` en segundos."""
	if stability <= 0 or not last_reinforced_at:
		return stability
	from datetime import date as _date

	from red_pill.memento.render import _to_datetime

	if isinstance(last_reinforced_at, datetime):
		last_dt = last_reinforced_at
	elif isinstance(last_reinforced_at, _date):
		last_dt = datetime(last_reinforced_at.year, last_reinforced_at.month, last_reinforced_at.day, tzinfo=timezone.utc)
	else:
		last_dt = _to_datetime(last_reinforced_at)
	if last_dt is None:
		return stability
	dt_days = max(0.0, (now - last_dt.timestamp()) / 86400.0)
	return stability * math.exp(-dt_days / max(tau, 0.1))


def reinforce_refine(
	root: Path,
	registry: Any,
	refine_path: Path,
	*,
	now: Optional[float] = None,
	tau: Optional[float] = None,
	gain: Optional[float] = None,
	memory_manager: Any = None,
) -> Dict[str, Any]:
	"""Aplica un refuerzo a un refine NO ascendido: decay temporal + GAIN, y si la
	estabilidad resultante supera el gate de resurrección, lo asciende (Fase 4 §3.2).

	- `tau`/`gain`/gate: del config (POLAROID_TAU/GAIN/REVIVAL_GATE) con defaults
	provisionales si no están declarados.
	- Escribe `polaroid_stability` y `last_reinforced_at` en el frontmatter
	(in-place, atómico) y los espeja en el registry.
	- Los refinados ya ascendidos no se refuerzan (dejan de competir).
	"""
	if now is None:
		now = time.time()
	tau = _polaroid_cfg(POLAROID_TAU_DEFAULT, "POLAROID_TAU") if tau is None else tau
	gain = _polaroid_cfg(POLAROID_GAIN_DEFAULT, "POLAROID_GAIN") if gain is None else gain
	gate = _polaroid_cfg(POLAROID_REVIVAL_GATE_DEFAULT, "POLAROID_REVIVAL_GATE")

	refine_path = Path(refine_path)
	fm, body = parse_refine(refine_path.read_text(encoding="utf-8"))
	if not body:
		return {"reinforced": False, "reason": "empty_body"}
	if fm.get("ascended"):
		return {"reinforced": False, "reason": "already_ascended", "stability": float(fm.get("polaroid_stability", 0.0) or 0.0)}

	source = str(fm.get("source") or "")
	session_id = str(fm.get("session_id") or "")

	stability = float(fm.get("polaroid_stability", 0.0) or 0.0)
	last_reinforced = fm.get("last_reinforced_at")
	decayed = polaroid_decay(stability, last_reinforced, now, tau)
	new_stability = decayed + gain
	last_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

	update_frontmatter_fields(
		refine_path,
		{"polaroid_stability": round(new_stability, 2), "last_reinforced_at": last_iso},
	)
	if source and session_id:
		registry.upsert(source, session_id, {"polaroid_stability": round(new_stability, 2), "last_reinforced_at": last_iso})

	if new_stability >= gate:
		logger.info(f"[POLAROID] {refine_path.name} estabilidad {new_stability:.2f} ≥ gate {gate} — asciende por refuerzo")
		ascended = ascender(root, registry, refine_path, memory_manager=memory_manager)
		return {"reinforced": True, "stability": round(new_stability, 2), "gate": gate, "ascended": ascended.get("ascended", False)}

	return {"reinforced": True, "stability": round(new_stability, 2), "gate": gate, "ascended": False}


def parse_refine(text: str) -> Tuple[Dict[str, Any], str]:
	"""`refine/*.md` → (frontmatter dict, cuerpo). El frontmatter se serializa como
	YAML/JSON (flow), así que `yaml.safe_load` lo lee; el cuerpo va tras el cierre."""
	lines = text.split("\n")
	if not lines or lines[0].strip() != "---":
		return {}, text.strip()
	close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
	if close is None:
		return {}, text.strip()
	try:
		fm = yaml.safe_load("\n".join(lines[1:close])) or {}
	except Exception:
		fm = {}
	if not isinstance(fm, dict):
		fm = {}
	return fm, "\n".join(lines[close + 1 :]).strip()


def refine_point_id(session_id: str, source_lines: str) -> str:
	"""Point id determinista (uuid5) → idempotencia por (session_id, source_lines).

	Re-promover el mismo refine reutiliza el id y hace upsert (no duplica)."""
	return str(uuid.uuid5(uuid.NAMESPACE_OID, f"memento:{session_id}:{source_lines}"))


def _relative_refine_ref(root: Path, refine_path: Path) -> str:
	try:
		return str(refine_path.relative_to(root))
	except ValueError:
		return refine_path.name


def ascender(
	root: Path,
	registry: Any,
	refine_path: Path,
	*,
	collection: Optional[str] = None,
	force: bool = False,
	memory_manager: Any = None,
) -> Dict[str, Any]:
	"""Promociona un `refine/*.md` a engrama curado en `work_memories`/`social_memories`.

	- `collection`: destino explícito; si es None, se clasifica el cuerpo con
	`detect_category_heuristics` (misma heurística que el sueño → consistencia).
	- `force`: re-promueve aunque el refine ya esté sellado como ascendido.
	- `memory_manager`: inyectable para tests (default `MemoryManager()`).

	Devuelve un dict con `ascended` (bool), `reason`, `collection`, `point_id`.
	"""
	refine_path = Path(refine_path)
	text = refine_path.read_text(encoding="utf-8")
	fm, body = parse_refine(text)
	if not body:
		return {"ascended": False, "reason": "empty_body"}

	session_id = str(fm.get("session_id") or "")
	source_lines = str(fm.get("source_lines") or "")
	if not session_id or not source_lines:
		return {"ascended": False, "reason": "missing_key"}

	if fm.get("ascended") and not force:
		return {"ascended": False, "reason": "already_ascended", "point_id": fm.get("ascended_point_id")}

	significance = float(fm.get("significance", 0.0) or 0.0)
	emotion = str(fm.get("emotion", "gray"))
	intensity = float(fm.get("intensity", 0.0) or 0.0)
	texture = fm.get("texture") if isinstance(fm.get("texture"), dict) else {}
	theme = str(texture.get("theme", "")) if texture else ""
	relics = list(texture.get("relics", [])) if texture else []
	cross_refs = list(fm.get("cross_refs", []) or [])
	source = str(fm.get("source") or "")

	if collection is None:
		from red_pill.metabolism.categorizer import detect_category_heuristics

		collection = f"{detect_category_heuristics(body)}_memories"

	point_id = refine_point_id(session_id, source_lines)

	if memory_manager is None:
		from red_pill.memory import MemoryManager

		memory_manager = MemoryManager()

	metadata: Dict[str, Any] = {
		"session_id": session_id,
		"source": source,
		"source_lines": source_lines,
		"significance": significance,
		"theme": theme,
		"relics": relics,
		"cross_refs": cross_refs,
		"origin": "memento",
		"refine_ref": _relative_refine_ref(root, refine_path),
	}

	new_id = memory_manager.add_memory(
		collection=collection,
		text=body,
		importance=max(significance, 0.1),
		metadata=metadata,
		point_id=point_id,
		emotion=emotion,
		intensity=intensity,
	)
	if not new_id:
		# El quality gate (`is_garbage`) o un fallo de escritura lo rechazó.
		logger.warning(f"[ASCENSION] refine rechazado por el gate: {refine_path.name} → {collection}")
		return {"ascended": False, "reason": "rejected", "collection": collection}

	# Sello in-place en el frontmatter del refine (no mueve el cuerpo).
	update_frontmatter_fields(
		refine_path,
		{
			"ascended": True,
			"ascended_at": datetime.now(timezone.utc).isoformat(),
			"ascended_to": collection,
			"ascended_point_id": point_id,
		},
	)

	if source:
		registry.upsert(
			source,
			session_id,
			{"ascended": True, "ascended_to": collection, "ascended_point_id": point_id},
		)

	logger.info(f"[ASCENSION] {refine_path.name} → {collection} (point {point_id[:8]}…)")
	return {"ascended": True, "reason": "ok", "collection": collection, "point_id": point_id}
