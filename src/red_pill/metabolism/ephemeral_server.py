"""Local-LLM reachability probe and the ephemeral llama-server lifecycle.

Extracted from sleep.py per ADR-SLEEP-001. Manages the on-demand distillation
server (start/stop) and checks whether the sovereign inference proxy is reachable.
"""

import logging
import os
import socket
import subprocess
import urllib.parse
import urllib.request
from typing import Any, List

import red_pill.config as cfg
from red_pill.core.paths import get_daemon_persistent_dir

logger = logging.getLogger(__name__)


def _check_llm_available() -> bool:
	"""Quick reachability probe for the local distillation LLM."""
	import os

	uds_path = cfg.SIP_SOCKET_PATH
	if os.path.exists(uds_path):
		try:
			s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			s.settimeout(1.0)
			s.connect(uds_path)
			s.close()
			return True
		except OSError:
			logger.warning(f"[SLEEP ENGINE] UDS connection refused on {uds_path}. Cleaning up orphan socket file.")
			try:
				os.remove(uds_path)
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to remove orphan socket {uds_path}: {e}")

	# Fallback: probe TCP endpoint
	mlx_url = getattr(cfg, "MLX_LM_URL", "") or ""
	if mlx_url:
		try:
			parsed = urllib.parse.urlparse(mlx_url)
			host = parsed.hostname or "127.0.0.1"
			port = parsed.port or 8760
			s = socket.create_connection((host, port), timeout=1.0)
			s.close()
			return True
		except OSError:
			return False

	return False  # No endpoint configured


class EphemeralServer:
	"""
	Manages the lifecycle of the ephemeral local LLM server used during the sleep
	distillation cycle.

	Start order:
	1. Try systemd user service (Linux)
	2. Try launchctl user agent (macOS)
	3. Fall back to direct subprocess with systemd-run cgroup or nice(1).

	The object tracks which path was taken so teardown can be handled correctly.
	"""

	def __init__(self):
		self._process: Any = None  # subprocess.Popen | str | None

	@property
	def is_managed_service(self) -> bool:
		"""True when the server is controlled by systemd/launchd (not a Popen)."""
		return self._process in ("systemd_service", "launchd_service")

	def start(self, memory_manager) -> bool:
		"""
		Attempts to bring the ephemeral LLM server online.
		Returns True when the server is reachable, False on failure.
		"""
		import shutil
		import sys
		import time as _time

		from red_pill.core.notifier import SovereignNotifier

		SovereignNotifier.notify_os(
			"Bünker Cortex",
			"El Hilo de Ariadna está tejiendo...\nConsolidación de memoria iniciada.",
			icon="weather-clear-night",
		)
		SovereignNotifier.notify_bunker(memory_manager, "ariadne_thread_running", intensity=1.0, source="SLEEP_ENGINE")

		start_sh = str(get_daemon_persistent_dir() / "start.sh")
		if not os.path.exists(start_sh):
			logger.error("[EPHEMERAL SERVER] start.sh not found. Aborting.")
			SovereignNotifier.notify_bunker(memory_manager, "local_llm_offline", intensity=7.0, signal_type="pain", source="SLEEP_ENGINE")
			return False

		if shutil.which("systemctl"):
			subprocess.run(
				["systemctl", "--user", "restart", "redpill-llm.service"],
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)
			self._process = "systemd_service"
		elif shutil.which("launchctl"):
			uid = os.getuid()
			subprocess.run(
				["launchctl", "kickstart", "-k", f"gui/{uid}/com.agent.modeldaemon"],
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)
			self._process = "launchd_service"
		else:
			# Fallback: direct execution wrapped in cgroup/nice for resource safety
			cmd: List[str] = []
			if shutil.which("systemd-run"):
				cmd = ["systemd-run", "--user", "--scope", "-p", "MemoryMax=10G", "-p", "Nice=19", "-p", "IOSchedulingClass=3", start_sh]
			elif shutil.which("nice"):
				cmd = ["nice", "-n", "19"]
				if sys.platform == "darwin" and shutil.which("taskpolicy"):
					cmd += ["taskpolicy", "-c", "background"]
				cmd.append(start_sh)
			else:
				cmd = [start_sh]
			self._process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

		logger.info("[EPHEMERAL SERVER] Waiting for LLM to come online...")
		for _ in range(30):
			_time.sleep(2)
			if _check_llm_available():
				logger.info("[EPHEMERAL SERVER] LLM is ONLINE.")
				return True

		logger.error("[EPHEMERAL SERVER] LLM failed to start within 60s.")
		if not self.is_managed_service and self._process is not None:
			self._process.terminate()
		SovereignNotifier.notify_os("Bünker Cortex", "Fallo al iniciar el servidor efímero.", urgency="critical")
		SovereignNotifier.clear_bunker_signal(memory_manager, "ariadne_thread_running")
		return False

	def stop(self, memory_manager, total_processed: int) -> None:
		"""Gracefully shuts down the ephemeral server (Popen only; services self-manage)."""
		if self.is_managed_service:
			try:
				import urllib.request

				req = urllib.request.Request("http://127.0.0.1:8760/unload", method="POST")
				with urllib.request.urlopen(req, timeout=5):
					logger.info("[EPHEMERAL SERVER] Explicit model unload triggered successfully on local daemon.")
			except Exception as e:
				logger.warning(f"[EPHEMERAL SERVER] Failed to trigger explicit model unload on local daemon: {e}")
			return

		if self._process is None:
			return

		logger.info("[EPHEMERAL SERVER] Shutting down...")
		try:
			self._process.terminate()
			self._process.wait(timeout=10)
		except Exception:
			self._process.kill()

		try:
			from red_pill.core.notifier import SovereignNotifier

			SovereignNotifier.notify_os(
				"Bünker Cortex",
				f"Hilo de Ariadna finalizado.\n{total_processed} engramas consolidados en el neocórtex.",
				icon="dialog-information",
			)
		except Exception:
			pass


