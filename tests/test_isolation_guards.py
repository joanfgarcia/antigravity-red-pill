"""Las guardas de aislamiento de la suite (tests/_isolation_guards.py) funcionan.

Cada comprobación usa un servidor PROPIO del test (nunca un servicio real): se
marca su puerto/ruta como "real" y se verifica que la guarda corta la conexión
aunque haya alguien escuchando.
"""

import os
import socket
import subprocess
import tempfile
import threading
from pathlib import Path

import _isolation_guards as guards
import pytest


@pytest.fixture
def consume_violations():
	"""Las violaciones provocadas a propósito no deben tumbar el propio test."""
	yield
	guards.take_violations()


def _tcp_server():
	srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	srv.bind(("127.0.0.1", 0))
	srv.listen(1)
	return srv


def test_tcp_a_un_puerto_de_servicio_real_se_bloquea_aunque_escuche(monkeypatch, consume_violations):
	srv = _tcp_server()
	port = srv.getsockname()[1]
	try:
		monkeypatch.setattr(guards, "GUARDED_TCP_PORTS", frozenset({port}))
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as c:
			with pytest.raises(ConnectionRefusedError, match="TEST ISOLATION"):
				c.connect(("127.0.0.1", port))
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as c:
			assert c.connect_ex(("localhost", port)) != 0
		assert len(guards.take_violations()) == 2
	finally:
		srv.close()


def test_tcp_local_a_otro_puerto_se_permite():
	srv = _tcp_server()
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as c:
			c.connect(srv.getsockname())
	finally:
		srv.close()


def test_host_remoto_se_bloquea_sin_salir_a_la_red(consume_violations):
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as c:
		c.settimeout(1)
		with pytest.raises(ConnectionRefusedError, match="no-loopback"):
			c.connect(("192.0.2.1", 443))  # TEST-NET-1: ni siquiera es enrutable


def test_puertos_de_servicios_del_operador_estan_vigilados():
	assert {6333, 6334, 8760, 8761, 8770, 8771} <= guards.GUARDED_TCP_PORTS


def test_uds_dentro_del_sandbox_se_permite_y_fuera_se_bloquea(tmp_path, monkeypatch, consume_violations):
	path = str(tmp_path / "s.sock")
	srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	srv.bind(path)
	srv.listen(1)
	accepted = threading.Thread(target=lambda: srv.accept()[0].close(), daemon=True)
	accepted.start()
	try:
		with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
			c.connect(path)  # tmp_path vive en el sandbox
		monkeypatch.setattr(guards, "_allowed_unix_roots", [])
		with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
			with pytest.raises(ConnectionRefusedError, match="fuera del sandbox"):
				c.connect(path)
		with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
			with pytest.raises(ConnectionRefusedError, match="abstracto"):
				c.connect("\0rp-test-abstract")
	finally:
		srv.close()


@pytest.mark.allow_local_services
def test_marker_allow_local_services_desactiva_la_guarda(monkeypatch):
	srv = _tcp_server()
	port = srv.getsockname()[1]
	try:
		monkeypatch.setattr(guards, "GUARDED_TCP_PORTS", frozenset({port}))
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as c:
			c.connect(("127.0.0.1", port))
	finally:
		srv.close()


def test_systemctl_de_lectura_responde_inactive_determinista():
	r = subprocess.run(["systemctl", "--user", "is-active", "redpill-sleep.service"], capture_output=True, text=True)
	assert (r.returncode, r.stdout.strip()) == (3, "inactive")
	r = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "redpill-llm.service"])
	assert r.returncode == 3
	r = subprocess.run(["systemctl", "--user", "show", "x.service", "--property=MainPID"], capture_output=True, text=True)
	assert r.stdout.strip() == "MainPID=0"
	r = subprocess.run("journalctl --user -n 5 --no-pager", shell=True, capture_output=True, text=True)
	assert (r.returncode, r.stdout) == (0, "")
	r = subprocess.run(["podman", "ps", "--filter", "name=qdrant", "--format", "{{.Status}}"], capture_output=True, text=True)
	assert (r.returncode, r.stdout) == (0, "")


