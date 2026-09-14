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
