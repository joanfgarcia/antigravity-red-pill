import hmac
import json
import logging
import os
import signal
import socket
import subprocess
import sys
from typing import Any, Optional

from fastembed import TextEmbedding

import red_pill.config as cfg

logger = logging.getLogger("memory_daemon")
SOCKET_PATH = cfg.DAEMON_SOCKET_PATH


class MemoryDaemon:
	"""Sidecar for semantic memory embedding."""

	def __init__(self) -> None:
		self.encoder: Optional[TextEmbedding] = None
		self.running = True
		self.server: Optional[socket.socket] = None

	def _check_encryption(self) -> None:
		"""
		SEC-001 / CERT-COND-001: Surface disk encryption check at startup.
		Warns the user if the storage directory is not on an encrypted volume (LUKS/dm-crypt).
		"""
		if sys.platform != "linux":
			return

		try:
			# SEC-001: Check for system tools before proceeding
			import shutil

			if not shutil.which("findmnt") or not shutil.which("lsblk"):
				logger.debug("SEC-001: findmnt or lsblk not found. Skipping disk encryption check.")
				return

			# Identify the block device for IA_DIR/storage
			storage_path = os.path.join(cfg.IA_DIR, "storage")

			if not os.path.exists(storage_path):
				os.makedirs(storage_path, exist_ok=True)

			# Use findmnt to get the source device and lsblk to check for 'crypt' type
			find_dev = subprocess.run(["findmnt", "-nvo", "SOURCE", "-T", storage_path], capture_output=True, text=True, check=False)
			device = find_dev.stdout.strip()

			if device:
				check_crypt = subprocess.run(["lsblk", "-no", "TYPE", device], capture_output=True, text=True, check=False)
				if "crypt" in check_crypt.stdout:
					logger.info(f"SEC-001: Disk encryption (LUKS/dm-crypt) detected on {device}.")
				else:
					logger.warning(
						f"!!! SECURITY WARNING (SEC-001) !!!: The volume {device} storing Red Pill engrams "
						"does NOT appear to be encrypted. Your data is at risk if the host is compromised."
					)

		except Exception as e:
			logger.debug(f"Failed to perform encryption check: {e}")

	def _load_model(self) -> None:
		if self.encoder is None:
			import shutil

			# B760 Asymmetric Priority: ROCm (iGPU) > CUDA (dGPU) > OpenVINO (NPU) > CPU
			# We prefer the iGPU for background embeddings to keep the dGPU free for reasoning.
			providers = ["CPUExecutionProvider"]

			has_amdgpu = False
			for i in range(5):
				if os.path.exists(f"/sys/class/drm/card{i}/device/driver/module/name"):
					with open(f"/sys/class/drm/card{i}/device/driver/module/name", "r") as f:
						if "amdgpu" in f.read():
							has_amdgpu = True
							break

			if has_amdgpu:
				providers = ["ROCmExecutionProvider", "CPUExecutionProvider"]
			elif shutil.which("nvidia-smi"):
				providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]

			# Add OpenVINO if NPU is present
			if os.path.exists("/sys/class/accel/accel0"):
				providers.insert(0, "OpenVINOExecutionProvider")

			logger.info(f"Loading embedding model {cfg.EMBEDDING_MODEL} with providers: {providers}")
			try:
				self.encoder = TextEmbedding(model_name=cfg.EMBEDDING_MODEL, providers=providers)
			except Exception as e:
				logger.warning(f"Hardware-accelerated embedding failed ({e}). Falling back to CPU only.")
				self.encoder = TextEmbedding(model_name=cfg.EMBEDDING_MODEL, providers=["CPUExecutionProvider"])

	def start(self) -> None:
		self._check_encryption()
		if os.path.exists(SOCKET_PATH):
			os.remove(SOCKET_PATH)

		self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		self.server.bind(SOCKET_PATH)
		os.chmod(SOCKET_PATH, 0o600)
		self.server.listen(5)

		try:
			self._load_model()
			# Sovereign Pulse Integration (v6.0)
			from red_pill.memory import MemoryManager
			from red_pill.soul import SoulManager
			from red_pill.heartbeat import LazarusPulse

			self.memory_mgr = MemoryManager()
			self.soul_mgr = SoulManager()
			self.pulse = LazarusPulse(self.memory_mgr, self.soul_mgr)
			self.pulse.start()
		except Exception as e:
			logger.error(f"Daemon startup failed (Model/Pulse): {e}")
			self.stop()

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
		"""Handles a single client connection (Framing + Auth + Execution)."""
		try:
			# 1. Read Header (4 bytes)
			header = conn.recv(4)
			if not header:
				return
			payload_len = int.from_bytes(header, byteorder="big")

			# 2. Read Full Payload
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

				# SEC-002 & SEC-004: Shared Secret Auth (Hardened)
				auth_key = str(cfg.SIDECAR_AUTH_KEY or "").strip()
				provided_key = str(request.get("api_key") or "").strip()

				if not auth_key or not provided_key or not hmac.compare_digest(provided_key, auth_key):
					response = {"status": "error", "message": "Unauthorized (B760 Handshake failed)"}
				else:
					text = request.get("text")
					if text and self.encoder:
						vector = list(self.encoder.embed([text]))[0].tolist()
						response = {"status": "ok", "vector": vector}
					elif request.get("command") == "ping":
						response = {"status": "ok", "message": "pong"}
					else:
						response = {"status": "error", "message": "Missing input"}
			except Exception as e:
				response = {"status": "error", "message": str(e)}

			# 3. Send Response with Header
			resp_payload = json.dumps(response).encode("utf-8")
			resp_header = len(resp_payload).to_bytes(4, byteorder="big")
			conn.sendall(resp_header + resp_payload)
		except Exception as e:
			logger.error(f"Connection handling failed: {e}")

	def stop(self, *args: Any) -> None:
		if not self.running:
			return
		self.running = False
		# Stop Autonomous Pulse
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


if __name__ == "__main__":
	daemon = MemoryDaemon()
	signal.signal(signal.SIGINT, daemon.stop)
	signal.signal(signal.SIGTERM, daemon.stop)
	daemon.start()