def test_verbos_mutantes_no_llegan_al_host_y_se_registran(consume_violations):
	# Sustituto puro: no se ejecuta nada (ni siquiera el sh de imitación).
	for argv in (
		["systemctl", "--user", "stop", "redpill-llm.service"],
		["/usr/bin/systemctl", "--user", "reset-failed", "redpill-job-x.scope"],
		["systemctl", "--user", "-p", "MemoryMax=1G", "set-property", "x.service"],
		["podman", "restart", "qdrant"],
		["systemd-run", "--user", "--scope", "true"],
		["journalctl", "--user", "--vacuum-time=1s"],
		["bash", "-c", "systemctl --user daemon-reload"],
	):
		sub = guards.host_command_substitute(argv, shell=False)
		assert sub is not None and sub[0] == "/bin/sh" and sub[-1] == "1", argv
	assert guards.host_command_substitute("systemctl --user restart x", shell=True)[-1] == "1"
	assert len(guards.take_violations()) == 8
	assert guards.host_command_substitute(["git", "status"], shell=False) is None


def test_verbo_mutante_devuelve_error_y_queda_registrado():
	"""Lo registrado es lo que el fixture `_isolation_guards` convierte en fallo."""
	sub = guards.host_command_substitute(["systemctl", "--user", "start", "x.service"], shell=False)
	r = subprocess.run(sub, capture_output=True, text=True)
	assert r.returncode == 1 and "TEST ISOLATION" in r.stderr
	pending = guards.take_violations()
	assert len(pending) == 1 and "systemctl --user start x.service" in pending[0]


def test_sandbox_temporal_y_runtime_redirigidos():
	sandbox = os.environ[guards.SANDBOX_ENV]
	assert tempfile.gettempdir() == sandbox
	assert os.environ["TMPDIR"] == sandbox
	runtime = os.environ["XDG_RUNTIME_DIR"]
	assert runtime.startswith(sandbox + os.sep) and os.path.isdir(runtime)
	assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["CUDA_VISIBLE_DEVICES"] == ""

	import red_pill.config as cfg
	from red_pill.core import paths

	assert cfg.get_config().RUNTIME_DIR == runtime
	assert str(paths.get_daemon_dir()).startswith(runtime)


def test_runtime_real_del_operador_aborta_bajo_tests(monkeypatch):
	import red_pill.config as cfg
	from red_pill.core import paths

	real = paths._operator_runtime_dir()
	with pytest.raises(RuntimeError, match="TEST ISOLATION"):
		paths._assert_not_production_runtime(real / "red-pill" / "gpu_reservations.json", "x")
	# XDG_RUNTIME_DIR inexistente: antes caía en silencio a /run/user/<uid>
	monkeypatch.setenv("XDG_RUNTIME_DIR", str(Path(tempfile.gettempdir()) / "no-existe"))
	if real.exists():
		with pytest.raises(RuntimeError, match="TEST ISOLATION"):
			_ = cfg.get_config().RUNTIME_DIR
	monkeypatch.setenv("XDG_RUNTIME_DIR", str(real))
	with pytest.raises(RuntimeError, match="TEST ISOLATION"):
		paths.get_daemon_dir()


@pytest.mark.parametrize("port", sorted(guards.GUARDED_TCP_PORTS))
def test_puertos_reales_del_operador_nunca_se_alcanzan(port, consume_violations):
	"""Extremo a extremo contra los puertos REALES (Qdrant, LLM, neon-link): socket,
	urllib y requests rebotan con ConnectionRefused antes de tocar el servicio."""
	import urllib.error
	import urllib.request

	# Precondiciones puras (sin E/S): si la guarda no estuviera, el test para AQUÍ.
	assert socket.socket.connect is guards._guarded_connect
	assert socket.socket.connect_ex is guards._guarded_connect_ex
	probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	try:
		assert guards._blocked_reason(probe, ("127.0.0.1", port))
		assert guards._blocked_reason(probe, ("localhost", port))
	finally:
		probe.close()

	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as c:
		with pytest.raises(ConnectionRefusedError, match="TEST ISOLATION"):
			c.connect(("127.0.0.1", port))
	with pytest.raises(urllib.error.URLError) as exc:
		urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/unload", method="POST"), timeout=2)
	assert isinstance(exc.value.reason, ConnectionRefusedError)
	requests = pytest.importorskip("requests")
	with pytest.raises(requests.exceptions.ConnectionError):
		requests.post(f"http://localhost:{port}/v1/chat/completions", json={"task": "hub"}, timeout=2)
	assert len(guards.take_violations()) >= 3
