"""runtime_server — servidor dedicado por runtime para perfiles no-python (RFC-HARNESS-003).

El daemon clásico (llama-cpp-python) solo puede servir modelos del runtime
stock. Los perfiles anclados a un runtime no-python (p.ej. el fork PrismML con
ternarios PTQ1_0/PQ2_0) se sirven con un `llama-server` dedicado:

	with RuntimeServer("bonsai_2_27b") as srv:
		resp = srv.chat([{"role": "user", "content": "hola"}])

Garantías:
- Gate `RuntimeRegistry.require()`: runtime declarado y no disponible → error
limpio con motivo (jamás fallback silencioso a stock).
- Health real (/health) antes de devolver el control; si el proceso muere,
el error incluye la cola del log del servidor.
- `stop()`/context manager abaten el proceso siempre (unload de VRAM).
"""

from __future__ import annotations

import json
import logging
import os
import signal
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


def _servers_state_dir() -> Path:
	path = get_data_dir() / "runtime_servers"
	path.mkdir(parents=True, exist_ok=True)
	return path


def _pid_alive(pid: int) -> bool:
	try:
		os.kill(pid, 0)
		return True
	except OSError:
		return False


def running_servers() -> List[Dict[str, Any]]:
	"""Servidores dedicados vivos según el registro de estado; limpia huérfanos."""
	running: List[Dict[str, Any]] = []
	for state in sorted(_servers_state_dir().glob("*.json")):
		try:
			info = json.loads(state.read_text(encoding="utf-8"))
		except Exception:
			state.unlink(missing_ok=True)
			continue
		pid = int(info.get("pid") or 0)
		if pid and _pid_alive(pid):
			info["_state_path"] = str(state)
			running.append(info)
		else:
			state.unlink(missing_ok=True)
	return running


def stop_dedicated_servers(profile_name: Optional[str] = None, timeout: float = 10.0) -> int:
	"""Abate servidores dedicados (todos o uno) — swap del daemon (RFC-HARNESS-003).

	Espera a que mueran: la VRAM debe estar liberada de verdad antes de que el
	caller re-mida/re-evalúe el tier. Devuelve cuántos paró.
	"""
	stopped = 0
	for info in running_servers():
		if profile_name and info.get("profile") != profile_name:
			continue
		pid = int(info.get("pid") or 0)
		if pid:
			try:
				os.kill(pid, signal.SIGTERM)
			except OSError:
				pass
			deadline = time.time() + timeout
			while time.time() < deadline and _pid_alive(pid):
				time.sleep(0.25)
			if _pid_alive(pid):
				try:
					os.kill(pid, signal.SIGKILL)
				except OSError:
					pass
		state_path = info.get("_state_path")
		if state_path:
			try:
				Path(state_path).unlink(missing_ok=True)
			except OSError:
				pass
		stopped += 1
	return stopped


