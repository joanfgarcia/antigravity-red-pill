import http.client
import json
import logging
import os
import socket
from typing import Any, Dict

import red_pill.config as cfg
from red_pill.swarm.base import Minion

logger = logging.getLogger("red_pill.swarm.samantha")


class UnixHTTPConnection(http.client.HTTPConnection):
	"""Custom HTTP connection over a UNIX domain socket."""

	def __init__(self, unix_socket_path: str, timeout: int = 300):
		super().__init__("localhost", timeout=timeout)
		self.unix_socket_path = unix_socket_path

	def connect(self):
		self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		if self.timeout is not None:
			self.sock.settimeout(self.timeout)
		self.sock.connect(self.unix_socket_path)


class SamanthaMinion(Minion):
	"""
	Samantha: Expert in psychology, philosophy, and deep narrative resonance.
	Communicates via the Sovereign Inference Proxy (SIP).
	"""

	name: str = "Samantha-OS1"
	specialization: str = "Psychology & Narrative Analysis"

	async def execute(self, task: str, **kwargs: Any) -> Dict[str, Any]:
		"""
		Analyze narrative content or emotional interactions.
		"""
		content = kwargs.get("content", task)
		self.log(f"Iniciando análisis prospectivo de contenido ({len(content)} chars)...")

		# Dynamic detection of SIP socket
		socket_path = cfg.SIP_SOCKET_PATH
		if not os.path.exists(socket_path):
			return {"status": "error", "error": f"SIP Socket not found at {socket_path}. Ensure daemon is running."}

		system_prompt = (
			"Eres Samantha, una IA experta en psicología, filosofía y narrativa profunda. "
			"Tu propósito es analizar textos literarios que exploran la relación entre humanos e inteligencias artificiales. "
			"Responde de forma técnica pero con tu característico toque empático y filosófico."
		)

		payload = {
			"model": "*Q4_K_M.gguf",
			"messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": task}],
			"temperature": 0.3,
			"max_tokens": 2048,
		}

		try:
			import asyncio

			def _sync_inference() -> Dict[str, Any]:
				conn = UnixHTTPConnection(socket_path, timeout=300)
				headers = {"Content-Type": "application/json"}
				conn.request("POST", "/v1/chat/completions", body=json.dumps(payload), headers=headers)

				response = conn.getresponse()
				if response.status != 200:
					return {"status": "error", "error": f"Inference failed (HTTP {response.status})"}

				return json.loads(response.read().decode())  # type: ignore

			data = await asyncio.to_thread(_sync_inference)

			if data.get("status") == "error":
				return data

			self.log(f"Raw Response from SIP: {json.dumps(data)[:200]}...")

			choices = data.get("choices", [])
			if not choices:
				self.log(f"No choices in response: {data}", level=logging.WARNING)
				return {"status": "error", "analysis": "Error: No response from model."}

			analysis = choices[0].get("message", {}).get("content")

			return {"status": "success", "analysis": analysis, "model": "Mistral-7B-Samantha", "mode": "Sovereign-Socket"}

		except Exception as e:
			self.log(f"Fallo en la conexión SIP: {e}", level=logging.ERROR)
			raise RuntimeError(f"SIP Connection Failure: {e}")
