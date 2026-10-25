"""Compactor de contexto (B-02): dos umbrales, resumen y reset(handoff).

El servicio no borra el espejo: elige un rango de turnos cerrados, pide un
resumen al puerto `Summarizer`, lo apenda como turno `system` y devuelve el
contexto podado (resumen + cola protegida). El histórico completo sigue en
`session_mirror` para auditoría, replay y `compact_parent`.

Esta pieza es síncrona a propósito. El disparo en fondo (Samantha/Job Manager)
es un consumidor suyo: puede llamar a `compact_now` desde su propio worker sin
que el runner dependa de un hilo efímero.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Any, List, Optional

from red_pill.session.mirror import SessionMirror
from red_pill.session.summarizer import ExtractiveSummarizer, Summarizer, build_summarizer

logger = logging.getLogger(__name__)


class CompactionError(RuntimeError):
	"""No se pudo producir un resumen; la compactación queda abortada."""


@dataclass(frozen=True)
class ContextResult:
	turns: List[dict]
	messages: List[dict]
	compacted: bool
	compaction_id: Optional[str]
	tokens_before: int
	tokens_after: int


def estimate_tokens(text: str) -> int:
	"""Estimación conservadora chars/3.2 (B02-TOKENS); no sustituye usage."""
	return max(1, int(len(str(text or "")) / 3.2))


def estimate_messages_tokens(messages: List[dict]) -> int:
	"""Estimación de un prompt OpenAI: contenido + tool_calls serializados."""
	total = 0
	for message in messages or []:
		total += estimate_tokens(str(message.get("content") or ""))
		calls = message.get("tool_calls")
		if calls:
			import json

			total += estimate_tokens(json.dumps(calls, ensure_ascii=False, separators=(",", ":")))
	return total


def _config_int(name: str, default: int) -> int:
	try:
		import red_pill.config as cfg

		return int(getattr(cfg.get_config(), name, default))
	except Exception:
		return default


def _config_str(name: str, default: str) -> str:
	try:
		import red_pill.config as cfg

		return str(getattr(cfg.get_config(), name, default) or default)
	except Exception:
		return default


def _safe_range_end(turns: List[dict], *, start: int, candidate: int) -> int:
	"""Baja el corte hasta no partir una pareja assistant(tool_calls)↔tool."""
	end = int(candidate)
	while end >= start:
		selected = [t for t in turns if start <= int(t.get("seq") or 0) <= end]
		if not selected:
			return end
		last = selected[-1]
		if str(last.get("role") or "") == "tool":
			end -= 1
			continue
		calls = last.get("tool_calls")
		if isinstance(calls, list) and calls:
			ids = {str((c or {}).get("id") or "") for c in calls if isinstance(c, dict)}
			orphan = any(
				str(t.get("role") or "") == "tool"
				and str(t.get("tool_call_id") or "") in ids
				and int(t.get("seq") or 0) > end
				for t in turns
			)
			if orphan:
				end -= 1
				continue
		break
	return end


class Compactor:
	"""Servicio de compactación sobre un `SessionMirror` y un `Summarizer`."""

	def __init__(
		self,
		mirror: SessionMirror,
		*,
		summarizer: Optional[Summarizer] = None,
		engine: Optional[str] = None,
		protect_last_n: Optional[int] = None,
		background_tokens: Optional[int] = None,
		reserve_tokens: Optional[int] = None,
		max_input_chars: Optional[int] = None,
		queue_manager: Optional[Any] = None,
	):
		self.mirror = mirror
		self.queue_manager = queue_manager
		self.engine = (engine or _config_str("SESSION_COMPACTOR_ENGINE", "samantha")).strip().lower()
		self.protect_last_n = max(
			0,
			int(protect_last_n if protect_last_n is not None else _config_int("SESSION_COMPACTOR_PROTECT_LAST_N", 4)),
		)
		self.background_tokens = max(
			1,
			int(background_tokens if background_tokens is not None else _config_int("SESSION_COMPACTOR_BACKGROUND_TOKENS", 8000)),
		)
		self.reserve_tokens = max(
			128,
			int(reserve_tokens if reserve_tokens is not None else _config_int("SESSION_COMPACTOR_RESERVE_TOKENS", 2000)),
		)
		self.max_input_chars = max(
			4000,
			int(max_input_chars if max_input_chars is not None else _config_int("SESSION_COMPACTOR_MAX_INPUT_CHARS", 120000)),
		)
		if summarizer is not None:
			self.summarizer = summarizer
		else:
			try:
				self.summarizer = build_summarizer(self.engine)
			except ValueError:
				logger.warning("[compactor] motor desconocido %r; usando extractivo", self.engine)
				self.summarizer = ExtractiveSummarizer()

	def should_compact(self, messages: List[dict], *, budget_tokens: int, reserve_tokens: Optional[int] = None) -> bool:
		reserve = self.reserve_tokens if reserve_tokens is None else max(0, int(reserve_tokens))
		return estimate_messages_tokens(messages) > max(1, int(budget_tokens) - reserve)

	def context(self, continuity_id: str) -> ContextResult:
		turns = self.mirror.context_turns(continuity_id)
		from red_pill.session.switch import replay_messages

		messages = replay_messages(turns)
		return ContextResult(
			turns=turns,
			messages=messages,
			compacted=False,
			compaction_id=None,
			tokens_before=estimate_messages_tokens(messages),
			tokens_after=estimate_messages_tokens(messages),
		)

	def compact_now(
		self,
		continuity_id: str,
		*,
		mission_id: Optional[str] = None,
		protect_last_n: Optional[int] = None,
		reason: str = "manual",
	) -> Optional[dict]:
		"""Compacta una vez el rango cerrado disponible; None si no hay rango."""
		continuity = str(continuity_id or "").strip()
		if not continuity:
			raise ValueError("continuity_id requerido")
		protect = self.protect_last_n if protect_last_n is None else max(0, int(protect_last_n))
		latest = self.mirror.latest_compaction(continuity)
		start = int(latest["range_end_seq"]) + 1 if latest else 1
		turns = self.mirror.read_turns(continuity)
		if not turns:
			return None
		# `last_seq`/los turnos incluyen el resumen anterior; la cola protegida
		# se cuenta sobre turnos normales, no sobre resúmenes del compactor.
		regular = [
			t
			for t in turns
			if not (str(t.get("source") or "") == "compactor" and latest and str(t.get("source_ref") or "") == f"compact:{latest['compaction_id']}")
		]
		if not regular:
			return None
		last = max(int(t.get("seq") or 0) for t in regular)
		candidate = last - protect
		if candidate < start:
			return None
		all_turns = self.mirror.read_turns(continuity, statuses=["completed", "pending", "aborted"])
		end = _safe_range_end(all_turns, start=start, candidate=candidate)
		if end < start:
			return None
		selected = [t for t in turns if start <= int(t.get("seq") or 0) <= end]
		if not selected:
			return None
		if latest:
			mission = str(mission_id or latest.get("mission_id") or "")
		else:
			mission = str(mission_id or "")
		mission = mission.strip()
		if not mission:
			first = selected[0]
			mission = str(first.get("mission_id") or "").strip()
		if not mission:
			raise ValueError("mission_id requerido para compactar")
		from red_pill.session.switch import render_history

		history = render_history(continuity, selected, max_chars=self.max_input_chars)
		tokens_before = estimate_tokens(history)
		pending = self.mirror.start_compaction(
			continuity_id=continuity,
			mission_id=mission,
			range_start_seq=start,
			range_end_seq=end,
			parent_compaction_id=str(latest["compaction_id"]) if latest else None,
			model=getattr(self.summarizer, "name", self.engine),
			tokens_before=tokens_before,
		)
		compaction_id = str(pending["compaction_id"])
		if str(pending.get("status") or "") == "completed":
			return pending
		if str(pending.get("status") or "") == "aborted":
			return None
		# Otra instancia pudo ganar el rango: se resume EL RANGO RECLAMADO, no el
		# que habíamos calculado antes de entrar en la transacción. Se releen los
		# turnos para no resumir un snapshot viejo.
		start = int(pending["range_start_seq"])
		end = int(pending["range_end_seq"])
		mission = str(pending["mission_id"])
		turns = self.mirror.read_turns(continuity)
		selected = [t for t in turns if start <= int(t.get("seq") or 0) <= end]
		if not selected:
			self.mirror.abort_compaction(compaction_id, reason="empty_range")
			return None
		from red_pill.session.switch import render_history

		history = render_history(continuity, selected, max_chars=self.max_input_chars)
		tokens_before = estimate_tokens(history)
		try:
			summary = self.summarizer.summarize(
				text=history,
				instructions=f"Compactación {reason} del alma {continuity}. Rango {start}-{end}.",
				max_tokens=700,
			)
		except Exception as exc:  # noqa: BLE001
			self.mirror.abort_compaction(compaction_id, reason=f"summary_error: {exc}")
			raise CompactionError(f"resumen falló: {exc}") from exc
		tokens_after = estimate_tokens(summary)
		# En contextos reales, un "resumen" que no reduce no debe completarse.
		# En tramos minúsculos el overhead del prompt puede dar un falso positivo;
		# ahí no hay nada que ganar, pero tampoco se bloquea el turno.
		if tokens_before >= 512 and tokens_after >= tokens_before:
			self.mirror.abort_compaction(compaction_id, reason="summary_not_smaller")
			raise CompactionError(
				f"el resumen no reduce el contexto ({tokens_before}→{tokens_after} tokens)"
			)
		try:
			done = self.mirror.complete_compaction(
				compaction_id,
				summary=summary,
				model=getattr(self.summarizer, "last_engine", getattr(self.summarizer, "name", self.engine)),
				tokens_after=tokens_after,
			)
		except ValueError as exc:
			# Otra instancia abortó la fila compartida; no tumbar el turno.
			logger.warning("[compactor] no se pudo cerrar %s: %s", compaction_id, exc)
			return None
		logger.info(
			"[compactor] %s compactó %s-%s (%s→%s tokens)",
			continuity,
			start,
			end,
			tokens_before,
			tokens_after,
		)
		return done

	def ensure_context(
		self,
		continuity_id: str,
		*,
		budget_tokens: int,
		reserve_tokens: Optional[int] = None,
		protect_last_n: Optional[int] = None,
		extra_tokens: int = 0,
		mission_id: Optional[str] = None,
	) -> ContextResult:
		"""Devuelve contexto que cabe; compacta una vez si hace falta."""
		ctx = self.context(continuity_id)
		before = ctx.tokens_before + max(0, int(extra_tokens))
		if before <= max(1, int(budget_tokens) - (self.reserve_tokens if reserve_tokens is None else int(reserve_tokens))):
			return ctx
		try:
			done = self.compact_now(
				continuity_id,
				mission_id=mission_id,
				protect_last_n=protect_last_n,
				reason="threshold",
			)
		except CompactionError as exc:
			logger.warning("[compactor] compactación fallida, se conserva el contexto: %s", exc)
			return ctx
		if done is None:
			return ctx
		after = self.context(continuity_id)
		latest = self.mirror.latest_compaction(continuity_id)
		return ContextResult(
			turns=after.turns,
			messages=after.messages,
			compacted=True,
			compaction_id=str(latest["compaction_id"]) if latest else None,
			tokens_before=before,
			tokens_after=after.tokens_after,
		)

	def should_start_background(
		self,
		messages: List[dict],
		*,
		extra_tokens: int = 0,
		budget_tokens: Optional[int] = None,
		reserve_tokens: Optional[int] = None,
	) -> bool:
		"""True si el contexto supera el umbral de compactación en fondo.

		El umbral se recorta al hueco real (`budget - reserve`) para que el
		background pueda dispararse antes de que `ensure_context` compacte inline.
		Sin presupuesto explícito manda `background_tokens`.
		"""
		threshold = self.background_tokens
		if budget_tokens is not None:
			reserve = self.reserve_tokens if reserve_tokens is None else max(0, int(reserve_tokens))
			threshold = min(threshold, max(1, int(budget_tokens) - reserve - 1))
		return estimate_messages_tokens(messages) + max(0, int(extra_tokens)) >= threshold

	def maybe_start(
		self,
		continuity_id: str,
		*,
		mission_id: Optional[str] = None,
		protect_last_n: Optional[int] = None,
		extra_tokens: int = 0,
		budget_tokens: Optional[int] = None,
		reserve_tokens: Optional[int] = None,
	) -> Optional[str]:
		"""Encola un `script_job` durable que ejecuta `session compact`.

		No compacta en el proceso actual: el Job Manager lo recoge con su OOM
		shield y el CLI usa este mismo `Compactor`. Dedupe por continuity: si ya
		hay un job PENDING/PROCESSING, devuelve su id.
		"""
		continuity = str(continuity_id or "").strip()
		if not continuity:
			raise ValueError("continuity_id requerido")
		messages = self.mirror.context_messages(continuity)
		if not self.should_start_background(
			messages,
			extra_tokens=extra_tokens,
			budget_tokens=budget_tokens,
			reserve_tokens=reserve_tokens,
		):
			return None
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		qm = self.queue_manager or CognitiveQueueManager()
		try:
			existing = qm.find_task_by_payload_key(
				source="script_job", key="continuity_id", value=continuity, limit=None
			)
		except Exception:
			existing = None
		if existing:
			return str(existing["id"])
		mission = str(mission_id or "").strip()
		if not mission:
			turns = self.mirror.read_turns(continuity)
			mission = str((turns[-1].get("mission_id") if turns else "") or "").strip()
		if not mission:
			raise ValueError("mission_id requerido para compactar en fondo")
		protect = self.protect_last_n if protect_last_n is None else max(0, int(protect_last_n))
		command = [
			sys.executable,
			"-m",
			"red_pill.cli",
			"session",
			"compact",
			"--continuity",
			continuity,
			"--mission",
			mission,
			"--protect-last-n",
			str(protect),
			"--db-path",
			self.mirror.db_path,
		]
		payload = {
			"continuity_id": continuity,
			"mission_id": mission,
			"title": f"compact:{continuity[:8]}",
			"step_command": command,
			"progress": {"mode": "single"},
			"control": {"max_step_minutes": 15},
		}
		priority = _config_int("SESSION_COMPACTOR_JOB_PRIORITY", 4)
		return str(qm.enqueue_task(source="script_job", payload=payload, priority=priority, mission_id=mission))

	def maybe_compact(self, continuity_id: str, messages: List[dict], *, threshold: int) -> List[dict]:
		"""Contrato `Compactor`: compacta si el prompt supera `threshold`."""
		if estimate_messages_tokens(messages) < max(1, int(threshold)):
			return messages
		self.compact_now(continuity_id, reason="threshold")
		return self.mirror.context_messages(continuity_id)

	def reset(
		self,
		continuity_id: str,
		*,
		summary: str,
		mission_id: str,
	) -> dict:
		"""Crea un handoff total: el contexto nuevo empieza por `summary`."""
		continuity = str(continuity_id or "").strip()
		text = str(summary or "").strip()
		if not continuity or not text:
			raise ValueError("continuity_id y summary requeridos")
		last = self.mirror.last_seq(continuity)
		# Un reset/handoff manda sobre las compactaciones vigentes: se retiran
		# (abortadas, no borradas) para que el rango 0..last pueda nacer y el
		# resumen nuevo sea el único contexto.
		self.mirror.supersede_compactions(continuity, reason="reset_handoff")
		pending = self.mirror.start_compaction(
			continuity_id=continuity,
			mission_id=mission_id,
			range_start_seq=0,
			range_end_seq=last,
			model=getattr(self.summarizer, "name", self.engine),
		)
		return self.mirror.complete_compaction(
			str(pending["compaction_id"]),
			summary=text,
			model=getattr(self.summarizer, "name", self.engine),
			tokens_after=estimate_tokens(text),
		)


def build_compactor(mirror: Optional[SessionMirror] = None, **kwargs: Any) -> Compactor:
	"""Fábrica para consumidores (MiniSession, local-minion, CLI)."""
	return Compactor(mirror or SessionMirror(), **kwargs)
