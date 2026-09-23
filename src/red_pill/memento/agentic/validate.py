"""Fase de validación de contenido (MEM-006): revisa las notas rechazadas por el
filtro de ruido (`is_garbage`) y emite veredicto LLM.

- Selección (`pending_validations`): notas/refines ascend-eligible cuyo veredicto vigente es el del gate (`validator: is_garbage`, `validator_approved: false`).
- Política annotate-first: los `refine/` de sesiones anotadas quedan fuera.
- El veredicto LLM SOBRESCRIBE el del gate en el frontmatter (self-documented): `validator_approved`, `validator` (engine), `validator_prompt_version`, `validator_reason`, `validated_at`.
- Aprobada → el ascenso llamará `add_memory(content_verified=True)` (exención quirúrgica del filtro, NUNCA `immune`). Rechazada → terminal, no se reintenta.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import prompts, runtime

logger = logging.getLogger(__name__)

BATCH = 10

# Pre-check determinista: volcados obvios que no merecen ni llamada al LLM
# (el caso 001-stash-check: meta-comentario en inglés; 019: línea de progreso).
_RAW_DUMP_RE = re.compile(
	r"(^|\n)\s*##\s*\d{4}-\d{2}-\d{2}.*—\s*Tool|(^|\n)\s*\d{1,3}(\.\d+)?\s*%\s*—|passed the \d+\s*%\s*threshold|"
	r"\bthe user asks\b|\blet me (check|push|see|fix)\b|file:/{3}|file:/{2}[^/]",
	re.I,
)


def looks_like_raw_dump(body: str) -> bool:
	"""True para volcados de terminal/meta-comentarios evidentes (sin LLM)."""
	return bool(_RAW_DUMP_RE.search(body))


def _gate(route: str) -> float:
	import red_pill.config as cfg

	if route == "work":
		return float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE_WORK", 0.6))
	return float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE_SOCIAL", 0.5))


def _route_of(fm: Dict[str, Any], kind: str) -> str:
	route = str(fm.get("dual_route") or "").strip().lower()
	if route in ("work", "social"):
		return route
	if kind == "refine":
		try:
			return "work" if float(fm.get("category_score", 0.5) or 0.5) >= 0.5 else "social"
		except (TypeError, ValueError):
			return "social"
	return "none"


def _is_pending(root: Path, path: Path, kind: str, fm: Dict[str, Any], body: str) -> bool:
	if fm.get("ascended"):
		return False
	verdict = str(fm.get("validator_approved") or "").strip().lower()
	validator = str(fm.get("validator") or "").strip()
	if verdict == "true":
		return False
	if validator and validator != "is_garbage":
		return False  # veredicto LLM ya emitido (rechazo terminal)
	if not validator:
		# Sin veredicto previo: solo aplica si el filtro de ruido lo cazaría
		# (así el validador cubre el backlog sin depender de un pase de ascenso).
		from red_pill.utils.telemetry_filter import is_garbage

		if not is_garbage(body):
			return False
	route = _route_of(fm, kind)
	if route not in ("work", "social"):
		return False
	try:
		sig = float(fm.get("significance", 0) or 0)
	except (TypeError, ValueError):
		sig = 0.0
	if sig < _gate(route):
		return False
	if kind == "refine":
		session_dir = path.parent.parent
		annot = session_dir / "annotate"
		if annot.is_dir() and any(annot.glob("*.md")):
			return False  # annotate-first: el refine legacy de sesiones anotadas no aplica
	return True


def pending_validations(root: Path) -> List[Path]:
	"""Notas/refines con veredicto del gate pendiente de revisión LLM."""
	from red_pill.memento.ascension import parse_refine

	out: List[Path] = []
	for kind in ("annotate", "refine"):
		for p in sorted(root.rglob(f"{kind}/*.md")):
			fm, body = parse_refine(p.read_text(encoding="utf-8", errors="replace"))
			if _is_pending(root, p, kind, fm, body):
				out.append(p)
	return out


def _stamp_verdict(path: Path, approved: bool, reason: str, validator: Optional[str] = None) -> None:
	from red_pill.memento.ascension import _stamp_refine

	_stamp_refine(
		path,
		{
			"validator_approved": bool(approved),
			"validator": validator or runtime.engine_id(),
			"validator_prompt_version": runtime.validate_prompt_version(),
			"validator_reason": reason,
			"validated_at": datetime.now(timezone.utc).isoformat(),
		},
	)


def _body(path: Path) -> str:
	from red_pill.memento.ascension import parse_refine

	_fm, body = parse_refine(path.read_text(encoding="utf-8", errors="replace"))
	return body


def validate_notes(transport: runtime.Transport, paths: List[Path], batch: int = BATCH) -> Dict[str, Any]:
	"""Valida en lotes; sella el veredicto. Las no contestadas quedan pendientes.

	Pre-check determinista: los volcados obvios (`looks_like_raw_dump`) se rechazan
	sin llamar al LLM (razón `raw-dump heuristic`).
	"""
	stats: Dict[str, Any] = {"pending": len(paths), "approved": 0, "rejected": 0, "sin_respuesta": 0, "heuristic_rejected": 0}
	pendientes: List[Path] = []
	for p in paths:
		if looks_like_raw_dump(_body(p)):
			_stamp_verdict(p, False, "raw-dump heuristic", validator="raw-dump-heuristic")
			stats["rejected"] += 1
			stats["heuristic_rejected"] += 1
		else:
			pendientes.append(p)
	for start in range(0, len(pendientes), batch):
		chunk = pendientes[start : start + batch]
		listing = "\n\n".join(f"[{i}] {_body(p)[:600]}" for i, p in enumerate(chunk))
		raw = transport(prompts.CONTENT_VALIDATE_SYSTEM, prompts.CONTENT_VALIDATE_USER.format(notes=listing), 2048)
		answered = set()
		for row in runtime._extract_json_array(raw) or []:
			if not isinstance(row, dict):
				continue
			raw_idx = row.get("i")
			if raw_idx is None:
				continue
			try:
				idx = int(raw_idx)
			except (TypeError, ValueError):
				continue
			if not (0 <= idx < len(chunk)):
				continue
			approved = bool(row.get("approved")) if isinstance(row.get("approved"), bool) else str(row.get("approved")).lower() == "true"
			reason = str(row.get("reason") or "").strip()[:120]
			_stamp_verdict(chunk[idx], approved, reason)
			stats["approved" if approved else "rejected"] += 1
			answered.add(idx)
		stats["sin_respuesta"] += len(chunk) - len(answered)
	return stats


def validate_note(transport: runtime.Transport, path: Path) -> Dict[str, Any]:
	"""(Element-job) valida UNA nota."""
	stats = validate_notes(transport, [path], batch=1)
	stats["path"] = str(path)
	return stats
