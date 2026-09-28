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
from typing import Any, Optional

import red_pill.config as cfg

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
)


def default_socket_path() -> str:
	explicit = str(getattr(cfg, "LAYA_TAG_SOCKET", "") or "").strip()
	if explicit:
		return explicit
	base = os.getenv("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
	return str(Path(base) / "red-pill" / "laya_tag.sock")


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
		return json.loads(buf.decode("utf-8"))
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
