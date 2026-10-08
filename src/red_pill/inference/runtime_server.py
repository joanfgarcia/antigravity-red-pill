"""runtime_server — servidor dedicado por runtime para perfiles no-python (RFC-HARNESS-003).

El daemon clásico (llama-cpp-python) solo puede servir modelos del runtime
stock. Los perfiles anclados a un runtime no-python (p.ej. el fork PrismML con
ternarios PTQ1_0/PQ2_0) se sirven con un `llama-server` dedicado:

	with RuntimeServer("bonsai_2_27b") as srv:
		resp = srv.chat([{"role": "user", "content": "hola"}])

Garantías:
- Gate `RuntimeRegistry.require()`: runtime declarado y no disponible → error
  limpio con motivo (jamás fallback silencioso a stock).
- Health real (/health) antes de devolver el control; si el proceso muere, el
  error incluye la cola del log del servidor.
- `stop()`/context manager abaten el proceso siempre (unload de VRAM).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from red_pill.core.model_registry import ModelRegistry
from red_pill.core.paths import get_data_dir
from red_pill.core.runtime_registry import RuntimeRegistry, RuntimeUnavailableError

logger = logging.getLogger(__name__)


class RuntimeServerError(RuntimeError):
	"""Fallo operativo del servidor dedicado (arranque/health/HTTP)."""


def _free_port(host: str = "127.0.0.1") -> int:
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
		s.bind((host, 0))
		return int(s.getsockname()[1])


class RuntimeServer:
	def __init__(
		self,
		profile_name: str,
		*,
		ctx: Optional[int] = None,
		kv_type: Optional[str] = None,
		port: Optional[int] = None,
		extra_args: Optional[List[str]] = None,
		host: str = "127.0.0.1",
		startup_timeout: float = 180.0,
	):
		self.profile_name = profile_name
		self.ctx = ctx
		self.kv_type = kv_type
		self.port = port
		self.extra_args = list(extra_args or [])
		self.host = host
		self.startup_timeout = startup_timeout
		self._proc: Optional[subprocess.Popen] = None
		self._log_path: Optional[Path] = None

	@property
	def base_url(self) -> str:
		return f"http://{self.host}:{self.port}"

	def is_running(self) -> bool:
		return self._proc is not None and self._proc.poll() is None

	def _resolve(self) -> Dict[str, Any]:
		"""Perfil + runtime resueltos, con gate fail-clean (RFC-HARNESS-003)."""
		profile = ModelRegistry.get_profile(self.profile_name)
		if not profile:
			raise RuntimeServerError(f"perfil '{self.profile_name}' no existe en model_profiles.yaml")
		runtime_id = profile.get("runtime")
		if runtime_id:
			runtime = RuntimeRegistry.require(str(runtime_id))
		else:
			runtime = RuntimeRegistry.for_profile(profile)
		server_binary = runtime.get("server") or runtime.get("binary")
		if not server_binary or not os.access(server_binary, os.X_OK):
			raise RuntimeUnavailableError(
				f"[RUNTIME] '{runtime_id or RuntimeRegistry.default_id()}' sin binario server ejecutable ({server_binary})"
			)
		model_path = str(Path(os.path.expanduser(str(profile.get("model_path", "")))))
		if not model_path or not os.path.isfile(model_path):
			raise RuntimeServerError(f"model_path inexistente para '{self.profile_name}': {model_path}")
		return {"profile": profile, "runtime": runtime, "server_binary": server_binary, "model_path": model_path}

	def _build_command(self, resolved: Dict[str, Any]) -> List[str]:
		"""Argv del llama-server: tiers de VRAM del perfil + quirks del runtime."""
		hw = ModelRegistry.get_resolved_hardware_affinity(self.profile_name)
		n_ctx = int(self.ctx or hw.get("n_ctx") or (resolved["profile"].get("hardware_affinity") or {}).get("n_ctx") or 8192)
		ngl = int(hw.get("n_gpu_layers", -1))
		cmd = [
			resolved["server_binary"],
			"-m", resolved["model_path"],
			"-ngl", str(ngl),
			"-fa", "on",
			"-c", str(n_ctx),
			"-np", "1",  # 8 GB VRAM: un slot (RFC-HARNESS-003 quirks)
			"--host", self.host,
			"--port", str(self.port),
		]
		if self.kv_type:
			cmd += ["-ctk", self.kv_type, "-ctv", self.kv_type]
		cmd += self.extra_args
		return cmd

	def start(self) -> "RuntimeServer":
		"""Arranca el servidor y espera health. Idempotente si ya corre."""
		if self.is_running():
			return self
		resolved = self._resolve()
		if not self.port:
			self.port = _free_port(self.host)
		cmd = self._build_command(resolved)
		log_dir = get_data_dir() / "runtime_servers"
		log_dir.mkdir(parents=True, exist_ok=True)
		self._log_path = log_dir / f"{self.profile_name}.log"
		logger.info(f"[RUNTIME_SERVER] arrancando {self.profile_name}: {' '.join(cmd)}")
		with open(self._log_path, "a", encoding="utf-8") as logf:
			logf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} | {self.profile_name} | {resolved['runtime'].get('id', 'stock')} =====\n")
			logf.flush()
			self._proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
		try:
			self.wait_ready(self.startup_timeout)
		except Exception:
			self.stop()
			raise
		return self

	def wait_ready(self, timeout: Optional[float] = None) -> None:
		"""Health real: /health == 200 o muerte del proceso (con cola del log)."""
		deadline = time.time() + (timeout or self.startup_timeout)
		while time.time() < deadline:
			if self._proc is not None and self._proc.poll() is not None:
				raise RuntimeServerError(f"el servidor murió durante el arranque (rc={self._proc.returncode}): {self._log_tail()}")
			try:
				with urllib.request.urlopen(f"{self.base_url}/health", timeout=2) as resp:
					if resp.status == 200:
						return
			except Exception:
				time.sleep(0.5)
		raise RuntimeServerError(f"timeout de arranque ({timeout or self.startup_timeout:.0f}s): {self._log_tail()}")

	def _log_tail(self, lines: int = 20) -> str:
		try:
			content = self._log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
			return "\n".join(content[-lines:]) if content else "(sin log)"
		except Exception:
			return "(log no disponible)"

	def stop(self, timeout: float = 15.0) -> None:
		"""Abate el servidor (terminate → kill) — unload de VRAM garantizado."""
		proc = self._proc
		if proc is None:
			return
		try:
			if proc.poll() is None:
				proc.terminate()
				try:
					proc.wait(timeout=timeout)
				except subprocess.TimeoutExpired:
					proc.kill()
					proc.wait(timeout=5)
		finally:
			self._proc = None

	def chat(
		self,
		messages: List[Dict[str, Any]],
		*,
		max_tokens: Optional[int] = None,
		temperature: Optional[float] = None,
		top_p: Optional[float] = None,
		chat_template_kwargs: Optional[dict] = None,
		timeout: float = 600.0,
	) -> Dict[str, Any]:
		"""POST /v1/chat/completions (no streaming) contra el servidor dedicado."""
		if not self.is_running():
			raise RuntimeServerError("servidor no está corriendo (usa start())")
		body: Dict[str, Any] = {"messages": messages, "stream": False}
		if max_tokens is not None:
			body["max_tokens"] = max_tokens
		if temperature is not None:
			body["temperature"] = temperature
		if top_p is not None:
			body["top_p"] = top_p
		if chat_template_kwargs:
			body["chat_template_kwargs"] = chat_template_kwargs
		req = urllib.request.Request(
			f"{self.base_url}/v1/chat/completions",
			data=json.dumps(body).encode("utf-8"),
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		try:
			with urllib.request.urlopen(req, timeout=timeout) as resp:
				return json.loads(resp.read().decode("utf-8"))
		except urllib.error.HTTPError as e:
			detail = e.read().decode("utf-8", errors="replace")[:500]
			raise RuntimeServerError(f"HTTP {e.code} del servidor: {detail}") from e

	def __enter__(self) -> "RuntimeServer":
		return self.start()

	def __exit__(self, *exc: Any) -> bool:
		self.stop()
		return False
