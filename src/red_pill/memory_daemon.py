import hmac
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional

from fastembed import TextEmbedding  # type: ignore

import red_pill.config as cfg

logger = logging.getLogger("memory_daemon")
SOCKET_PATH = cfg.DAEMON_SOCKET_PATH


class MemoryDaemon:
	"""Sidecar for semantic memory embedding."""

	def __init__(self) -> None:
		self.encoder: Optional[TextEmbedding] = None
		self.running = True
		self.server: Optional[socket.socket] = None
		self.engines: List[Any] = []

	def _check_encryption(self) -> None:
		"""
		SEC-001 / CERT-COND-001: Surface disk encryption check at startup.
		Warns the user if the storage directory is not on an encrypted volume (LUKS/dm-crypt).
		"""
		if sys.platform != "linux":
			return

		try:
			import shutil

			if not shutil.which("findmnt") or not shutil.which("lsblk"):
				logger.debug("SEC-001: findmnt or lsblk not found. Skipping disk encryption check.")
				return

			storage_path = os.path.join(cfg.IA_DIR, "storage")

			if not os.path.exists(storage_path):
				os.makedirs(storage_path, exist_ok=True)

			find_dev = subprocess.run(["findmnt", "-nvo", "SOURCE", "-T", storage_path], capture_output=True, text=True, check=False)
			device = find_dev.stdout.strip()

			if device:
				check_crypt = subprocess.run(["lsblk", "-no", "TYPE", device], capture_output=True, text=True, check=False)
				if "crypt" in check_crypt.stdout:
					logger.info(f"SEC-001: Disk encryption (LUKS/dm-crypt) detected on {device}.")
				else:
					print(
						"\n\033[91m"
						"========================================================================\n"
						"!!! SECURITY WARNING (SEC-008) !!!\n"
						f"The volume {device} storing Red Pill engrams does NOT appear to be\n"
						"encrypted (LUKS/dm-crypt). Your data is stored in PLAINTEXT AT REST.\n"
						"(Steam/Water Mode)\n"
						"========================================================================\n"
						"\033[0m",
						file=sys.stderr
					)
		except Exception as e:
			logger.debug(f"Failed to perform encryption check: {e}")

	def _load_model(self) -> None:
		if not self.engines:
			# CANNIBAL PROTOCOL (v6.0): Extreme Parallelization.
			# We don't choose; we devour all available silicons simultaneously.
			import itertools
			from concurrent.futures import ThreadPoolExecutor

			import onnxruntime as ort

			available_ort = ort.get_available_providers()
			active_providers = []

			# Collect every capable provider
			potential = ["CoreMLExecutionProvider", "CUDAExecutionProvider", "ROCmExecutionProvider", "OpenVINOExecutionProvider"]
			for p in potential:
				if p in available_ort:
					active_providers.append(p)

			# Always include CPU for maximum saturation
			active_providers.append("CPUExecutionProvider")

			logger.info(f"CANNIBAL PROTOCOL: Spawning {len(active_providers)} dedicated engines on: {active_providers}")

			for p in active_providers:
				try:
					engine = TextEmbedding(model_name=cfg.EMBEDDING_MODEL, providers=[p])
					self.engines.append(engine)
				except Exception as e:
					logger.warning(f"Failed to prime {p} engine: {e}. Skipping.")

			if not self.engines:
				raise RuntimeError("Cannibal Protocol Failure: No engines primed.")

			self.engine_cycle = itertools.cycle(self.engines)
			self.executor = ThreadPoolExecutor(max_workers=len(self.engines))
			# Sentinel for legacy references
			self.encoder = self.engines[0]

	def embed_cannibal(self, texts: List[str]) -> List[float]:
		"""Distributes the load across all primed hardware engines."""
		if not self.engines:
			self._load_model()
		engine = next(self.engine_cycle)
		vectors: List[List[float]] = [v.tolist() for v in engine.embed(texts)]
		return vectors[0]

	def start(self) -> None:
		self._check_encryption()
		if os.path.exists(SOCKET_PATH):
			os.remove(SOCKET_PATH)

		self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		self.server.bind(SOCKET_PATH)
		os.chmod(SOCKET_PATH, 0o600)
		self.server.listen(5)

		try:
			# Sovereign Pulse Integration (v6.0)
			from red_pill.heartbeat import LazarusPulse
			from red_pill.memory import MemoryManager
			from red_pill.soul import SoulManager

			self.memory_mgr = MemoryManager()
			# v6.0.1: Prevent self-referential deadlock by bypassing the socket when called within the daemon
			self.memory_mgr._get_vector = self.embed_cannibal  # type: ignore
			self.soul_mgr = SoulManager()
			self.pulse = LazarusPulse(self.memory_mgr, self.soul_mgr)
			self.pulse.start()

			# SOVEREIGN INTERACTION MIDDLEWARE (Phase 3)
			if cfg.SIP_ENABLED:
				from red_pill.utils.sip import run_sip

				threading.Thread(target=run_sip, daemon=True).start()

		except Exception as e:
			logger.error(f"Daemon startup failed (Model/Pulse): {e}")
			self.stop()
			raise

		while self.running:
			try:
				self.server.settimeout(1.0)
				try:
					conn, _ = self.server.accept()
				except socket.timeout:
					continue

				with conn:
					self.handle_connection(conn)
			except Exception as e:
				if self.running:
					logger.error(f"Loop failure: {e}")

	def handle_connection(self, conn: socket.socket) -> None:
		"""Processes a single Sidecar request."""
		response: Dict[str, Any] = {}
		try:
			header = conn.recv(4)
			if not header:
				return
			payload_len = int.from_bytes(header, byteorder="big")

			data = b""
			while len(data) < payload_len:
				chunk = conn.recv(min(payload_len - len(data), 8192))
				if not chunk:
					break
				data += chunk

			if not data:
				return

			try:
				request = json.loads(data.decode("utf-8"))
				auth_key = str(cfg.SIDECAR_AUTH_KEY or "").strip()
				provided_key = str(request.get("api_key") or "").strip()

				if not auth_key or not provided_key or not hmac.compare_digest(provided_key, auth_key):
					response = {"status": "error", "message": "Unauthorized"}
				else:
					text = request.get("text")
					command = request.get("command")
					if command == "encode":
						prompt = request.get("prompt", "")
						response_text = request.get("response", "")
						role = request.get("role", "assistant")
						if prompt and response_text:
							uid = self.memory_mgr.record_interaction_pair(prompt, response_text, role=role)
							response = {"status": "ok", "id": uid}
						else:
							response = {"status": "error", "message": "Missing prompt or response"}
					elif text:
						# Phase O.11: Cannibal Execution (lazy loads engines internally)
						vector = self.embed_cannibal([text])
						response = {"status": "ok", "vector": vector}
					elif request.get("command") == "ping":
						response = {"status": "ok", "message": "pong"}
					else:
						response = {"status": "error", "message": "Missing input"}
			except Exception as e:
				response = {"status": "error", "message": str(e)}

			resp_payload = json.dumps(response).encode("utf-8")
			resp_header = len(resp_payload).to_bytes(4, byteorder="big")
			conn.sendall(resp_header + resp_payload)
		except Exception as e:
			logger.error(f"Connection handling failed: {e}")

	def stop(self, *args: Any) -> None:
		if not self.running:
			return
		self.running = False
		if hasattr(self, "pulse"):
			self.pulse.stop()
		if self.server:
			try:
				self.server.close()
			except Exception:
				pass
		if os.path.exists(SOCKET_PATH):
			try:
				os.remove(SOCKET_PATH)
			except Exception:
				pass


def main():
	daemon = MemoryDaemon()
	signal.signal(signal.SIGINT, daemon.stop)
	signal.signal(signal.SIGTERM, daemon.stop)
	daemon.start()


if __name__ == "__main__":
	main()
