"""RFC-004 P2 — cliente del sidecar de etiquetado (UDS, fail-visible).

Etiqueta cada turno capturado (emoción/tema) con el sidecar Laya y lo persiste
como metadata aditiva del engrama. Contrato RFC-004:

1. El registro NUNCA espera al tag: `record_interaction_pair` escribe primero y
	el tag se aplica después con un timeout corto; si falla, el engrama queda
	escrito igual.
2. Fallo señalizado, nunca oculto: el engrama lleva `tag_status`
	(`ok|degraded|failed`) + `tag_reason`; el interceptor lo comunica (WEAK).
3. Sin reintentos en caliente y sin garantizar el servicio.

Este módulo NO importa torch ni el daemon: habla el protocolo JSON newline del
sidecar (`scripts/laya_tag_server.py`) por `AF_UNIX`.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path
from typing import Any, Optional, cast

import red_pill.config as cfg
from red_pill.core.paths import _assert_not_production_runtime

logger = logging.getLogger(__name__)

COLLECTION = "interaction_memories"
TAG_ENGINE = "laya-multilingual"

# Campos aditivos que se escriben en el payload del engrama (prefijo `tag_` para
# no colisionar con `metadata` ni otros campos; `set_payload` es shallow).
_TAG_FIELDS = (
	"tag_status",
	"tag_reason",
	"tag_emotion",
	"tag_theme",
	"tag_confidence",
	"tag_engine",
	"tagged_at",
	# Dos moods por turno (2026-11-20): el del Operador sale de SU prompt y el del
	# agente de SU respuesta. `tag_emotion` se mantiene como el del Operador para
	# no romper a los consumidores que ya lo leen.
	"tag_emotion_operator",
	"tag_theme_operator",
	"tag_confidence_operator",
	"tag_emotion_assistant",
	"tag_theme_assistant",
	"tag_confidence_assistant",
)


def default_socket_path() -> str:
	explicit = str(getattr(cfg, "LAYA_TAG_SOCKET", "") or "").strip()
	if explicit:
		return explicit
	base = os.getenv("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
	path = Path(base) / "red-pill" / "laya_tag.sock"
	_assert_not_production_runtime(path, "realtime_tag.default_socket_path()")
	return str(path)


def enabled() -> bool:
	return bool(getattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", False))


def budget_s() -> float:
	"""Presupuesto total de etiquetado por drenaje (acota N×timeout).

	0 es un valor válido (no etiquetar) — no debe caer al default.
	"""
	v = getattr(cfg, "MEMENTO_REALTIME_TAG_BUDGET_S", 20.0)
	if v is None:
		return 20.0
	try:
		return float(v)
	except (TypeError, ValueError):
		return 20.0


def timeout_s() -> float:
	try:
		return float(getattr(cfg, "MEMENTO_REALTIME_TAG_TIMEOUT_S", 3.0) or 3.0)
	except (TypeError, ValueError):
		return 3.0


def max_chars() -> int:
	"""Recorte del texto etiquetado. Medido: la latencia CPU crece ~0,4 ms/char;
	1500 chars ≈ 0,7 s deja el timeout muy por encima de la latencia real."""
	try:
		return int(getattr(cfg, "MEMENTO_REALTIME_TAG_MAX_CHARS", 1500) or 1500)
	except (TypeError, ValueError):
		return 1500


def _clip(text: str, cap: int) -> tuple[str, bool]:
	"""Recorta conservando cabeza Y cola (la señal emocional suele estar al
	final del turno del operador). Devuelve (texto, truncado)."""
	if len(text) <= cap:
		return text, False
	half = max(1, cap // 2)
	return text[:half] + "\n...\n" + text[-half:], True


def _send(payload: dict, sock_path: str, timeout: float) -> dict:
	"""Request/response UDS de una línea. Lanza si no hay respuesta parseable."""
	s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	s.settimeout(timeout)
	try:
		s.connect(sock_path)
		s.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
		buf = b""
		while not buf.endswith(b"\n"):
			chunk = s.recv(65536)
			if not chunk:
				break
			buf += chunk
		if not buf.strip():
			raise RuntimeError("empty-response")
		return cast("dict[Any, Any]", json.loads(buf.decode("utf-8")))
	finally:
		s.close()


def tag_turn(text: str, *, socket_path: Optional[str] = None, timeout: Optional[float] = None) -> dict:
	"""Devuelve SIEMPRE un dict con `tag_status`; nunca lanza.

	- disabled: flag OFF (no se toca el socket).
	- ok: etiqueta fiable.
	- degraded: respondió pero con baja confianza (heurística, no verdad).
	- failed: sin sidecar / timeout / respuesta inválida (con `tag_reason`).
	"""
	if not enabled():
		return {"tag_status": "disabled"}
	body = (text or "").strip()
	if not body:
		return {"tag_status": "failed", "tag_reason": "empty-text"}
	sock_path = socket_path or default_socket_path()
	tmo = timeout if timeout is not None else timeout_s()
	clipped, truncated = _clip(body, max_chars())
	try:
		resp = _send({"id": "drain", "text": clipped}, sock_path, tmo)
	except FileNotFoundError:
		return {"tag_status": "failed", "tag_reason": "sidecar-down"}
	except socket.timeout:
		return {"tag_status": "failed", "tag_reason": "timeout"}
	except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError, OSError):
		return {"tag_status": "failed", "tag_reason": "sidecar-down"}
	except Exception as e:  # json inválido, etc.
		return {"tag_status": "failed", "tag_reason": f"bad-response: {type(e).__name__}"}

	if not resp.get("ok"):
		return {"tag_status": "failed", "tag_reason": str(resp.get("error") or "sidecar-error")[:120]}
	emo = (resp.get("emotion") or {}).get("label", "?")
	thm = (resp.get("theme") or {}).get("label", "?")
	conf = resp.get("confidence")
	if resp.get("low_confidence"):
		return {
			"tag_status": "degraded",
			"tag_reason": "low-confidence",
			"tag_emotion": emo,
			"tag_theme": thm,
			"tag_confidence": conf,
		}
	if truncated:
		# Vimos solo una parte del turno: la etiqueta puede fallar por el recorte
		# (p.ej. emoción al final). Se marca `degraded` en vez de un `ok` falso.
		return {
			"tag_status": "degraded",
			"tag_reason": "truncated",
			"tag_emotion": emo,
			"tag_theme": thm,
			"tag_confidence": conf,
		}
	return {
		"tag_status": "ok",
		"tag_emotion": emo,
		"tag_theme": thm,
		"tag_confidence": conf,
	}


def apply_tag(memory: Any, uid: str, tag: dict, *, collection: str = COLLECTION, now: Optional[float] = None) -> bool:
	"""Escribe los campos `tag_*` en el engrama. Nunca lanza; False si no pudo."""
	payload = {k: v for k, v in tag.items() if k in _TAG_FIELDS}
	payload["tag_engine"] = TAG_ENGINE
	try:
		import time

		payload["tagged_at"] = now if now is not None else time.time()
		memory.client.set_payload(collection_name=collection, payload=payload, points=[uid])
		return True
	except Exception as e:
		logger.warning(f"[realtime_tag] set_payload falló para {uid}: {e}")
		return False


def pair_tag(operator: dict, assistant: dict) -> dict:
	"""Compone los campos de un turno con DOS moods (puro: sin socket).

	- `tag_emotion` = el del Operador (compatibilidad: quien ya leía `tag_emotion`
		sigue leyendo el ánimo de quien escribe, no la mezcla de los dos).	- `tag_emotion_assistant` = el del agente, desde su respuesta.
	- `tag_status` global = el peor de los dos: si un lado falló, se dice.
	"""

	def _st(tag: dict) -> str:
		return str(tag.get("tag_status") or "failed")

	op_ok = _st(operator) in ("ok", "degraded")
	as_ok = _st(assistant) in ("ok", "degraded")
	out: dict = {
		"tag_status": "ok" if (_st(operator) == "ok" and _st(assistant) == "ok") else "degraded",
		"tag_engine": TAG_ENGINE,
		"tag_emotion": operator.get("tag_emotion") or "?",
		"tag_theme": operator.get("tag_theme") or "?",
		"tag_confidence": operator.get("tag_confidence"),
		"tag_emotion_operator": operator.get("tag_emotion") or "?",
		"tag_theme_operator": operator.get("tag_theme") or "?",
		"tag_confidence_operator": operator.get("tag_confidence"),
		"tag_emotion_assistant": assistant.get("tag_emotion") or "?",
		"tag_theme_assistant": assistant.get("tag_theme") or "?",
		"tag_confidence_assistant": assistant.get("tag_confidence"),
	}
	if not op_ok and not as_ok:
		out["tag_status"] = "failed"
		out["tag_reason"] = f"operator:{_st(operator)} assistant:{_st(assistant)}"
	elif not op_ok:
		out["tag_reason"] = "operator-failed"
	elif not as_ok:
		out["tag_reason"] = "assistant-failed"
	return out


# ── Troceado (2026-11-20) ────────────────────────────────────────────────────
# El turno se recortaba a `MAX_CHARS` cogiendo cabeza y cola: con respuestas de
# 2.281 chars de mediana, el medio de lo que dice el agente no se etiquetaba
# nunca y el tag salía `degraded: truncated`. Se trocea en ventanas con solape
# y se agrega por confianza acumulada: el ánimo de un texto largo no es el de su
# primera frase.
CHUNK_OVERLAP = 120


def split_chunks(text: str, cap: int, overlap: int = CHUNK_OVERLAP) -> list[str]:
	"""Parte `text` en trozos de ≤cap chars, cortando por espacio y con solape."""
	body = (text or "").strip()
	if not body:
		return []
	if len(body) <= cap:
		return [body]
	chunks: list[str] = []
	start = 0
	while start < len(body):
		end = min(start + cap, len(body))
		if end < len(body):
			cut = body.rfind(" ", start + cap // 2, end)
			if cut > start:
				end = cut
		chunks.append(body[start:end].strip())
		if end >= len(body):
			break
		start = max(start + 1, end - overlap)
	return [c for c in chunks if c]


def aggregate_tags(tags: list[dict]) -> dict:
	"""Agrega etiquetas de varios trozos: emoción/tema por confianza acumulada."""
	ok = [t for t in tags if str(t.get("tag_status") or "") in ("ok", "degraded") and t.get("tag_emotion")]
	if not ok:
		last = tags[-1] if tags else {}
		return {"tag_status": "failed", "tag_reason": str(last.get("tag_reason") or "no-chunks")}
	emo_w: dict[str, float] = {}
	thm_w: dict[str, float] = {}
	for t in ok:
		try:
			w = float(t.get("tag_confidence")) if t.get("tag_confidence") is not None else 0.5
		except (TypeError, ValueError):
			w = 0.5
		emo = str(t.get("tag_emotion") or "?")
		thm = str(t.get("tag_theme") or "?")
		emo_w[emo] = emo_w.get(emo, 0.0) + w
		thm_w[thm] = thm_w.get(thm, 0.0) + w
	best_emo = max(emo_w.items(), key=lambda kv: kv[1])
	best_thm = max(thm_w.items(), key=lambda kv: kv[1])
	# La confianza del ganador es la mayor evidencia a su favor (no la media con
	# los trozos que votaron otra cosa: eso la hundía artificialmente).
	confs = []
	for t in ok:
		if str(t.get("tag_emotion") or "") != best_emo[0]:
			continue
		try:
			confs.append(float(t.get("tag_confidence")) if t.get("tag_confidence") is not None else 0.5)
		except (TypeError, ValueError):
			confs.append(0.5)
	conf_ganadora = max(confs) if confs else round(best_emo[1] / max(1, len(ok)), 3)
	status = "ok" if all(str(t.get("tag_status")) == "ok" for t in ok) else "degraded"
	return {
		"tag_status": status,
		"tag_emotion": best_emo[0],
		"tag_theme": best_thm[0],
		"tag_confidence": conf_ganadora,
		"tag_chunks": len(ok),
	}


def tag_turn_chunked(text: str, *, socket_path: Optional[str] = None, timeout: Optional[float] = None) -> dict:
	"""Etiqueta un texto largo por trozos y agrega. Nunca lanza."""
	if not enabled():
		return {"tag_status": "disabled"}
	chunks = split_chunks(text, max_chars())
	if not chunks:
		return {"tag_status": "failed", "tag_reason": "empty-text"}
	if len(chunks) == 1:
		return tag_turn(chunks[0], socket_path=socket_path, timeout=timeout)
	return aggregate_tags([tag_turn(c, socket_path=socket_path, timeout=timeout) for c in chunks])


def tag_pair(operator_text: str, assistant_text: str, *, socket_path: Optional[str] = None, timeout: Optional[float] = None) -> dict:
	"""Etiqueta las dos mitades por separado: su ánimo y el del agente."""
	if not enabled():
		return {"tag_status": "disabled"}
	op = tag_turn_chunked(operator_text, socket_path=socket_path, timeout=timeout)
	asst = tag_turn_chunked(assistant_text, socket_path=socket_path, timeout=timeout)
	return pair_tag(op, asst)


def maybe_tag_pair(
	memory: Any, uid: str, operator_text: str, assistant_text: str, *, socket_path: Optional[str] = None, timeout: Optional[float] = None
) -> dict:
	"""Pipeline completo del turno con dos moods. Nunca lanza."""
	tag = tag_pair(operator_text, assistant_text, socket_path=socket_path, timeout=timeout)
	if tag.get("tag_status") == "disabled":
		return tag
	persisted = False
	try:
		persisted = apply_tag(memory, uid, tag)
	except Exception as e:  # noqa: BLE001 — el tag nunca tumba el drenaje
		logger.error(f"[realtime_tag] apply_tag inesperado (par): {e}")
	tag["tag_persisted"] = persisted
	return tag


def maybe_tag(memory: Any, uid: str, text: str, *, socket_path: Optional[str] = None, timeout: Optional[float] = None) -> dict:
	"""Pipeline completo: gate → etiqueta → persiste. Nunca lanza.

	Devuelve el tag más `tag_persisted` (False si el `set_payload` falló): el
	worker lo usa para no dar por escrito algo que no se guardó.
	"""
	tag = tag_turn(text, socket_path=socket_path, timeout=timeout)
	if tag.get("tag_status") == "disabled":
		return tag
	persisted = False
	try:
		persisted = apply_tag(memory, uid, tag)
	except Exception as e:  # cinturón y tirantes: apply_tag ya captura
		logger.error(f"[realtime_tag] apply_tag inesperado: {e}")
	tag["tag_persisted"] = persisted
	return tag
