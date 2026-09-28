"""RFC-004 P2 — tests del cliente de etiquetado (sin torch, sin Qdrant real).

Usa el servidor real (`scripts/laya_tag_server.py`) en un hilo con un agente
falso: así se valida de paso que cliente y servidor hablan el mismo protocolo.
"""

from __future__ import annotations

import asyncio
import importlib.util
import socket
import threading
import time
from pathlib import Path

import red_pill.config as cfg
from red_pill.core import realtime_tag

SERVER_PY = Path(__file__).resolve().parents[1] / "scripts" / "laya_tag_server.py"
CANNED = {
	"answers": {
		"emotion": {"choice": "calm", "answer_confidence": 0.91},
		"theme": {"choice": "work", "answer_confidence": 0.8},
	}
}
LOWCONF = {
	"answers": {
		"emotion": {"choice": "neutral", "answer_confidence": 0.3},
		"theme": {"choice": "other", "answer_confidence": 0.9},
	}
}


def _load_server():
	spec = importlib.util.spec_from_file_location("laya_tag_server_p2", SERVER_PY)
	mod = importlib.util.module_from_spec(spec)
	assert spec and spec.loader
	spec.loader.exec_module(mod)
	return mod


class _FakeAgent:
	def __init__(self, result):
		self.result = result

	def predict(self, text, questions):
		return self.result


class _ServerThread:
	"""Servidor UDS real en un hilo con su propio event loop."""

	def __init__(self, sock: str, result: dict):
		self.sock = sock
		self.result = result

	def __enter__(self):
		mod = _load_server()
		ready = threading.Event()

		def _run():
			loop = asyncio.new_event_loop()
			asyncio.set_event_loop(loop)
			self.loop = loop
			srv = mod.TagServer(_FakeAgent(self.result), self.sock)
			self._task = loop.create_task(srv.serve())
			loop.call_soon(ready.set)

			async def _wait():
				try:
					await self._task
				except asyncio.CancelledError:
					pass

			try:
				loop.run_until_complete(_wait())
			finally:
				loop.close()

		self.t = threading.Thread(target=_run, daemon=True)
		self.t.start()
		for _ in range(300):
			if Path(self.sock).exists():
				break
			time.sleep(0.01)
		assert Path(self.sock).exists()
		return self

	def __exit__(self, *a):
		self.loop.call_soon_threadsafe(self._task.cancel)
		self.t.join(3)


def _set_enabled(monkeypatch, enabled=True, sock=None, timeout=None):
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", enabled)
	if sock is not None:
		monkeypatch.setattr(cfg, "LAYA_TAG_SOCKET", sock)
	if timeout is not None:
		monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_TIMEOUT_S", timeout)


class _FakeClient:
	def __init__(self, boom=False):
		self.calls = []
		self.boom = boom

	def set_payload(self, collection_name, payload, points):
		if self.boom:
			raise RuntimeError("qdrant down")
		self.calls.append({"collection": collection_name, "payload": payload, "points": points})


class _FakeMemory:
	def __init__(self, boom=False):
		self.client = _FakeClient(boom=boom)


def test_disabled_no_toca_socket(monkeypatch, tmp_path):
	_set_enabled(monkeypatch, False, sock=str(tmp_path / "nope.sock"))
	assert realtime_tag.tag_turn("hola") == {"tag_status": "disabled"}
	assert realtime_tag.maybe_tag(_FakeMemory(), "u1", "hola") == {"tag_status": "disabled"}


def test_default_socket_path(monkeypatch):
	monkeypatch.setattr(cfg, "LAYA_TAG_SOCKET", "/tmp/x.sock")
	assert realtime_tag.default_socket_path() == "/tmp/x.sock"
	monkeypatch.setattr(cfg, "LAYA_TAG_SOCKET", "")
	monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/4242")
	assert realtime_tag.default_socket_path() == "/run/user/4242/red-pill/laya_tag.sock"


def test_ok(monkeypatch, tmp_path):
	sock = str(tmp_path / "ok.sock")
	_set_enabled(monkeypatch, True, sock=sock, timeout=3.0)
	with _ServerThread(sock, CANNED):
		tag = realtime_tag.tag_turn("hola")
	assert tag["tag_status"] == "ok"
	assert tag["tag_emotion"] == "calm" and tag["tag_theme"] == "work"
	assert tag["tag_confidence"] == 0.8


def test_degraded_por_baja_confianza(monkeypatch, tmp_path):
	sock = str(tmp_path / "low.sock")
	_set_enabled(monkeypatch, True, sock=sock, timeout=3.0)
	with _ServerThread(sock, LOWCONF):
		tag = realtime_tag.tag_turn("hola")
	assert tag["tag_status"] == "degraded"
	assert tag["tag_reason"] == "low-confidence"
	assert tag["tag_emotion"] == "neutral"


def test_sidecar_down(monkeypatch, tmp_path):
	_set_enabled(monkeypatch, True, sock=str(tmp_path / "missing.sock"), timeout=2.0)
	tag = realtime_tag.tag_turn("hola")
	assert tag["tag_status"] == "failed"
	assert tag["tag_reason"] == "sidecar-down"


