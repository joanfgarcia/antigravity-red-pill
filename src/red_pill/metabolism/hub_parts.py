"""Planes de partes por polaroid (MEM-011 · F1).

Un **plan** dice, para una sesión, en cuántas partes se divide y qué hojas van en
cada una. Es puro: no escribe nada. La escritura (upsert de la parte y marcado de
sus hojas) es F2 y solo ocurre después de que la parte exista, para no dejar hojas
apuntando a un padre inexistente (invariante I-01).

Regla (contrato MEM-011):
- La unidad es la **polaroid** (unidad renderizada de Memento; la sesión entera si
  no se partió).
- Se fusionan polaroids adyacentes hasta el presupuesto; ninguna se reparte.
- `partes = 1` ⇒ no hay partes: la raíz es el único nodo.
- `engrama → polaroid` por el rango de líneas de `source_lines`; `→ parte` por el
  plan. Sin LLM y sin heurística.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from red_pill.memento.agentic.fragments import work_units
from red_pill.memento.polaroid_pack import (
	oversized_polaroids,
	pack_polaroids,
)

_REF_RE = re.compile(r"#l(\d+)-(\d+)")


@dataclass(frozen=True)
class PolaroidRange:
	"""Una polaroid: clave estable (rango de mensajes) y rango de líneas."""

	key: str
	lo: Optional[int]
	hi: Optional[int]


@dataclass
class PartPlan:
	"""Una parte planificada: qué polaroids agrupa y qué hojas lleva."""

	index: int
	polaroid_keys: List[str]
	members: List[Tuple[Any, Dict[str, Any]]] = field(default_factory=list)
	chars: int = 0

	@property
	def part_key(self) -> str:
		"""Identidad estable de la parte: primera polaroid que contiene.

		Estable cuando la sesión crece: una polaroid nueva se añade al final, así
		que las partes anteriores conservan su clave (y su id).
		"""
		return self.polaroid_keys[0] if self.polaroid_keys else "index"


def part_point_id(collection: str, session_id: str, part_key: str) -> str:
	"""Id determinista de la parte (uuid5). Cambia con `part_key`, no con el cuerpo."""
	return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hub-part:{collection}:{session_id}:{part_key}"))


def polaroids_for_session(session_id: str, root: Optional[Path] = None) -> List[PolaroidRange]:
	"""Polaroids de la sesión según Memento; lista vacía si no se puede resolver.

	La sesión sin split devuelve **una** polaroid implícita (la sesión entera).
	"""
	session_dir = _session_dir(session_id, root)
	if session_dir is None:
		return []
	units = work_units(session_dir)
	if not units:
		return [PolaroidRange(key="index", lo=None, hi=None)]
	out: List[PolaroidRange] = []
	for unit in units:
		m = _REF_RE.search(unit.ref or "")
		out.append(
			PolaroidRange(
				key=unit.key,
				lo=int(m.group(1)) if m else None,
				hi=int(m.group(2)) if m else None,
			)
		)
	return out


def _session_dir(session_id: str, root: Optional[Path] = None) -> Optional[Path]:
	"""Resuelve el directorio de la sesión vía registry (`entry["dir"]`)."""
	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry

	base = Path(root) if root is not None else get_memento_root()
	source, _, raw = str(session_id).partition(":")
	if not raw:
		source, raw = "", str(session_id)
	registry = MementoRegistry()
	for candidate_source in ([source] if source else []) + list((registry.state.get("registry") or {}).keys()):
		for key in (raw, f"{candidate_source}:{raw}"):
			entry = registry.sessions_of(candidate_source).get(key)
			if entry and entry.get("dir"):
				path = base / str(entry["dir"])
				if (path / "memento").is_dir():
					return path
	return None


def polaroid_index_of(source_lines: str, polaroids: Sequence[PolaroidRange]) -> Optional[int]:
	"""Índice de la polaroid que contiene un rango de `source_lines`."""
	m = _REF_RE.search(str(source_lines or ""))
	if not m:
		return 0 if len(polaroids) == 1 else None
	lo, hi = int(m.group(1)), int(m.group(2))
	for idx, pol in enumerate(polaroids):
		if pol.lo is None or pol.hi is None:
			continue
		if not (hi < pol.lo or lo > pol.hi):
			return idx
	# Una sola polaroid (la sesión sin split) contiene cualquier rango por definición.
	return 0 if len(polaroids) == 1 else None


def plan_session_parts(
	session_id: str,
	members: Sequence[Tuple[Any, Dict[str, Any]]],
	budget: int,
	root: Optional[Path] = None,
) -> Dict[str, Any]:
	"""Plan de partes de una sesión (puro, sin escrituras).

	Devuelve `{"polaroids": n, "parts": [...], "unmapped": k, "oversized": [...],
	"needs_parts": bool}`. Con `needs_parts=False` la raíz es el único nodo y no
	hay que escribir ninguna parte (caso mayoritario).
	"""
	polaroids = polaroids_for_session(session_id, root)
	if not polaroids:
		return {
			"polaroids": 0,
			"parts": [],
			"unmapped": len(members),
			"oversized": [],
			"needs_parts": False,
		}
	chars: List[int] = [0] * len(polaroids)
	buckets: List[List[Tuple[Any, Dict[str, Any]]]] = [[] for _ in polaroids]
	unmapped = 0
	for point_id, payload in members:
		idx = polaroid_index_of(str((payload or {}).get("source_lines") or ""), polaroids)
		if idx is None:
			unmapped += 1
			continue
		buckets[idx].append((point_id, payload))
		chars[idx] += len(str((payload or {}).get("content") or ""))

	packed = pack_polaroids(chars, budget)
	plans: List[PartPlan] = []
	for index, part in enumerate(packed):
		plan = PartPlan(
			index=index,
			polaroid_keys=[polaroids[i].key for i in range(part.start, part.end + 1)],
			chars=sum(chars[part.start : part.end + 1]),
		)
		for i in range(part.start, part.end + 1):
			plan.members.extend(buckets[i])
		plans.append(plan)
	return {
		"polaroids": len(polaroids),
		"parts": plans,
		"unmapped": unmapped,
		"oversized": oversized_polaroids(chars, budget),
		"needs_parts": len(plans) > 1,
	}


def synthesize_parts(
	memory_manager: Any,
	collection: str,
	session_id: str,
	members: Sequence[Tuple[Any, Dict[str, Any]]],
	synthesizer: Any,
	affect_fn: Any,
	budget: int,
	force: bool = False,
	failure_reasons: Optional[List[Tuple[str, str]]] = None,
) -> str:
	"""Escribe las partes y luego la raíz (MEM-011 F2). Devuelve el veredicto.

	- `no_parts`: la sesión cabe en una sola parte; el llamante sigue su camino
		normal (comportamiento de hoy).
	- `written` / `skipped` / `failed`: veredicto de la raíz.

	Fail-soft (IC): si una parte no se escribe, **no se escribe la raíz** y las
	partes ya escritas se quedan; la sesión se reintenta el ciclo siguiente. Nunca
	se marca una hoja con un padre que no existe.
	"""
	from red_pill.metabolism.hub_synthesis import _synthesize_one

	plan = plan_session_parts(session_id, members, budget)
	if not plan["needs_parts"]:
		return "no_parts"

	root_members: List[Tuple[Any, Dict[str, Any]]] = []
	for part in plan["parts"]:
		if not part.members:
			continue
		pid = part_point_id(collection, session_id, part.part_key)
		result = _synthesize_one(
			memory_manager,
			collection,
			session_id,
			part.members,
			synthesizer,
			affect_fn,
			force=force,
			failure_reasons=failure_reasons,
			point_id=pid,
			hub_role="part",
			part_key=part.part_key,
		)
		if result == "failed":
			return "failed"
		created = min(
			(float((payload or {}).get("created_at") or 0.0) for _, payload in part.members),
			default=0.0,
		)
		root_members.append(
			(
				pid,
				{
					"content": f"Parte {part.part_key}",
					"session_id": session_id,
					"created_at": created,
					"hub_role": "part",
					"part_key": part.part_key,
				},
			)
		)
	if len(root_members) < 2:
		return "no_parts"
	return _synthesize_one(
		memory_manager,
		collection,
		session_id,
		root_members,
		synthesizer,
		affect_fn,
		force=force,
		failure_reasons=failure_reasons,
		hub_role="root",
	)
