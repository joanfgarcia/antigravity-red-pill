"""Shared RedPill-Kernel MCP backend (AD-018).

One heavy process serves N stdio proxies over a Unix-domain socket using MCP
`streamable_http`. The proxy sends the harness identity in the
`X-RedPill-Proxy` header; this module publishes it in `mcp_server`'s contextvar
for the duration of each request. The kernel is imported once, here — the proxy
stays light.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

import red_pill.mcp_server as kernel
from red_pill.mcp_proxy import default_socket


def _identity_from_headers(scope: Any) -> Optional[dict]:
	try:
		raw = dict(scope.get("headers") or []).get(b"x-redpill-proxy")
	except Exception:
		return None
	if not raw:
		return None
	try:
		value = json.loads(base64.b64decode(raw))
	except Exception:
		return None
	return value if isinstance(value, dict) else None


class IdentityMiddleware:
	"""Injects the proxy identity into the kernel's contextvar per HTTP request."""

	def __init__(self, app: Callable):
		self.app = app

	async def __call__(self, scope, receive, send):
		if scope.get("type") != "http":
			await self.app(scope, receive, send)
			return
		token = kernel._shared_identity_var.set(_identity_from_headers(scope))
		try:
			await self.app(scope, receive, send)
		finally:
			kernel._shared_identity_var.reset(token)


def build_app(json_response: bool = False) -> Starlette:
	# Stateless (2026-10-27): el kernel no guarda estado por conexión — la
	# identidad viaja en cada request (`X-RedPill-Proxy`). Con sesión viva, un
	# reinicio del servicio dejaba huérfanas TODAS las sesiones de los IDEs
	# ("Session terminated") y el proxy no podía recuperarse.
	manager = StreamableHTTPSessionManager(app=kernel.server, json_response=json_response, stateless=True)

	@contextlib.asynccontextmanager
	async def lifespan(_app):
		async with manager.run():
			yield

	return Starlette(
		routes=[Mount("/mcp", app=IdentityMiddleware(manager.asgi_app))],
		lifespan=lifespan,
	)


def _chmod_socket_when_ready(path: Path, mode: int = 0o600) -> None:
	"""Uvicorn puede crear el UDS con 0666; el directorio ya es 0700, pero
	endurecemos el fichero en cuanto exista (defensa en profundidad)."""
	for _ in range(200):
		try:
			if path.exists():
				path.chmod(mode)
				return
		except OSError:
			pass
		time.sleep(0.05)


def serve(socket_path: str | None = None, json_response: bool = False) -> None:
	"""Run the shared backend on a Unix socket (blocks)."""
	sock = Path(socket_path or default_socket())
	sock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
	try:
		sock.parent.chmod(0o700)
	except OSError:
		pass
	try:
		sock.unlink()
	except FileNotFoundError:
		pass
	threading.Thread(target=_chmod_socket_when_ready, args=(sock,), daemon=True).start()
	old_umask = os.umask(0o077)
	try:
		uvicorn.run(build_app(json_response=json_response), uds=str(sock), log_level="warning")
	finally:
		os.umask(old_umask)


if __name__ == "__main__":
	import argparse

	parser = argparse.ArgumentParser(description="RedPill shared MCP backend (AD-018)")
	parser.add_argument("--socket", default=None, help="Backend UDS")
	parser.add_argument("--json-response", action="store_true", help="JSON responses instead of SSE")
	options = parser.parse_args()
	serve(socket_path=options.socket, json_response=options.json_response)
