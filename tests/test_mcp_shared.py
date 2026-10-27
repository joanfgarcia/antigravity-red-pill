"""AD-018: MCP compartido (backend UDS + proxy stdio).

Los tests unitarios cubren la identidad del proxy. El E2E real (backend + dos
proxies + dos sesiones) está gateado: arranca un proceso pesado y usa config
real; se activa con `REDPILL_MCP_SHARED_E2E=1`.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from red_pill.mcp_proxy import default_socket, identity_payload

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_identity_payload_from_env(monkeypatch):
	for key in ("REDPILL_ORIGINATOR", "REDPILL_WORKSPACE", "REDPILL_CONTINUITY_ID", "REDPILL_MISSION_ID", "REDPILL_ROLE"):
		monkeypatch.delenv(key, raising=False)
	monkeypatch.setenv("REDPILL_HARNESS", "opencode")
	monkeypatch.setenv("REDPILL_ORIGINATOR", "opencode:s1")
	monkeypatch.setenv("REDPILL_WORKSPACE", "/ws/proj")
	monkeypatch.setenv("REDPILL_CONTINUITY_ID", "alma-1")
	monkeypatch.setenv("REDPILL_MISSION_ID", "repo:x")
	payload = identity_payload()
	assert payload["originator"] == "opencode:s1"
	assert payload["workdir"] == "/ws/proj"
	assert payload["continuity_id"] == "alma-1"
	assert payload["mission_id"] == "repo:x"
	assert payload["harness"] == "opencode"


def test_identity_payload_reads_opencode_bridge(tmp_path, monkeypatch):
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
	monkeypatch.setenv("REDPILL_HARNESS", "opencode")
	monkeypatch.delenv("REDPILL_ORIGINATOR", raising=False)
	monkeypatch.delenv("REDPILL_WORKSPACE", raising=False)
	state = tmp_path / "red-pill" / "state"
	state.mkdir(parents=True)
	(state / "opencode_session.json").write_text(
		json.dumps({"provider": "opencode", "session_id": "ses_abc", "workdir": "/ws/oc"}),
		encoding="utf-8",
	)
	payload = identity_payload("opencode")
	assert payload["originator"] == "opencode:ses_abc"
	assert payload["workdir"] == "/ws/oc"


def _git_repo(path: Path, branch: str) -> Path:
	"""Repo git de verdad en `path` (los tests de identidad usan `git` real)."""
	path.mkdir(parents=True, exist_ok=True)
	subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True, capture_output=True)
	for k, v in (("user.email", "t@t"), ("user.name", "t")):
		subprocess.run(["git", "-C", str(path), "config", k, v], check=True, capture_output=True)
	(path / "a.txt").write_text("x", encoding="utf-8")
	subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
	subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True, capture_output=True)
	return path


def test_resolve_workspace_salta_candidato_fuera_de_repo(tmp_path):
	"""El puente es un fichero global: si el último escritor estaba en una carpeta
	padre sin repo (app desktop con cwd=~), el handshake caía a `mission:adhoc-*`
	y el leg se quedaba sin `ws:` aunque el repo estuviera más abajo en la lista.
	(Regresión 2026-10-27: sesiones opencode en adhoc tras la migración a V2.)
	"""
	from red_pill.mcp_server import _resolve_workspace

	parent = tmp_path / "papers"  # no es repo
	parent.mkdir()
	repo = _git_repo(tmp_path / "sharing", "next")
	workspace, branch, mirror = _resolve_workspace([str(parent), str(repo)])
	assert workspace == str(repo)
	assert branch == "next"
	assert mirror["worktree"] == str(repo)


def test_resolve_workspace_sin_repo_conserva_precedencia(tmp_path):
	from red_pill.mcp_server import _resolve_workspace

	parent = tmp_path / "papers"
	parent.mkdir()
	workspace, branch, mirror = _resolve_workspace([str(parent), ""])
	assert workspace == str(parent)
	assert branch is None
	assert mirror.get("worktree") is None


def test_default_socket_prefers_runtime(monkeypatch):
	monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
	assert default_socket() == "/run/user/1000/red-pill/mcp.sock"


def _env(base: Path) -> dict:
	return {
		**os.environ,
		"XDG_DATA_HOME": str(base / "data"),
		"XDG_STATE_HOME": str(base / "state"),
		"XDG_CACHE_HOME": str(base / "cache"),
		"PYTHONPATH": str(REPO_ROOT / "src"),
	}


async def _session(sock: str, label: str, base: Path) -> str:
	from mcp import StdioServerParameters
	from mcp.client.session import ClientSession
	from mcp.client.stdio import stdio_client

	env = {
		**_env(base),
		"REDPILL_HARNESS": "opencode",
		"REDPILL_ORIGINATOR": f"opencode:e2e-{label}",
		"REDPILL_CONTINUITY_ID": f"alma-e2e-{label}",
		"REDPILL_MISSION_ID": "repo:e2e",
	}
	params = StdioServerParameters(
		command=sys.executable,
		args=["-m", "red_pill.mcp_proxy", "--socket", sock, "--harness", "opencode"],
		env=env,
		cwd=str(REPO_ROOT),
	)
	async with stdio_client(params) as (read, write):
		async with ClientSession(read, write) as session:
			await session.initialize()
			result = await session.call_tool("sovereign_handshake", {"user_prompt": "e2e", "mode": "low"})
			text = "\n".join(getattr(c, "text", "") for c in result.content)
			match = re.findall(r"<session[^>]*/>", text)
			return match[0] if match else text[:200]


@pytest.mark.integration
@pytest.mark.timeout(180)
@pytest.mark.skipif(os.getenv("REDPILL_MCP_SHARED_E2E") != "1", reason="E2E MCP compartido desactivado")
def test_shared_backend_two_sessions(tmp_path):
	sock = str(tmp_path / "mcp.sock")
	env = _env(tmp_path)
	backend = subprocess.Popen(
		[sys.executable, "-m", "red_pill.mcp_backend", "--socket", sock],
		env=env,
		cwd=str(REPO_ROOT),
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
	)
	try:
		for _ in range(150):
			if os.path.exists(sock):
				break
			if backend.poll() is not None:
				pytest.fail("el backend MCP compartido murió al arrancar")
			time.sleep(0.2)
		else:
			pytest.fail("timeout esperando el socket del backend")
		results = asyncio.run(_run_both(sock, tmp_path))
	finally:
		backend.terminate()
		try:
			backend.wait(timeout=10)
		except subprocess.TimeoutExpired:
			backend.kill()
	assert 'continuity_id="alma-e2e-a"' in results["a"]
	assert 'continuity_id="alma-e2e-b"' in results["b"]
	assert 'leg="opencode:e2e-a"' in results["a"]
	assert 'leg="opencode:e2e-b"' in results["b"]


async def _run_both(sock: str, base: Path) -> dict:
	a, b = await asyncio.gather(_session(sock, "a", base), _session(sock, "b", base))
	return {"a": a, "b": b}


def test_resolve_workspace_no_atribuye_el_repo_del_kernel(tmp_path):
	"""Una sesión en una carpeta que no es repo NO debe heredar el checkout del
	kernel (el `cwd` del servidor MCP) sólo porque sea el único repo a mano: eso
	etiquetaría como `repo:<rama-del-kernel>` a quien trabaja en cualquier otro
	sitio. Sin repo declarado → adhoc (honesto)."""
	from red_pill.mcp_server import _resolve_workspace

	kernel = _git_repo(tmp_path / "sharing", "next")
	ajena = tmp_path / "notas"
	ajena.mkdir()
	workspace, branch, _ = _resolve_workspace([str(ajena)], cwd=str(kernel))
	assert workspace == str(ajena)
	assert branch is None


def test_resolve_workspace_desciende_al_repo_cuando_el_padre_lo_contiene(tmp_path):
	"""El caso real de la app desktop: el puente declara `~` (no es repo) y el
	kernel vive debajo. Ahí sí el repo del agente es el del cwd."""
	from red_pill.mcp_server import _resolve_workspace

	home = tmp_path / "home"
	repo = _git_repo(home / "Documents" / "sharing", "next")
	workspace, branch, _ = _resolve_workspace([str(home)], cwd=str(repo))
	assert workspace == str(repo)
	assert branch == "next"


class _SesionFalsa:
	"""Sesión MCP de mentira: las primeras `fallos` llamadas fallan."""

	def __init__(self, estado: dict, valor: str = "pong"):
		self.estado = estado
		self.valor = valor

	async def ping(self):
		if self.estado["fallos"] > 0:
			self.estado["fallos"] -= 1
			raise self.estado["exc"]
		return self.valor


def _parchea_backend(monkeypatch, **kwargs):
	"""Sustituye la conexión real por una sesión falsa y cuenta los intentos."""
	from red_pill import mcp_proxy

	estado = {"fallos": kwargs.get("fallos", 0), "exc": kwargs.get("exc") or RuntimeError("Connection closed")}
	intentos = {"n": 0}

	async def _fake(socket_path, harness, client_info, fn, **kw):
		intentos["n"] += 1
		return await fn(_SesionFalsa(estado))

	monkeypatch.setattr(mcp_proxy, "_with_backend", _fake)
	return intentos


def test_call_backend_reintenta_tras_reiniciar_el_backend(monkeypatch):
	"""Incidente 2026-10-27: reiniciar `redpill-mcp.service` dejaba a TODAS las
	sesiones del IDE con "Session terminated" hasta reiniciar la app, porque el
	proxy abría una única sesión al arrancar y no sabía reconectar."""
	from red_pill.mcp_proxy import _call_backend

	intentos = _parchea_backend(monkeypatch, fallos=1)

	resultado = asyncio.run(_call_backend("/tmp/x.sock", "opencode", None, lambda s: s.ping()))

	assert resultado == "pong"
	assert intentos["n"] == 2, "debe reintentar una vez contra el backend nuevo"


def test_call_backend_sin_fallos_usa_un_solo_intento(monkeypatch):
	from red_pill.mcp_proxy import _call_backend

	intentos = _parchea_backend(monkeypatch)
	assert asyncio.run(_call_backend("/tmp/x.sock", "opencode", None, lambda s: s.ping())) == "pong"
	assert intentos["n"] == 1


def test_call_backend_no_reintenta_errores_de_herramienta(monkeypatch):
	"""Un tool que falla no es un transporte caído: reintentarlo duplicaría
	efectos y perdería el mensaje original."""
	import pytest

	from red_pill.mcp_proxy import _call_backend

	intentos = _parchea_backend(monkeypatch, fallos=99, exc=ValueError("tool error"))

	with pytest.raises(ValueError):
		asyncio.run(_call_backend("/tmp/x.sock", "opencode", None, lambda s: s.ping()))
	assert intentos["n"] == 1


def test_backend_stateless():
	"""El backend no guarda sesión por conexión: si guardara, reiniciarlo
	orfanizaría a todos los clientes vivos."""
	import inspect

	from red_pill import mcp_backend

	fuente = inspect.getsource(mcp_backend.build_app)
	assert "stateless=True" in fuente


@pytest.mark.skipif(
	os.getenv("REDPILL_MCP_SELFHEAL_E2E") != "1",
	reason="E2E real (backend + proxy en subproceso); activar con REDPILL_MCP_SELFHEAL_E2E=1",
)
def test_proxy_sobrevive_al_reinicio_del_backend(tmp_path):
	"""Incidente 2026-10-27, de punta a punta: matar el backend y revivirlo no
	debe dejar al IDE sin tools. Backend propio en socket temporal — nunca el
	servicio vivo."""
	import asyncio

	from mcp import ClientSession, StdioServerParameters
	from mcp.client.stdio import stdio_client

	py = str(REPO_ROOT / ".venv" / "bin" / "python")
	sock = str(tmp_path / "e2e.sock")
	env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src"), "REDPILL_HARNESS": "opencode"}

	async def _arranca():
		proc = await asyncio.create_subprocess_exec(
			py, "-m", "red_pill.mcp_backend", "--socket", sock,
			stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, env=env,
		)
		# Esperar a que ACEPTE conexiones, no sólo a que exista el fichero: tras un
		# kill el socket viejo sigue en disco y "existe" sin escuchar a nadie.
		for _ in range(150):
			try:
				reader, writer = await asyncio.open_unix_connection(sock)
				writer.close()
				await writer.wait_closed()
				return proc
			except (FileNotFoundError, ConnectionRefusedError):
				await asyncio.sleep(0.1)
		raise RuntimeError("el backend no arrancó")

	async def _run():
		backend = await _arranca()
		params = StdioServerParameters(
			command=py, args=["-m", "red_pill.mcp_proxy", "--socket", sock, "--harness", "opencode"], env=env
		)
		try:
			async with stdio_client(params) as (r, w):
				async with ClientSession(r, w) as session:
					await session.initialize()
					antes = await session.list_tools()
					backend.kill()
					await backend.wait()
					backend = await _arranca()
					despues = await session.list_tools()
					return len(antes.tools), len(despues.tools)
		finally:
			if backend.returncode is None:
				backend.kill()
				await backend.wait()

	antes, despues = asyncio.run(_run())
	assert antes > 0 and despues == antes
