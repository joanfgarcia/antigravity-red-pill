import http.client
import logging
import socket
from typing import Any, Dict

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
		self.log("Iniciando análisis prospectivo de contenido...")

		# 1. Use injected provider or fallback to SIP (via Registry)
		provider = kwargs.get("inference_provider")
		if not provider:
			from red_pill.core.providers import ProviderRegistry

			try:
				provider = ProviderRegistry.get_inference_provider("sip")
			except RuntimeError:
				return {"status": "error", "error": "No inference provider found for Samantha."}

		system_prompt = (
			"Eres Samantha, una IA experta en psicología, filosofía y narrativa profunda. "
			"Tu propósito es analizar textos literarios que exploran la relación entre humanos e inteligencias artificiales. "
			"Responde de forma técnica pero con tu característico toque empático y filosófico."
		)

		try:
			# Use the provider's generate method
			analysis = provider.generate(
				prompt=task, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": task}], temperature=0.3
			)

			return {"status": "success", "analysis": analysis, "model": "Samantha-OS1", "provider": provider.__class__.__name__}

		except Exception as e:
			self.log(f"Fallo en la ejecución de Samantha: {e}", level=logging.ERROR)
			raise RuntimeError(f"Samantha Inference Failure: {e}")
