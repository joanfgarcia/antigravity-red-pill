import json
import logging
import os
import signal
import socket
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

	def _load_model(self) -> None:
		if self.encoder is None:
			self.encoder = TextEmbedding(model_name=cfg.EMBEDDING_MODEL)

	def start(self) -> None:
		if os.path.exists(SOCKET_PATH):
			os.remove(SOCKET_PATH)

		self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		self.server.bind(SOCKET_PATH)
		os.chmod(SOCKET_PATH, 0o600)
		self.server.listen(5)

		try:
			self._load_model()
		except Exception as e:
			logger.error(f"Model load failed: {e}")
			self.stop()

		while self.running:
			try:
				self.server.settimeout(1.0)
				try:
					conn, _ = self.server.accept()
				except socket.timeout:
					continue

				with conn:
					# 1. Read Header (4 bytes)
					header = conn.recv(4)
					if not header:
						continue
					payload_len = int.from_bytes(header, byteorder="big")

					# 2. Read Full Payload
					data = b""
					while len(data) < payload_len:
						chunk = conn.recv(min(payload_len - len(data), 8192))
						if not chunk:
							break
						data += chunk

					if not data:
						continue

					try:
						request = json.loads(data.decode("utf-8"))

						# SEC-002: Shared Secret Auth
						if request.get("api_key") != cfg.QDRANT_API_KEY:
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
				if self.running:
					logger.error(f"Loop failure: {e}")

	def stop(self, *args: Any) -> None:
		if not self.running:
			return
		self.running = False
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