def test_timeout(monkeypatch, tmp_path):
	"""Socket que acepta conexión pero nunca responde → timeout, no cuelgue."""
	sock = str(tmp_path / "slow.sock")
	dummy = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	dummy.bind(sock)
	dummy.listen(1)
	try:
		_set_enabled(monkeypatch, True, sock=sock, timeout=0.4)
		t0 = time.time()
		tag = realtime_tag.tag_turn("hola")
		assert tag["tag_status"] == "failed" and tag["tag_reason"] == "timeout"
		assert time.time() - t0 < 3.0
	finally:
		dummy.close()


def test_apply_tag_escribe_campos():
	mem = _FakeMemory()
	ok = realtime_tag.apply_tag(mem, "u1", {"tag_status": "ok", "tag_emotion": "calm", "tag_theme": "work", "tag_confidence": 0.9, "tag_reason": None})
	assert ok is True
	c = mem.client.calls[0]
	assert c["collection"] == "interaction_memories" and c["points"] == ["u1"]
	assert c["payload"]["tag_status"] == "ok"
	assert c["payload"]["tag_emotion"] == "calm"
	assert c["payload"]["tag_engine"] == "laya-multilingual"
	assert "tagged_at" in c["payload"]
	assert "tag_reason" not in c["payload"] or c["payload"]["tag_reason"] is None


def test_apply_tag_no_lanza_si_falla():
	mem = _FakeMemory(boom=True)
	assert realtime_tag.apply_tag(mem, "u1", {"tag_status": "ok"}) is False


def test_maybe_tag_ok_escribe(monkeypatch, tmp_path):
	sock = str(tmp_path / "mt.sock")
	_set_enabled(monkeypatch, True, sock=sock, timeout=3.0)
	mem = _FakeMemory()
	with _ServerThread(sock, CANNED):
		tag = realtime_tag.maybe_tag(mem, "u9", "hola")
	assert tag["tag_status"] == "ok"
	assert mem.client.calls[0]["points"] == ["u9"]
	assert mem.client.calls[0]["payload"]["tag_status"] == "ok"


def test_maybe_tag_failed_escribe_fallo(monkeypatch, tmp_path):
	_set_enabled(monkeypatch, True, sock=str(tmp_path / "none.sock"), timeout=2.0)
	mem = _FakeMemory()
	tag = realtime_tag.maybe_tag(mem, "u9", "hola")
	assert tag["tag_status"] == "failed"
	# el fallo SÍ se persiste (señalizado, no oculto)
	assert mem.client.calls[0]["payload"]["tag_status"] == "failed"
	assert mem.client.calls[0]["payload"]["tag_reason"] == "sidecar-down"


def test_sin_texto_no_llama(monkeypatch, tmp_path):
	_set_enabled(monkeypatch, True, sock=str(tmp_path / "x.sock"))
	tag = realtime_tag.tag_turn("   ")
	assert tag == {"tag_status": "failed", "tag_reason": "empty-text"}


def test_texto_largo_no_revienta(monkeypatch, tmp_path):
	sock = str(tmp_path / "big2.sock")
	_set_enabled(monkeypatch, True, sock=sock, timeout=3.0)
	with _ServerThread(sock, CANNED):
		tag = realtime_tag.tag_turn("A" * 20000)
	assert tag["tag_status"] in ("ok", "degraded")


def test_texto_largo_se_recorta_y_marca_degraded(monkeypatch, tmp_path):
	"""Recorte: no se miente con un `ok` sobre una vista parcial."""
	sock = str(tmp_path / "big.sock")
	_set_enabled(monkeypatch, True, sock=sock, timeout=3.0)
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_MAX_CHARS", 100)
	with _ServerThread(sock, CANNED):
		tag = realtime_tag.tag_turn("A" * 20000)
	assert tag["tag_status"] == "degraded"
	assert tag["tag_reason"] == "truncated"
	assert tag["tag_emotion"] == "calm"


def test_clip_conserva_cabeza_y_cola():
	mod = realtime_tag
	text = "CABEZA" + "x" * 100 + "COLA"
	clipped, trunc = mod._clip(text, 20)
	assert trunc is True
	assert clipped.startswith("CABEZA")
	assert clipped.endswith("COLA")
	assert len(clipped) <= 20 + 5  # cap + separador "\n...\n"
	short, trunc2 = mod._clip("corto", 100)
	assert (short, trunc2) == ("corto", False)