class RuntimeServer:
	def __init__(
		self,
		profile_name: str,
		*,
		ctx: Optional[int] = None,
		kv_type: Optional[str] = None,
		variant: Optional[str] = None,
		port: Optional[int] = None,
		extra_args: Optional[List[str]] = None,
		host: str = "127.0.0.1",
		startup_timeout: float = 180.0,
		unload_daemon: bool = False,
		vram_margin_mb: int = 1500,
	):
		self.profile_name = profile_name
		self.ctx = ctx
		self.kv_type = kv_type
		self.variant = variant
		self.port = port
		self.extra_args = list(extra_args or [])
		self.host = host
		self.startup_timeout = startup_timeout
		self.unload_daemon = unload_daemon
		self.vram_margin_mb = vram_margin_mb
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
			runtime = RuntimeRegistry.require(str(runtime_id), variant=self.variant)
		else:
			runtime = RuntimeRegistry.for_profile(profile, variant=self.variant)
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
		# Tope duro del thinking declarado por el perfil (no toca el contexto:
		# acota la traza de razonamiento; la respuesta conserva su margen).
		reasoning_budget = (resolved.get("profile") or {}).get("reasoning_budget")
		if reasoning_budget:
			cmd += ["--reasoning-budget", str(int(reasoning_budget))]
		cmd += self.extra_args
		return cmd

	def start(self) -> "RuntimeServer":
		"""Arranca el servidor y espera health. Idempotente si ya corre."""
		if self.is_running():
			return self
		resolved = self._resolve()
		plan = self._plan_kv()
		if plan and not plan.get("fits") and self.unload_daemon:
			logger.info(f"[RUNTIME_SERVER] ningún KV cabe ({plan.get('free_mb')} MB libres): pidiendo unload al daemon.")
			self._request_daemon_unload()
			plan = self._plan_kv()
		if plan:
			if not plan.get("fits"):
				raise RuntimeServerError(
					f"VRAM insuficiente para '{self.profile_name}': ningún KV cabe a ctx={plan['ctx']} "
					f"con {plan['free_mb']} MB libres (ctx menor, liberar VRAM o unload_daemon)"
				)
			if self.ctx is None:
				self.ctx = plan["ctx"]
			if self.kv_type is None:
				self.kv_type = plan["kv_type"]
				if plan["degraded"]:
					logger.info(
						f"[RUNTIME_SERVER] KV degradada a {plan['kv_type']} para conservar ctx={plan['ctx']} "
						f"({plan['required_mb']} ≤ {plan['free_mb']} MB)"
					)
			self._ensure_vram(resolved["model_path"], required_mb=plan["required_mb"])
		else:
			self._ensure_vram(resolved["model_path"])
		if not self.port:
			self.port = _free_port(self.host)
		cmd = self._build_command(resolved)
		log_dir = get_data_dir() / "runtime_servers"
		log_dir.mkdir(parents=True, exist_ok=True)
		self._log_path = log_dir / f"{self.profile_name}.log"
		logger.info(f"[RUNTIME_SERVER] arrancando {self.profile_name}: {' '.join(cmd)}")
		rt_env = {str(k): str(v) for k, v in (resolved["runtime"].get("env") or {}).items()}
		env = {**os.environ, **rt_env}
		with open(self._log_path, "a", encoding="utf-8") as logf:
			variant = resolved["runtime"].get("variant")
			head = resolved["runtime"].get("id", "stock") + (f" [{variant}]" if variant else "")
			logf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} | {self.profile_name} | {head} =====\n")
			logf.flush()
			self._proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True, env=env)
		try:
			self.wait_ready(self.startup_timeout)
		except Exception:
			self.stop()
			raise
		self._write_state(resolved)
		return self

	def _plan_kv(self) -> dict:
		"""Plan de KV por calidad del perfil (RFC-HARNESS-003 §2.7).

		{} si el perfil no declara `kv_cache`/`vram_footprint` (el caller cae al
		kv_type explícito o a la heurística de tamaño + margen).
		"""
		try:
			return ModelRegistry.plan_kv_cache(self.profile_name, ctx=self.ctx)
		except Exception as e:
			logger.debug(f"[RUNTIME_SERVER] plan de KV no disponible: {e}")
			return {}

	def _ensure_vram(self, model_path: str, required_mb: Optional[int] = None) -> None:
		"""Gate de VRAM (RFC-HARNESS-003 §4.2): swap o defer — NUNCA degradar.

		Decisión del operador (2026-10-08): la degradación CPU/parcial queda
		descartada para modelos que caben en VRAM (tiempos inaceptables). Si la
		VRAM está ocupada: `unload_daemon=True` pide evict al proxy dual-bind y
		reintenta; si aun así no cabe, falla limpio (el caller puede diferir).
		`required_mb` (del plan de KV §2.7) manda si se aporta; si no, heurística
		de tamaño de fichero + margen.
		"""
		try:
			from red_pill.core.vram_probe import VramProbe
		except Exception:
			return  # sin probe no hay gate (no bloqueamos por un import)
		if required_mb is None:
			required_mb = max(1024, int(os.path.getsize(model_path) / (1024 * 1024)) + self.vram_margin_mb)
		free_mb = VramProbe.get_free_mb()
		if free_mb >= required_mb:
			return
		if self.unload_daemon:
			logger.info(f"[RUNTIME_SERVER] VRAM insuficiente ({free_mb}MB < {required_mb}MB): pidiendo unload al daemon.")
			self._request_daemon_unload()
			free_mb = VramProbe.get_free_mb()
		if free_mb < required_mb:
			hint = "" if self.unload_daemon else " (activa unload_daemon=True para swap con el daemon)"
			raise RuntimeServerError(
				f"VRAM insuficiente para '{self.profile_name}': {free_mb} MB libres < {required_mb} MB requeridos{hint}"
			)

	def _request_daemon_unload(self) -> bool:
		"""Evict del modelo residente vía proxy dual-bind (/v1/unload, patrón script_job).

		Sin degradación: el daemon recarga bajo demanda después. Proxy
		inalcanzable o fallo → False (el gate decide con la medida fresca).
		"""
		try:
			import red_pill.config as cfg

			base = str(getattr(cfg, "DUAL_BIND_PROXY_URL", "") or "")
			if not base:
				return False
			req = urllib.request.Request(f"{base.rstrip('/')}/v1/unload", method="POST")
			with urllib.request.urlopen(req, timeout=5) as resp:
				if resp.status == 200:
					time.sleep(2.0)  # el driver CUDA no devuelve la memoria al instante
					return True
		except Exception as e:
			logger.debug(f"[RUNTIME_SERVER] unload del daemon no disponible: {e}")
		return False

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
		if self._log_path is None:
			return "(log no disponible)"
		try:
			content = self._log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
			return "\n".join(content[-lines:]) if content else "(sin log)"
		except Exception:
			return "(log no disponible)"

	def _write_state(self, resolved: Dict[str, Any]) -> None:
		"""Registra el servidor vivo (pid/puerto/ctx) para descubrimiento y swap."""
		try:
			state = {
				"profile": self.profile_name,
				"pid": self._proc.pid if self._proc else None,
				"port": self.port,
				"ctx": self.ctx,
				"kv_type": self.kv_type,
				"runtime": (resolved.get("runtime") or {}).get("id"),
				"variant": (resolved.get("runtime") or {}).get("variant"),
				"started_at": time.time(),
				"log": str(self._log_path) if self._log_path else None,
			}
			_servers_state_dir().joinpath(f"{self.profile_name}.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
		except Exception as e:
			logger.warning(f"[RUNTIME_SERVER] no se pudo escribir el estado: {e}")

	def stop(self, timeout: float = 15.0) -> None:
		"""Abate el servidor (terminate → kill) — unload de VRAM garantizado."""
		proc = self._proc
		if proc is not None:
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
		try:
			(get_data_dir() / "runtime_servers" / f"{self.profile_name}.json").unlink(missing_ok=True)
		except OSError:
			pass

	def chat(
		self,
		messages: List[Dict[str, Any]],
		*,
		max_tokens: Optional[int] = None,
		temperature: Optional[float] = None,
		top_p: Optional[float] = None,
		top_k: Optional[int] = None,
		min_p: Optional[float] = None,
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
		if top_k is not None:
			body["top_k"] = top_k
		if min_p is not None:
			body["min_p"] = min_p
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
				payload = json.loads(resp.read().decode("utf-8"))
				if not isinstance(payload, dict):
					raise RuntimeServerError("respuesta no-dict del servidor dedicado")
				return payload
		except urllib.error.HTTPError as e:
			detail = e.read().decode("utf-8", errors="replace")[:500]
			raise RuntimeServerError(f"HTTP {e.code} del servidor: {detail}") from e

	def __enter__(self) -> "RuntimeServer":
		return self.start()

	def __exit__(self, *exc: Any) -> None:
		self.stop()
