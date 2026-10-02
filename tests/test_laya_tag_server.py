"""RFC-004 P1 — tests del sidecar UDS de etiquetado (sin torch, sin red TCP).

Carga el módulo desde `scripts/` por ruta (el .venv del repo NO tiene laya/torch:
si el módulo importara torch a nivel de módulo, estos tests no cargarían — eso
es en sí mismo la verificación de que el import es diferido).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

SERVER_PY = Path(__file__).resolve().parents[1] / "scripts" / "laya_tag_server.py"


def _load():
	spec = importlib.util.spec_from_file_location("laya_tag_server_test", SERVER_PY)
	mod = importlib.util.module_from_spec(spec)
	assert spec and spec.loader
	spec.loader.exec_module(mod)
	return mod


CANNED = {
	"answers": {
		"emotion": {"choice": "calm", "answer_confidence": 0.91},
		"theme": {"choice": "work", "answer_confidence": 0.77},
	},
	"usage": {"input_tokens": 120, "output_tokens": 0},
}

LOWCONF = {
	"answers": {
		"emotion": {"choice": "neutral", "answer_confidence": 0.30},
		"theme": {"choice": "other", "answer_confidence": 0.91},
	},
}


class _FakeAgent:
	def __init__(self, result=None, boom=False):
		self.result = result or CANNED
		self.boom = boom
		self.calls = 0

	def predict(self, text, questions):
		self.calls += 1
		if self.boom:
			raise RuntimeError("model down")
		return self.result


def test_import_no_arrastra_torch():
	"""El import de laya/torch debe ser diferido (dentro de load_agent).

	Se comprueba por AST (determinista): ningún import de módulo importa
	torch/laya; y `load_agent` sí lo hace dentro.
	"""
	import ast

	mod = _load()
	assert hasattr(mod, "build_questions")
	tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"))
	top_level = set()
	for node in tree.body:
		if isinstance(node, ast.Import):
			top_level.update(a.name.split(".")[0] for a in node.names)
		elif isinstance(node, ast.ImportFrom) and node.module:
			top_level.add(node.module.split(".")[0])
	assert "torch" not in top_level
	assert "laya" not in top_level
	fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "load_agent"]
	assert fns, "load_agent debe existir"
	imported_in_load = {a.name.split(".")[0] for n in ast.walk(fns[0]) if isinstance(n, ast.Import) for a in n.names}
	assert "laya" in imported_in_load


def test_default_socket_respeta_env(monkeypatch):
	mod = _load()
	monkeypatch.setenv("LAYA_TAG_SOCK", "/tmp/x/laya.sock")
	assert mod.default_socket_path() == "/tmp/x/laya.sock"
	monkeypatch.delenv("LAYA_TAG_SOCK", raising=False)
	monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1234")
	assert mod.default_socket_path() == "/run/user/1234/red-pill/laya_tag.sock"


def test_build_questions_esquema_laya():
	mod = _load()
	q = mod.build_questions()
	assert set(q) == {"emotion", "theme"}
	for axis in q.values():
		assert axis["type"] == "choice"
		assert isinstance(axis["criteria"], dict) and axis["criteria"]
		assert "instructions" in axis
	assert set(q["emotion"]["criteria"]) == set(mod.EMOTIONS)
	assert set(q["theme"]["criteria"]) == set(mod.THEMES)


def test_normalize_ok():
	mod = _load()
	tag = mod.normalize(CANNED)
	assert tag["emotion"] == {"label": "calm", "confidence": 0.91}
	assert tag["theme"] == {"label": "work", "confidence": 0.77}
	assert tag["confidence"] == 0.77
	assert tag["low_confidence"] is False


def test_normalize_low_confidence():
	mod = _load()
	tag = mod.normalize(LOWCONF)
	assert tag["confidence"] == 0.30
	assert tag["low_confidence"] is True


def test_normalize_label_desconocido():
	mod = _load()
	tag = mod.normalize({"answers": {"emotion": {"choice": "euforia"}, "theme": {"choice": "work"}}})
	assert tag["emotion"]["label"] == "?"
	assert tag["theme"]["label"] == "work"


def test_normalize_vacio_no_lanza():
	mod = _load()
	assert mod.normalize({})["emotion"]["label"] == "?"
	assert mod.normalize(None)["theme"]["label"] == "?"


def test_handle_ping():
	mod = _load()
	resp = mod.handle(_FakeAgent(), {"id": "p", "ping": True})
	assert resp == {"id": "p", "ok": True, "pong": True, "model_loaded": True}


def test_handle_texto_vacio():
	mod = _load()
	resp = mod.handle(_FakeAgent(), {"id": "1", "text": "   "})
	assert resp["ok"] is False and resp["error"] == "empty-text"


def test_handle_sin_modelo():
	mod = _load()
	resp = mod.handle(None, {"id": "1", "text": "hola"})
	assert resp["ok"] is False and resp["error"] == "model-not-loaded"


def test_handle_ok():
	mod = _load()
	agent = _FakeAgent()
	resp = mod.handle(agent, {"id": "1", "text": "hola"})
	assert resp["ok"] is True
	assert resp["emotion"]["label"] == "calm"
	assert resp["theme"]["label"] == "work"
	assert "lat_s" in resp and agent.calls == 1


def test_handle_modelo_que_revienta_no_propaga():
	mod = _load()
	resp = mod.handle(_FakeAgent(boom=True), {"id": "1", "text": "hola"})
	assert resp["ok"] is False and "RuntimeError" in resp["error"]


def test_roundtrip_uds(tmp_path):
	mod = _load()
	sock = str(tmp_path / "t.sock")
	agent = _FakeAgent()

	async def _run():
		srv = mod.TagServer(agent, sock)
		task = asyncio.create_task(srv.serve())
		for _ in range(200):
			if Path(sock).exists():
				break
			await asyncio.sleep(0.01)
		loop = asyncio.get_running_loop()
		ok = await loop.run_in_executor(None, mod.send_request, {"id": "a", "text": "hola"}, sock, 2.0)
		ping = await loop.run_in_executor(None, mod.send_request, {"id": "b", "ping": True}, sock, 2.0)
		task.cancel()
		try:
			await task
		except asyncio.CancelledError:
			pass
		return ok, ping

	resp, ping = asyncio.run(_run())
	assert resp["ok"] is True and resp["emotion"]["label"] == "calm"
	assert ping["ok"] is True and ping["pong"] is True
	assert agent.calls == 1


def test_linea_malformada_no_tumba_el_server(tmp_path):
	mod = _load()
	sock = str(tmp_path / "m.sock")

	async def _run():
		srv = mod.TagServer(_FakeAgent(), sock)
		task = asyncio.create_task(srv.serve())
		for _ in range(200):
			if Path(sock).exists():
				break
			await asyncio.sleep(0.01)
		loop = asyncio.get_running_loop()

		def _raw():
			s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			s.settimeout(2.0)
			s.connect(sock)
			s.sendall(b"esto no es json\n")
			buf = b""
			while not buf.endswith(b"\n"):
				chunk = s.recv(65536)
				if not chunk:
					break
				buf += chunk
			s.close()
			return json.loads(buf.decode())

		bad = await loop.run_in_executor(None, _raw)
		# el server sigue vivo tras la línea basura
		good = await loop.run_in_executor(None, mod.send_request, {"id": "z", "ping": True}, sock, 2.0)
		task.cancel()
		try:
			await task
		except asyncio.CancelledError:
			pass
		return bad, good

	bad, good = asyncio.run(_run())
	assert bad["ok"] is False
	assert good["ok"] is True and good["pong"] is True


def test_send_request_socket_ausente_falla_limpio(tmp_path):
	mod = _load()
	with pytest.raises((FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError)):
		mod.send_request({"id": "x", "ping": True}, str(tmp_path / "nope.sock"), 1.0)


def test_check_ok_exige_modelo_cargado():
	mod = _load()
	assert mod.check_ok({"ok": True, "pong": True, "model_loaded": True}) is True
	assert mod.check_ok({"ok": True, "pong": True, "model_loaded": False}) is False
	assert mod.check_ok({"ok": True, "pong": True}) is False
	assert mod.check_ok({}) is False


def test_linea_demasiado_larga_responde_error(tmp_path):
	"""Panel P1: una línea > límite no debe cerrar en silencio."""
	mod = _load()
	sock = str(tmp_path / "big.sock")

	async def _run():
		srv = mod.TagServer(_FakeAgent(), sock)
		task = asyncio.create_task(srv.serve())
		for _ in range(200):
			if Path(sock).exists():
				break
			await asyncio.sleep(0.01)
		loop = asyncio.get_running_loop()

		def _raw():
			s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			s.settimeout(3.0)
			s.connect(sock)
			s.sendall(b'{"id":"x","text":"' + b"A" * (mod.READ_LIMIT + 1024) + b'"}\n')
			buf = b""
			while not buf.endswith(b"\n"):
				chunk = s.recv(65536)
				if not chunk:
					break
				buf += chunk
			s.close()
			return json.loads(buf.decode())

		resp = await loop.run_in_executor(None, _raw)
		task.cancel()
		try:
			await task
		except asyncio.CancelledError:
			pass
		return resp

	resp = asyncio.run(_run())
	assert resp["ok"] is False
	assert resp["error"] == "line-too-long"


def test_segunda_instancia_no_pisa_socket_vivo(tmp_path):
	"""Panel P1: split-brain — la 2ª instancia no debe desenlazar un socket vivo."""
	mod = _load()
	sock = str(tmp_path / "dup.sock")
	live = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	live.bind(sock)
	live.listen(1)
	try:
		with pytest.raises(RuntimeError):
			asyncio.run(mod.TagServer(_FakeAgent(), sock).serve())
	finally:
		live.close()


def test_socket_rancio_se_recupera(tmp_path):
	"""Un socket muerto (sin listener) sí se reemplaza."""
	mod = _load()
	sock = str(tmp_path / "stale.sock")
	stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	stale.bind(sock)
	stale.close()
	assert Path(sock).exists()
	assert mod._socket_alive(sock) is False

	async def _run():
		srv = mod.TagServer(_FakeAgent(), sock)
		task = asyncio.create_task(srv.serve())
		for _ in range(200):
			if mod._socket_alive(sock):
				break
			await asyncio.sleep(0.01)
		ok = await asyncio.get_running_loop().run_in_executor(None, mod.send_request, {"id": "s", "ping": True}, sock, 2.0)
		task.cancel()
		try:
			await task
		except asyncio.CancelledError:
			pass
		return ok

	assert asyncio.run(_run())["ok"] is True


def test_escucha_antes_de_cargar_y_retira_socket_al_parar(tmp_path, monkeypatch):
	"""Panel P1: sin ventana 'active pero sordo'; y el socket se retira al parar."""
	import time as _time

	mod = _load()
	sock = str(tmp_path / "boot.sock")

	def _slow_load():
		_time.sleep(1.0)
		return _FakeAgent()

	monkeypatch.setattr(mod, "load_agent", _slow_load)

	async def _run():
		srv = mod.TagServer(None, sock)
		task = asyncio.create_task(mod._serve_with_load(srv))
		for _ in range(300):
			if Path(sock).exists():
				break
			await asyncio.sleep(0.01)
		loop = asyncio.get_running_loop()
		early = await loop.run_in_executor(None, mod.send_request, {"id": "e", "text": "x"}, sock, 2.0)
		for _ in range(300):
			if srv.agent is not None:
				break
			await asyncio.sleep(0.01)
		late = await loop.run_in_executor(None, mod.send_request, {"id": "l", "text": "x"}, sock, 2.0)
		task.cancel()
		try:
			await task
		except asyncio.CancelledError:
			pass
		return early, late, Path(sock).exists()

	early, late, exists_after = asyncio.run(_run())
	assert early["ok"] is False and early["error"] == "model-not-loaded"
	assert late["ok"] is True and late["emotion"]["label"] == "calm"
	assert exists_after is False


def test_stop_con_cliente_conectado_no_cuelga(tmp_path):
	"""Panel P1 pass3: un cliente UDS ocioso no debe colgar el apagado."""
	import threading

	mod = _load()
	sock = str(tmp_path / "c.sock")
	holder: dict = {"evt": threading.Event()}

	def _client_thread():
		s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		s.settimeout(5.0)
		s.connect(sock)
		s.sendall(b'{"id":"1","ping":true}\n')
		buf = b""
		while not buf.endswith(b"\n"):
			buf += s.recv(4096)
		holder["pong"] = json.loads(buf.decode())
		holder["ready"] = True
		holder["evt"].wait(10)  # mantiene la conexión abierta
		s.close()

	async def _run():
		srv = mod.TagServer(_FakeAgent(), sock)
		task = asyncio.create_task(srv.serve())
		for _ in range(200):
			if mod._socket_alive(sock):
				break
			await asyncio.sleep(0.01)
		t = threading.Thread(target=_client_thread, daemon=True)
		t.start()
		for _ in range(300):
			if holder.get("ready"):
				break
			await asyncio.sleep(0.01)
		assert holder.get("pong", {}).get("pong") is True
		# cancelar con el cliente aún conectado: debe terminar sin colgarse
		task.cancel()
		try:
			await asyncio.wait_for(task, timeout=5.0)
		except asyncio.CancelledError:
			pass
		holder["evt"].set()
		t.join(2)
		return True

	assert asyncio.run(_run()) is True


def test_unlink_own_no_borra_socket_ajeno(tmp_path):
	"""No retirar un fichero cuyo inodo no es el que creamos."""
	mod = _load()
	p = tmp_path / "otro"
	p.write_text("x")
	srv = mod.TagServer(_FakeAgent(), str(tmp_path / "s.sock"))
	srv._ino = 1  # inodo que no coincide con el del fichero
	srv._unlink_own(p)
	assert p.exists()
	# inodo correcto → sí lo retira
	srv._ino = p.stat().st_ino
	srv._unlink_own(p)
	assert not p.exists()


def test_no_cambia_permisos_de_dir_preexistente(tmp_path):
	"""Panel P1 pass4: no re-imponer 0700 sobre el dir runtime compartido."""
	mod = _load()
	d = tmp_path / "rt"
	d.mkdir()
	os.chmod(d, 0o775)
	sock = str(d / "s.sock")

	async def _run():
		srv = mod.TagServer(_FakeAgent(), sock)
		task = asyncio.create_task(srv.serve())
		for _ in range(200):
			if mod._socket_alive(sock):
				break
			await asyncio.sleep(0.01)
		task.cancel()
		try:
			await asyncio.wait_for(task, 3.0)
		except asyncio.CancelledError:
			pass
		return os.stat(d).st_mode & 0o777

	assert asyncio.run(_run()) == 0o775


def test_sigterm_durante_carga_sale_rapido(tmp_path):
	"""Panel P1 pass4: SIGTERM durante la carga no espera al executor de torch."""
	sock = str(tmp_path / "boot.sock")
	env = dict(os.environ, LAYA_TAG_FAKE_LOAD_S="30", LAYA_TAG_SOCK=sock)
	p = subprocess.Popen([sys.executable, str(SERVER_PY)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	try:
		for _ in range(300):
			if Path(sock).exists():
				break
			time.sleep(0.02)
		assert Path(sock).exists()
		t0 = time.time()
		p.send_signal(signal.SIGTERM)
		p.wait(timeout=8)
		dt = time.time() - t0
		assert p.returncode == 0
		assert dt < 5.0
		assert not Path(sock).exists()
	finally:
		if p.poll() is None:
			p.kill()


def test_unit_no_declara_runtimedirectory():
	"""Guardarraíl: RuntimeDirectory=red-pill borraría el socket del daemon al parar."""
	unit = (Path(__file__).resolve().parents[1] / "systemd" / "redpill-laya-tag.service").read_text(encoding="utf-8")
	assert "\nRuntimeDirectory=" not in unit
	assert "Restart=always" in unit
	assert "laya_tag_server.py" in unit
	assert "StartLimitIntervalSec=300" in unit  # converge a failed, no bucle infinito


def test_unit_es_plantilla_portable_y_el_instalador_la_reescribe(tmp_path):
	"""Sin rutas de un usuario concreto: la plantilla usa %h y el instalador fija las rutas reales."""
	root = Path(__file__).resolve().parents[1]
	unit = (root / "systemd" / "redpill-laya-tag.service").read_text(encoding="utf-8")
	assert "/home/" not in unit
	assert "%h/" in unit

	venv = tmp_path / "laya-venv"
	(venv / "bin").mkdir(parents=True)
	stub_bin = tmp_path / "stub-bin"
	stub_bin.mkdir()
	for exe in (venv / "bin" / "python", stub_bin / "systemctl"):
		exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
		exe.chmod(0o755)
	home = tmp_path / "home"
	env = {**os.environ, "HOME": str(home), "LAYA_VENV": str(venv), "PATH": f"{stub_bin}{os.pathsep}{os.environ.get('PATH', '')}"}
	subprocess.run(["bash", str(root / "scripts" / "install_laya_tag_service.sh")], env=env, check=True, capture_output=True, text=True, timeout=30)

	installed = (home / ".config" / "systemd" / "user" / "redpill-laya-tag.service").read_text(encoding="utf-8")
	assert "%h/" not in installed
	assert f"WorkingDirectory={root}\n" in installed
	assert f"ExecStart={venv}/bin/python {root}/scripts/laya_tag_server.py\n" in installed
	assert f"Environment=PYTHONPATH={root}/src\n" in installed
