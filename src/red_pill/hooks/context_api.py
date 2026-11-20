"""Núcleo puro del contrato del hook (RFC-HARNESS-001 · P1).

Aquí vive lo que **no** toca base de datos ni arranca procesos: el mapa de
cuerpos, la composición del `originator`, la validación del payload, la línea de
telemetría y el libro de acks. Los efectos (upsert del leg, cursor del coro,
sellado del turno) viven en `mcp_server.hook_*`, que reutiliza el resolutor de
identidad existente.

El motivo de separarlo: `AUDIT_R1` S12 — el constructor de payload anterior
memoizaba en un global de módulo y dos sesiones se contaminaban. Una función pura
no puede contaminar a nadie.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Nombres de arnés canónicos. El kernel hablaba de `claude_code` y el RFC de
# `claude-code`; sin un mapa único, la mitad de los arneses no resolvía cuerpo.
HARNESS_ID: Dict[str, str] = {
	"opencode": "opencode",
	"claude-code": "claude_code",
	"claude-code-project": "claude_code",
	"claude-desktop": "claude_code",
	"pi": "pi",
	"antigravity": "antigravity",
}

NEEDS = ("full", "light", "poll")
REASONS = ("session_start", "model_change", "compaction", "kernel_trigger", "manual")
MAX_SESSION_ID = 200


class HookPayloadError(ValueError):
	"""Payload inválido (4xx: es un bug del cliente, no una caída del kernel)."""


def canon_harness(raw: Optional[str]) -> str:
	"""Normaliza el nombre del arnés. Desconocido → se conserva en minúsculas."""
	name = (raw or "").strip().lower()
	if not name:
		raise HookPayloadError("harness vacío")
	return HARNESS_ID.get(name, name.replace("-", "_"))


def originator_for(harness: str, session_id: str) -> str:
	"""`originator` = `proveedor:id-nativo`. Es el cuerpo: la señal más fuerte.

	La pone el **arnés**, nunca el modelo: `session_id` viaja en el payload del
	hook, y el modelo no tiene forma de escribirlo (no es una tool).
	"""
	sid = (session_id or "").strip()
	if not sid:
		raise HookPayloadError("session_id vacío")
	if len(sid) > MAX_SESSION_ID:
		raise HookPayloadError(f"session_id demasiado largo ({len(sid)} > {MAX_SESSION_ID})")
	return f"{canon_harness(harness)}:{sid}"


def delivery_id(originator: str, turn: int, need: str) -> str:
	"""Identificador estable y determinista del reparto.

	Determinista a propósito: si el arnés repite la petición (reintento por
	timeout), el mismo `delivery_id` permite que el ack sea idempotente en vez de
	sellar dos veces.
	"""
	seed = f"{originator}|{int(turn)}|{need}"
	return hashlib.sha256(seed.encode()).hexdigest()[:26]


@dataclass
class HookRequest:
	session_id: str
	harness: str
	model: str = ""
	turn: int = 0
	prompt: str = ""
	need: str = "light"
	reason: str = "manual"

	@property
	def originator(self) -> str:
		return originator_for(self.harness, self.session_id)

	@property
	def delivery(self) -> str:
		return delivery_id(self.originator, self.turn, self.need)

	@classmethod
	def from_payload(cls, payload: Optional[Dict[str, Any]]) -> "HookRequest":
		if not isinstance(payload, dict):
			raise HookPayloadError("el payload no es un objeto")
		need = str(payload.get("need") or "light").strip().lower()
		if need not in NEEDS:
			raise HookPayloadError(f"need inválido: {need!r} (usa {', '.join(NEEDS)})")
		reason = str(payload.get("reason") or "manual").strip().lower()
		if reason not in REASONS:
			raise HookPayloadError(f"reason inválido: {reason!r} (usa {', '.join(REASONS)})")
		try:
			turn = int(payload.get("turn") or 0)
		except (TypeError, ValueError) as exc:
			raise HookPayloadError("turn no es un entero") from exc
		req = cls(
			session_id=str(payload.get("session_id") or ""),
			harness=str(payload.get("harness") or ""),
			model=str(payload.get("model") or ""),
			turn=max(0, turn),
			prompt=str(payload.get("prompt") or "")[:8000],
			need=need,
			reason=reason,
		)
		_ = req.originator  # valida session_id/harness aquí, no tres capas más abajo
		return req


def block(kind: str, text: str, *, origin: str = "kernel", trusted: bool) -> Dict[str, Any]:
	"""Bloque de contexto con procedencia explícita (seguridad F8).

	`trusted` es obligatorio y **sin default**: un `kind` nuevo debe declarar si lo
	redacta el kernel (`identity`, `telemetry`) o es de terceros (`coro`, `notice`)
	y va envuelto como **datos**, nunca como instrucción de sistema. Sin default,
	un kind que olvide el flag falla en el call-site, no entra confiable por error.
	"""
	return {"kind": kind, "origin": origin, "trusted": bool(trusted), "text": text}


def telemetry_text(stats: Optional[Dict[str, Any]]) -> Optional[str]:
	"""Una línea con el estado del mundo. `None` = SILENT (no hay nada que decir).

	Deliberadamente corta: en `local-9b` son ~40 tokens de 16.384, y el detalle
	vive detrás de la puerta única.
	"""
	if not stats:
		return None
	parts: List[str] = []
	loops = int(stats.get("open_loops") or 0)
	if loops:
		parts.append(f"OPEN LOOPS {loops}")
	pain = int(stats.get("pain") or 0)
	if pain:
		parts.append(f"dolor {pain}")
	coro = int(stats.get("coro") or 0)
	if coro:
		parts.append(f"coro {coro} nov." if coro != 1 else "coro 1 novedad")
	jobs = int(stats.get("jobs") or 0)
	if jobs:
		parts.append(f"jobs {jobs}")
	mood = stats.get("mood")
	if isinstance(mood, dict) and mood.get("emotion"):
		age = mood.get("lag_s")
		stale = bool(mood.get("stale"))
		tag = "mood" if not stale else "mood histórica"
		parts.append(f"{tag} {mood['emotion']}" + (f" {int(age) // 60}m" if isinstance(age, int) and age >= 60 else ""))
	return " · ".join(parts) if parts else None


@dataclass
class AckLedger:
	"""Libro de acks vistos, para que reintentar no selle dos veces.

	Se guarda en el estado del kernel (no en el arnés: el plugin se recarga en
	desarrollo y perdería la memoria). Bounded: sólo los últimos `limit` ids.
	"""

	path: Path
	limit: int = 512
	_ids: List[str] = field(default_factory=list)

	def _load(self) -> None:
		try:
			data = json.loads(self.path.read_text(encoding="utf-8"))
			if isinstance(data, list):
				self._ids = [str(x) for x in data][-self.limit :]
		except (OSError, ValueError):
			self._ids = []

	def seen(self, delivery: str) -> bool:
		self._load()
		return delivery in self._ids

	def mark(self, delivery: str) -> None:
		self._load()
		if delivery in self._ids:
			return
		self._ids.append(delivery)
		self._ids = self._ids[-self.limit :]
		try:
			self.path.parent.mkdir(parents=True, exist_ok=True)
			tmp = self.path.with_suffix(".tmp")
			tmp.write_text(json.dumps(self._ids), encoding="utf-8")
			os.replace(tmp, self.path)
		except OSError:
			pass