def test_enabled_lee_flag(monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", False)
	assert realtime_tag.enabled() is False
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", True)
	assert realtime_tag.enabled() is True


def test_timeout_s(monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_TIMEOUT_S", 2.5)
	assert realtime_tag.timeout_s() == 2.5
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_TIMEOUT_S", "bad")
	assert realtime_tag.timeout_s() == 3.0


def test_max_chars(monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_MAX_CHARS", 1200)
	assert realtime_tag.max_chars() == 1200
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_MAX_CHARS", "bad")
	assert realtime_tag.max_chars() == 1500


def test_maybe_tag_reporta_persistencia(monkeypatch, tmp_path):
	"""Un set_payload fallido no debe devolverse como si se hubiera escrito."""
	sock = str(tmp_path / "np.sock")
	_set_enabled(monkeypatch, True, sock=sock, timeout=3.0)
	with _ServerThread(sock, CANNED):
		tag = realtime_tag.maybe_tag(_FakeMemory(boom=True), "u1", "hola")
	assert tag["tag_status"] == "ok"
	assert tag["tag_persisted"] is False


# ── wiring del worker (comportamiento, no grep) ────────────────────────────

class _FakeQueue:
	def __init__(self, items):
		self.items = list(items)
		self.statuses = []

	def dequeue_pending(self, limit: int = 10):
		out = self.items[:limit]
		self.items = self.items[limit:]
		return out

	def update_status(self, item_id, status):
		self.statuses.append((item_id, status))


class _FakeWorkerMemory:
	def __init__(self, client):
		self.client = client
		self.recorded = []

	def record_interaction_pair(self, **kwargs):
		self.recorded.append(kwargs)
		return "u1"


_ITEM = {
	"id": "q1",
	"prompt": "Hola, necesito que revises el daemon porque no arranca bien.",
	"response": "Vale, lo miro ahora mismo y te confirmo en un momento.",
	"role": "assistant",
	"category": "mixed",
	"model": "m",
	"originator": "opencode",
}


def test_worker_gate_off_no_etiqueta(monkeypatch):
	"""Flag OFF: el drenaje no toca set_payload (RULE 4, comportamiento real)."""
	from red_pill.core.queue_worker import drain_memory_queue

	_set_enabled(monkeypatch, False)
	client = _FakeClient()
	mem = _FakeWorkerMemory(client)
	q = _FakeQueue([dict(_ITEM)])
	n = drain_memory_queue(q, mem, limit=10, max_batches=1)
	assert n == 1
	assert mem.recorded and client.calls == []
	assert ("q1", "completed") in q.statuses


def test_worker_gate_off_no_llama_maybe_tag(monkeypatch):
	"""Mutación-resistente: quitar `if _rt_tag.enabled()` haría llamar maybe_tag."""
	from red_pill.core import realtime_tag
	from red_pill.core.queue_worker import drain_memory_queue

	calls = []
	monkeypatch.setattr(realtime_tag, "maybe_tag", lambda *a, **k: calls.append(a) or {"tag_status": "ok"})
	_set_enabled(monkeypatch, False)
	client = _FakeClient()
	mem = _FakeWorkerMemory(client)
	q = _FakeQueue([dict(_ITEM)])
	drain_memory_queue(q, mem, limit=10, max_batches=1)
	assert calls == []


def test_worker_presupuesto_agotado_no_llama(monkeypatch):
	"""Presupuesto de drenaje 0 → no se llama al sidecar (acota N×timeout)."""
	from red_pill.core import realtime_tag
	from red_pill.core.queue_worker import drain_memory_queue

	calls = []
	monkeypatch.setattr(realtime_tag, "maybe_tag", lambda *a, **k: calls.append(a) or {"tag_status": "ok"})
	_set_enabled(monkeypatch, True)
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_BUDGET_S", 0.0)
	mem = _FakeWorkerMemory(_FakeClient())
	q = _FakeQueue([dict(_ITEM)])
	drain_memory_queue(q, mem, limit=10, max_batches=1)
	assert calls == []


def test_worker_gate_on_etiqueta(monkeypatch, tmp_path):
	"""Flag ON: se escribe tag_status=ok en el engrama."""
	from red_pill.core.queue_worker import drain_memory_queue

	sock = str(tmp_path / "w.sock")
	_set_enabled(monkeypatch, True, sock=sock, timeout=3.0)
	client = _FakeClient()
	mem = _FakeWorkerMemory(client)
	q = _FakeQueue([dict(_ITEM)])
	with _ServerThread(sock, CANNED):
		n = drain_memory_queue(q, mem, limit=10, max_batches=1)
	assert n == 1
	assert client.calls and client.calls[0]["points"] == ["u1"]
	assert client.calls[0]["payload"]["tag_status"] == "ok"
	assert client.calls[0]["payload"]["tag_emotion"] == "calm"
	assert ("q1", "completed") in q.statuses


def test_worker_sidecar_caido_no_rompe_drenaje(monkeypatch, tmp_path):
	"""Flag ON y sidecar caído: el engrama se escribe igual, tag failed."""
	from red_pill.core.queue_worker import drain_memory_queue

	_set_enabled(monkeypatch, True, sock=str(tmp_path / "down.sock"), timeout=1.0)
	client = _FakeClient()
	mem = _FakeWorkerMemory(client)
	q = _FakeQueue([dict(_ITEM)])
	n = drain_memory_queue(q, mem, limit=10, max_batches=1)
	assert n == 1
	assert mem.recorded  # el registro ocurrió
	assert client.calls[0]["payload"]["tag_status"] == "failed"
	assert ("q1", "completed") in q.statuses
