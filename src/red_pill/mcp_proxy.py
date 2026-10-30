"""MCP stdio proxy for the shared RedPill-Kernel backend (AD-018).

The IDE launches this lightweight proxy as its local MCP. The proxy forwards
JSON-RPC to the single backend over a Unix socket and attaches the harness
identity (env/bridge, never the model) as a trusted header on every request.

It deliberately does NOT import `red_pill.mcp_server`: the heavy kernel loads
once in the backend, not in each tab.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path

import httpx
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from red_pill.core.paths import get_state_dir

BACKEND_URL = "http://localhost/mcp/"

logger = logging.getLogger(__name__)


def state_dir() -> Path:
	return get_state_dir()


def default_socket() -> str:
	runtime = os.getenv("XDG_RUNTIME_DIR")
	if runtime:
		return str(Path(runtime) / "red-pill" / "mcp.sock")
	return str(state_dir() / "mcp.sock")


def _instance_cwd() -> str:
	"""cwd real de ESTA instancia del proxy (el workspace que sirve su pestaña).

	opencode arranca un proxy por instancia y le fija el cwd al workspace (la app
	de escritorio hospeda varias). Es el único discriminador per-instancia
	disponible: el env NO trae el session id (config MCP estática) y `PWD` está
	rancio (heredado del lanzador). Ver D-BRIDGE / core/bridge.py.
	"""
	try:
		return os.getcwd()
	except Exception:
		return ""


def identity_payload(harness: str | None = None) -> dict:
	"""Identidad de la instancia para el backend (canal de confianza del proxy)."""
	provider = (harness or os.getenv("REDPILL_HARNESS") or "opencode").strip() or "opencode"
	originator = str(os.getenv("REDPILL_ORIGINATOR") or "").strip()
	workdir = str(os.getenv("REDPILL_WORKSPACE") or "").strip()
	project_dir = ""
	continuity = str(os.getenv("REDPILL_CONTINUITY_ID") or "").strip()
	mission = str(os.getenv("REDPILL_MISSION_ID") or "").strip()
	role = str(os.getenv("REDPILL_ROLE") or "task").strip() or "task"
	if not originator and provider in ("opencode", "claude_code"):
		# D-BRIDGE: primero la correlación por cwd (resuelve el cuerpo de ESTA
		# instancia); el fichero global es la degradación (último escritor gana).
		raw = None
		ambiguous = False
		try:
			from red_pill.core.bridge import REASON_AMBIGUOUS, resolve_body

			raw, reason = resolve_body(provider, _instance_cwd())
			ambiguous = reason == REASON_AMBIGUOUS
		except Exception:
			raw, ambiguous = None, False
		if ambiguous:
			# Dos o más sesiones vivas en este mismo cwd: la correlación no decide
			# y el global es "la última que escribió", que puede ser OTRA alma.
			# Atribuir mal hace que los avisos y los jobs aterricen en un alma
			# ajena (incidente 2026-10-28); sin cuerpo es degradación honesta
			# (fail-closed: el backend no inventa alma).
			logger.debug("[RedPill-Proxy] identidad ambigua en %s; sin cuerpo (no se usa el global)", _instance_cwd())
		elif not raw:
			try:
				raw = json.loads((state_dir() / f"{provider}_session.json").read_text(encoding="utf-8"))
			except Exception:
				raw = None
		if isinstance(raw, dict):
			bridge_provider = str(raw.get("provider") or provider)
			session_id = str(raw.get("session_id") or "")
			if session_id:
				originator = f"{bridge_provider}:{session_id}"
			workdir = workdir or str(raw.get("workdir") or "")
			project_dir = str(raw.get("project_dir") or "")
	return {
		"originator": originator,
		"workdir": workdir,
		"project_dir": project_dir,
		"harness": provider,
		"continuity_id": continuity,
		"mission_id": mission,
		"role": role,
	}


def _uds_client_factory(socket_path: str, harness: str | None):
	async def _add_identity(request: httpx.Request) -> None:
		payload = identity_payload(harness)
		raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
		request.headers["X-RedPill-Proxy"] = base64.b64encode(raw).decode()

	def factory(headers=None, timeout=None, auth=None):
		return httpx.AsyncClient(
			transport=httpx.AsyncHTTPTransport(uds=socket_path),
			base_url="http://localhost",
			headers=headers,
			timeout=timeout,
			auth=auth,
			follow_redirects=True,
			event_hooks={"request": [_add_identity]},
		)

	return factory


async def _with_backend(socket_path: str, harness: str | None, client_info, fn, *, timeout: float = 30.0):
	"""Abre una conexión nueva, ejecuta `fn(session)` y la cierra en ESTA task.

	`streamablehttp_client` monta task groups de anyio: abrir la conexión en una
	task y cerrarla en otra revienta con "Attempted to exit cancel scope in a
	different task than it was entered in". Por eso la conexión es de vida corta
	y no se reutiliza entre peticiones.

	El backend corre en modo `stateless`, así que una conexión corta no deja
	sesión colgada en el servidor: reiniciar `redpill-mcp.service` ya no orfaniza
	nada (incidente 2026-10-27).
	"""
	factory = _uds_client_factory(socket_path, harness)
	async with streamablehttp_client(BACKEND_URL, httpx_client_factory=factory, timeout=timeout) as (
		read,
		write,
		_get_session_id,
	):
		async with ClientSession(read, write, client_info=client_info) as session:
			await session.initialize()
			return await fn(session)


async def _call_backend(socket_path: str, harness: str | None, client_info, fn):
	"""`fn(session)` con UN reintento si la conexión con el backend falla."""
	for intento in (1, 2):
		try:
			return await _with_backend(socket_path, harness, client_info, fn)
		except (KeyboardInterrupt, SystemExit):
			raise
		except ValueError:
			raise  # error de herramienta: no es transporte
		except asyncio.CancelledError:
			raise
		except BaseException as exc:  # noqa: BLE001 — anyio agrupa cancelaciones
			# `streamablehttp_client` monta task groups: al morir el backend el
			# fallo llega como `BaseExceptionGroup` (que NO hereda de Exception).
			# Se normaliza a RuntimeError en el último intento: un BaseExceptionGroup
			# escapando del handler se lleva por delante el servidor stdio entero.
			if intento == 2:
				raise RuntimeError(f"backend no disponible: {exc}") from exc
			logger.warning(f"[RedPill-Proxy] backend no disponible ({exc}); reintentando")
			await asyncio.sleep(0.3)


async def _run(socket_path: str, harness: str | None) -> None:
	client_info = types.Implementation(name="RedPill-Proxy", version="0.1")
	proxy = Server("RedPill-Kernel", version="0.1")

	@proxy.list_tools()
	async def list_tools():
		return (
			await _call_backend(socket_path, harness, client_info, lambda session: session.list_tools())
		).tools

	@proxy.call_tool()
	async def call_tool(name: str, arguments: dict):
		result = await _call_backend(
			socket_path, harness, client_info, lambda session: session.call_tool(name, arguments or {})
		)
		if result.isError:
			text = "\n".join(getattr(c, "text", "") for c in result.content)
			raise ValueError(text or "tool error")
		return result.content

	@proxy.list_prompts()
	async def list_prompts():
		return []

	@proxy.list_resources()
	async def list_resources():
		return []

	async with stdio_server() as (stdin, stdout):
		await proxy.run(stdin, stdout, proxy.create_initialization_options())


def run_proxy(socket_path: str | None = None, harness: str | None = None) -> None:
	"""Entry point for `red-pill mcp proxy` (blocks until the IDE closes stdio)."""
	sock = socket_path or default_socket()
	try:
		asyncio.run(_run(sock, harness))
	except KeyboardInterrupt:
		pass


if __name__ == "__main__":
	import argparse

	parser = argparse.ArgumentParser(description="RedPill MCP stdio proxy (AD-018)")
	parser.add_argument("--socket", default=None, help="Backend UDS")
	parser.add_argument("--harness", default=None, help="opencode | claude_code | pi")
	options = parser.parse_args()
	run_proxy(options.socket, options.harness)
