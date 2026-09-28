#!/usr/bin/env python3
"""RFC-004 P1 — sidecar UDS de etiquetado emocional/temático (Laya, CPU).

Servidor asyncio crudo sobre AF_UNIX; carga Laya una vez y responde JSON
newline-delimited. Sin fastapi/uvicorn (el venv no los trae) y sin puerto TCP.

Protocolo (una línea JSON por request, la conexión admite varias):
	→ {"id": "<str>", "text": "<turno>"}
	← {"id": "<str>", "ok": true, "emotion": {...}, "theme": {...}, "lat_s": 0.2}
	← {"id": "<str>", "ok": false, "error": "<motivo>"}
	→ {"id": "<str>", "ping": true}
	← {"id": "<str>", "ok": true, "pong": true, "model_loaded": true|false}

Contrato RFC-004: el servidor NUNCA bloquea al cliente de forma silenciosa; si
no puede responder devuelve ok=false con motivo. El cliente (queue_worker, P2)
decide `tag_status: ok|degraded|failed` y jamás espera más de su timeout.
Caveat de arranque en frío: mientras torch se importa el event loop puede
quedarse "sordo" unos segundos (GIL); por eso `--check` usa timeout amplio y el
primer turno tras un reinicio puede quedar sin tag (señalizado, no oculto).

Arranque: `redpill-laya-tag.service` (Restart=always), intérprete del venv
`~/.local/share/red-pill/laya-venv`. El gate de USO es del cliente
(`MEMENTO_REALTIME_TAG_ENABLED`); el server corre si la unit está activa.

IMPORTANTE: la unit NO debe declarar `RuntimeDirectory=red-pill` — systemd la
borra al parar y se llevaría el socket del daemon (`red_pill.sock`). El server
crea el directorio si falta y no lo borra al salir.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path

logger = logging.getLogger("redpill.laya_tag")

# Por debajo de esto el tag se marca low_confidence (el cliente lo vuelve
# `degraded`, nunca fallo duro: es heurística, no verdad).
TAG_LOW_CONFIDENCE = 0.5

# Límite de línea del protocolo. asyncio usa 64 KiB por defecto y una línea
# mayor cierra la conexión en silencio; aquí se sube y, si se excede, se
# responde ok=false antes de cerrar (panel P1: "nunca bloquea en silencio").
READ_LIMIT = 1_048_576

MODEL_ID = "convaiinnovations/laya"
MODEL_SUBFOLDER = "multilingual"

EMOTIONS = ("calm", "neutral", "positive", "tense", "frustrated", "sad", "focused")
THEMES = ("work", "personal", "meta", "other")


def default_socket_path() -> str:
	"""`$LAYA_TAG_SOCK` > `$XDG_RUNTIME_DIR/red-pill/laya_tag.sock` > /run/user/<uid>.

	Mismo directorio de runtime que el daemon (paths.get_daemon_dir) para no
	introducir otra ruta gestionada; `LAYA_TAG_SOCK` permite tests con tmp.
	"""
	env = os.getenv("LAYA_TAG_SOCK")
	if env:
		return env
	base = os.getenv("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
	return str(Path(base) / "red-pill" / "laya_tag.sock")


def build_questions() -> dict:
	"""Preguntas tipadas para Laya (choice cerrado → sin parseo, sin alucinación).

	Mantener pocas opciones y estables: la doc de Laya avisa que el ORDEN puede
	mover la respuesta y que las etiquetas booleanas fallan; aquí son labels
	descriptivos y un catálogo corto.
	"""
	return {
		"emotion": {
			"type": "choice",
			"instructions": "¿Qué tono emocional transmite este turno de la conversación?",
			"criteria": {
				"calm": "tranquilo, sereno",
				"neutral": "neutro, sin carga emocional",
				"positive": "positivo, satisfecho, contento",
				"tense": "tenso, con prisa o presión",
				"frustrated": "frustrado, molesto, con un problema",
				"sad": "triste, preocupado",
				"focused": "concentrado, inmerso en el trabajo",
			},
		},
		"theme": {
			"type": "choice",
			"instructions": "¿De qué trata principalmente este turno?",
			"criteria": {
				"work": "trabajo técnico o profesional",
				"personal": "vida personal, relaciones, familia, salud",
				"meta": "el propio sistema, los agentes o la memoria",
				"other": "ninguno de los anteriores",
			},
		},
	}


def _choice(answer: dict, allowed: tuple[str, ...]) -> tuple[str, float]:
	"""Normaliza una respuesta choice de Laya → (label, confidence)."""
	if not isinstance(answer, dict):
		return ("?", 0.0)
	label = str(answer.get("choice", "?"))
	conf = answer.get("answer_confidence", answer.get("confidence", 0.0))
	try:
		conf = float(conf)
	except (TypeError, ValueError):
		conf = 0.0
	if label not in allowed:
		return ("?", conf)
	return (label, conf)


def normalize(result: dict) -> dict:
	"""Respuesta cruda de Laya → tag estable (etiquetas cerradas + confianzas)."""
	answers = result.get("answers", {}) if isinstance(result, dict) else {}
	emo, emo_c = _choice(answers.get("emotion", {}), EMOTIONS)
	thm, thm_c = _choice(answers.get("theme", {}), THEMES)
	overall = min(emo_c, thm_c)
	return {
		"emotion": {"label": emo, "confidence": round(emo_c, 3)},
		"theme": {"label": thm, "confidence": round(thm_c, 3)},
		"confidence": round(overall, 3),
		"low_confidence": overall < TAG_LOW_CONFIDENCE,
	}


def handle(agent: object, req: dict) -> dict:
	"""Procesa una request ya decodificada. Nunca lanza: el error va en la respuesta."""
	rid = req.get("id")
	if req.get("ping"):
		return {"id": rid, "ok": True, "pong": True, "model_loaded": agent is not None}
	text = str(req.get("text") or "").strip()
	if not text:
		return {"id": rid, "ok": False, "error": "empty-text"}
	if agent is None:
		return {"id": rid, "ok": False, "error": "model-not-loaded"}
	t0 = time.time()
	try:
		raw = agent.predict(text, build_questions())  # type: ignore[attr-defined]
		tag = normalize(raw)
		return {
			"id": rid,
			"ok": True,
			"emotion": tag["emotion"],
			"theme": tag["theme"],
			"confidence": tag["confidence"],
			"low_confidence": tag["low_confidence"],
			"lat_s": round(time.time() - t0, 3),
		}
	except Exception as e:  # modelo caído / input inválido → señal, no excepción
		return {"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


class TagServer:
	"""Servidor UDS de una sola carga de modelo, serializado (torch CPU no es
	thread-safe para predict concurrente: un lock por request)."""

	def __init__(self, agent: object, socket_path: str):
		self.agent = agent
		self.socket_path = socket_path
		self._lock = asyncio.Lock()
		self._writers: set = set()
		self._ino: int | None = None

	async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
		self._writers.add(writer)
		try:
			while True:
				try:
					line = await reader.readline()
				except (ValueError, asyncio.LimitOverrunError):
					# Línea > READ_LIMIT: responder y cerrar (nunca cierre mudo).
					try:
						writer.write((json.dumps({"id": None, "ok": False, "error": "line-too-long"}) + "\n").encode("utf-8"))
						await writer.drain()
					except Exception:
						pass
					break
				if not line:
					break
				try:
					req = json.loads(line)
					if not isinstance(req, dict):
						req = {}
				except (ValueError, UnicodeDecodeError):
					req = {"_malformed": True}
				async with self._lock:
					loop = asyncio.get_running_loop()
					resp = await loop.run_in_executor(None, handle, self.agent, req)
				writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
				await writer.drain()
		except (ConnectionResetError, BrokenPipeError):
			pass
		except Exception as e:
			logger.warning(f"[laya_tag] conexión abortada: {e}")
		finally:
			self._writers.discard(writer)
			try:
				writer.close()
			except Exception:
				pass

	def _unlink_own(self, path: Path) -> None:
		"""Retira el socket SOLO si el inodo sigue siendo el que creamos (no borrar
		el socket vivo de otra instancia)."""
		try:
			if self._ino is not None and path.exists() and os.stat(path).st_ino == self._ino:
				path.unlink()
		except OSError:
			pass

	async def serve(self) -> None:
		path = Path(self.socket_path)
		created_dir = not path.parent.exists()
		path.parent.mkdir(parents=True, exist_ok=True)
		if created_dir:
			try:
				# Solo si lo creamos nosotros: el dir es compartido con el daemon
				# (no re-imponer permisos sobre el que ya gestiona otra unidad).
				os.chmod(path.parent, 0o700)
			except OSError:
				pass
		if path.exists():
			# No pisar un socket VIVO (split-brain: la 2ª instancia dejaba
			# inalcanzable a la 1ª desenlazando su inodo). Rancio → se borra.
			if _socket_alive(str(path)):
				raise RuntimeError(f"ya hay un sidecar escuchando en {path} (socket vivo); no se pisa")
			path.unlink()
		old_umask = os.umask(0o077)
		try:
			server = await asyncio.start_unix_server(self._client, path=str(path), limit=READ_LIMIT)
		finally:
			os.umask(old_umask)
		os.chmod(path, 0o600)
		try:
			self._ino = os.stat(path).st_ino
		except OSError:
			self._ino = None
		logger.info(f"[laya_tag] escuchando en {path} (modelo cargado={self.agent is not None})")
		try:
			# NO usar serve_forever(): en CPython 3.12 atrapa CancelledError y hace
			# `await self.wait_closed()` internamente, que aguarda a los handlers
			# —un cliente UDS ocioso colgaría el stop de systemd (SIGKILL 90s →
			# socket rancio). `start_unix_server` ya acepta conexiones; basta con
			# esperar aquí y cerrar nosotros en el `finally`.
			await asyncio.Event().wait()
		finally:
			# Cerrar el server y los clientes. NO se espera `wait_closed()`: en
			# Python 3.12 aguarda a que terminen los handlers y un cliente UDS
			# ocioso colgaría el stop de systemd (SIGKILL a los 90s → socket
			# rancio). `close()` + cerrar writers basta; los handlers ven EOF y
			# terminan (y el cierre del loop los cancelaría igualmente).
			server.close()
			for w in list(self._writers):
				try:
					w.close()
				except Exception:
					pass
			self._unlink_own(path)


def _socket_alive(socket_path: str, timeout: float = 0.5) -> bool:
	"""True si hay alguien escuchando en el socket (evita pisar una instancia viva)."""
	s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	s.settimeout(timeout)
	try:
		s.connect(socket_path)
		return True
	except OSError:
		return False
	finally:
		s.close()


def check_ok(resp: dict) -> bool:
	"""`--check` solo da OK si el sidecar responde Y tiene el modelo cargado."""
	return bool(resp.get("ok") and resp.get("pong") and resp.get("model_loaded"))


def send_request(payload: dict, socket_path: str | None = None, timeout: float = 2.0) -> dict:
	"""Cliente mínimo UDS (usado por `--check` y por el smoke). Un request/una línea.

	Respuesta vacía o no-JSON → RuntimeError (nunca un `{}` silencioso: el
	cliente de P2 debe poder distinguir "sin respuesta" de "respuesta".)
	"""
	sock_path = socket_path or default_socket_path()
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
		try:
			return json.loads(buf.decode("utf-8"))
		except (ValueError, UnicodeDecodeError) as e:
			raise RuntimeError(f"bad-response: {e}") from e
	finally:
		s.close()


def load_agent():
	"""Carga Laya (import diferido: a nivel de módulo NUNCA se importa torch).

	Seam de test `LAYA_TAG_FAKE_LOAD_S`: simula una carga lenta sin cargar el
	modelo (permite verificar la parada durante la carga sin torch).
	"""
	fake = os.getenv("LAYA_TAG_FAKE_LOAD_S")
	if fake:
		time.sleep(float(fake))
		return None
	import laya  # noqa: PLC0415

	t0 = time.time()
	agent = laya.load(MODEL_ID, subfolder=MODEL_SUBFOLDER, device="cpu")
	logger.info(f"[laya_tag] modelo cargado en {time.time() - t0:.1f}s")
	return agent


async def _serve_with_load(srv: "TagServer") -> None:
	"""Escucha ANTES de cargar (el socket existe desde el arranque y responde
	`model-not-loaded` mientras carga) y carga el modelo en un executor.

	Así `--check` da un veredicto rápido y explícito durante el arranque en frío
	en vez de un `connection refused` opaco, y no hay ventana en la que la unit
	esté `active` pero nadie escuche. Si la carga falla → se propaga y el
	proceso sale (systemd reinicia, acotado por StartLimit).
	"""

	async def _load() -> None:
		loop = asyncio.get_running_loop()
		srv.agent = await loop.run_in_executor(None, load_agent)

	loop = asyncio.get_running_loop()
	# SIGTERM (systemd stop) por defecto mata el proceso SIN ejecutar `finally`:
	# el socket quedaría rancio. Convertirlo en una parada ordenada.
	stop = asyncio.Event()
	for sig in (signal.SIGTERM, signal.SIGINT):
		try:
			loop.add_signal_handler(sig, stop.set)
		except (NotImplementedError, RuntimeError):
			pass

	loader = asyncio.create_task(_load())
	server_task = asyncio.create_task(srv.serve())
	stop_task = asyncio.create_task(stop.wait())
	try:
		# 1) esperar carga o parada. Si piden parar durante la carga, NO esperar
		#    al executor de torch (run_in_executor no es cancelable y asyncio.run
		#    aguardaría al thread → stop colgado): retirar el socket y salir.
		await asyncio.wait({loader, stop_task}, return_when=asyncio.FIRST_COMPLETED)
		if stop_task.done() and not loader.done():
			logger.info("[laya_tag] parada durante la carga; salida inmediata")
			try:
				p = Path(srv.socket_path)
				if srv._ino is not None and p.exists() and os.stat(p).st_ino == srv._ino:
					p.unlink()
			except OSError:
				pass
			os._exit(0)
		if loader.exception() is not None:
			raise loader.exception()  # type: ignore[misc]
		# 2) servir hasta la señal de parada o la muerte del servidor.
		await asyncio.wait({server_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
		if server_task.done() and server_task.exception() is not None:
			raise server_task.exception()  # type: ignore[misc]
	finally:
		for t in (loader, server_task, stop_task):
			t.cancel()
		# Dejar que la cancelación corra los `finally` (retirada del socket).
		await asyncio.gather(loader, server_task, stop_task, return_exceptions=True)
		for sig in (signal.SIGTERM, signal.SIGINT):
			try:
				loop.remove_signal_handler(sig)
			except (NotImplementedError, RuntimeError):
				pass


def main() -> int:
	logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [LAYATAG] %(message)s")
	ap = argparse.ArgumentParser(description="Sidecar UDS de etiquetado Laya (RFC-004).")
	ap.add_argument("--socket", default=default_socket_path())
	ap.add_argument("--check", action="store_true", help="Hace ping al socket y sale.")
	args = ap.parse_args()

	if args.check:
		try:
			# Timeout amplio: durante el arranque en frío el import de torch puede
			# acaparar el GIL y retrasar la respuesta (el loop se queda "sordo"
			# unos segundos); un timeout corto daría falso negativo.
			resp = send_request({"id": "probe", "ping": True}, socket_path=args.socket, timeout=10.0)
			ok = check_ok(resp)
			print(json.dumps({"ok": ok, "response": resp}, ensure_ascii=False))
			return 0 if ok else 1
		except Exception as e:
			print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
			return 1

	try:
		asyncio.run(_serve_with_load(TagServer(None, args.socket)))
	except KeyboardInterrupt:
		pass
	except Exception as e:
		logger.error(f"[laya_tag] arranque abortado: {e}")
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
