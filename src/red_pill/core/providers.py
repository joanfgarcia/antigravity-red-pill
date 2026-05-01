from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional


class BaseTelemetryProvider(ABC):
	"""Abstract Base Class for telemetry data (Hardware, Swarm, Enterprise)."""

	@abstractmethod
	def get_stats(self) -> Dict[str, Any]:
		"""Retrieve real-time stats."""
		return {}

	@abstractmethod
	def compute_delta(self, before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
		"""Compute the cognitive or hardware impact (delta) between two states."""
		return {}

	@abstractmethod
	def log_event(self, event_type: str, data: Dict[str, Any]):
		"""Log an event for auditing or telemetry."""
		pass


class BaseInferenceProvider(ABC):
	"""Abstract Base Class for LLM inference (OpenAI, Local BitNet, etc.)."""

	@abstractmethod
	def generate(self, prompt: str, **kwargs) -> str:
		"""Generate a complete response for a prompt."""
		return ""

	@abstractmethod
	def stream(self, prompt: str, **kwargs) -> Iterator[str]:
		"""Stream response tokens for a prompt."""
		return iter([])


class ProviderRegistry:
	"""Registry to manage and discover active providers (IoC)."""

	_telemetry_provider: Optional[BaseTelemetryProvider] = None
	_inference_providers: Dict[str, BaseInferenceProvider] = {}
	_default_inference_key: Optional[str] = None

	@classmethod
	def register_telemetry_provider(cls, provider: BaseTelemetryProvider):
		cls._telemetry_provider = provider

	@classmethod
	def get_telemetry_provider(cls) -> BaseTelemetryProvider:
		if cls._telemetry_provider is None:
			# Lazy import to avoid circular dependencies
			from red_pill.telemetry import sentinel

			return sentinel
		return cls._telemetry_provider

	@classmethod
	def register_inference_provider(cls, name: str, provider: BaseInferenceProvider, default: bool = False):
		cls._inference_providers[name] = provider
		if default or cls._default_inference_key is None:
			cls._default_inference_key = name

	@classmethod
	def get_inference_provider(cls, name: Optional[str] = None) -> BaseInferenceProvider:
		key = name or cls._default_inference_key
		if not key or key not in cls._inference_providers:
			raise RuntimeError(f"No inference provider registered for key: {key}")
		return cls._inference_providers[key]

	@classmethod
	def list_inference_providers(cls) -> List[str]:
		return list(cls._inference_providers.keys())

	@classmethod
	def reset(cls):
		"""Reset the registry to its initial state (mainly for testing)."""
		cls._telemetry_provider = None
		cls._inference_providers = {}
		cls._default_inference_key = None


class OpenAIInferenceProvider(BaseInferenceProvider):
	"""Provider for OpenAI-compatible HTTP APIs."""

	def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o"):
		self.api_key = api_key
		self.base_url = base_url
		self.model = model

	def generate(self, prompt: str, **kwargs) -> str:
		# Simplified implementation using requests or httpx (to be refined)
		import httpx

		timeout = httpx.Timeout(300.0, connect=10.0)
		with httpx.Client(timeout=timeout) as client:
			response = client.post(
				f"{self.base_url}/chat/completions",
				headers={"Authorization": f"Bearer {self.api_key}"},
				json={
					"model": kwargs.get("model", self.model),
					"messages": kwargs.get("messages", [{"role": "user", "content": prompt}]),
					"temperature": kwargs.get("temperature", 0.7),
				},
			)
			response.raise_for_status()
			return str(response.json()["choices"][0]["message"]["content"])

	def stream(self, prompt: str, **kwargs) -> Iterator[str]:
		# Implementation for streaming
		return iter([])


class SipInferenceProvider(BaseInferenceProvider):
	"""Provider for Sovereign Inference Proxy (SIP) over Unix Sockets."""

	def __init__(self, socket_path: str, model: str = "*Q4_K_M.gguf"):
		self.socket_path = socket_path
		self.model = model

	def generate(self, prompt: str, **kwargs) -> str:
		import http.client
		import json
		import socket

		class UnixHTTPConnection(http.client.HTTPConnection):
			def __init__(self, path: str):
				super().__init__("localhost")
				self.path = path

			def connect(self):
				self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
				self.sock.connect(self.path)

		payload = {
			"model": self.model,
			"messages": kwargs.get("messages", [{"role": "user", "content": prompt}]),
			"temperature": kwargs.get("temperature", 0.3),
		}

		conn = UnixHTTPConnection(self.socket_path)
		conn.request("POST", "/v1/chat/completions", body=json.dumps(payload))
		response = conn.getresponse()
		data = json.loads(response.read().decode())
		return str(data["choices"][0]["message"]["content"])

	def stream(self, prompt: str, **kwargs) -> Iterator[str]:
		return iter([])


class BitNetInferenceProvider(BaseInferenceProvider):
	"""
	Provider for 1.58-bit (ternary) inference using local llama-cli.
	Optimized for humble hardware (RTX 3050).
	"""

	def __init__(self, runner_path: str, model_path: str, grammar_path: Optional[str] = None):
		self.runner_path = runner_path
		self.model_path = model_path
		self.grammar_path = grammar_path

	def generate(self, prompt: str, **kwargs) -> str:
		import os
		import subprocess

		# Overrides from kwargs (via Minion Profiles)
		model_path = kwargs.get("model_path", self.model_path)
		max_tokens = kwargs.get("max_tokens", 128)
		temp = kwargs.get("temperature", 0.1)
		grammar_path = kwargs.get("grammar_path", self.grammar_path)
		use_mmap = kwargs.get("use_mmap", True)
		ngl = kwargs.get("ngl", 0)  # Hardware Offload

		cmd = [str(self.runner_path), "-m", str(model_path), "-p", str(prompt), "-n", str(max_tokens), "--temp", str(temp), "-ngl", str(ngl)]

		if not use_mmap:
			cmd.append("--no-mmap")

		if grammar_path and os.path.exists(str(grammar_path)):
			cmd.extend(["--grammar-file", str(grammar_path)])

		try:
			# LD_LIBRARY_PATH must be explicitly set for local subprocesses or they will fail to find libllama.so
			env = os.environ.copy()
			lib_path = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/build/3rdparty/llama.cpp/src")
			ggml_path = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/build/3rdparty/llama.cpp/ggml/src")
			env["LD_LIBRARY_PATH"] = f"{lib_path}:{ggml_path}:" + env.get("LD_LIBRARY_PATH", "")

			# Use a short timeout for humble hardware to prevent hangs
			result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
			output = result.stdout
			if result.stderr:
				print(f"DEBUG (stderr):\n{result.stderr}")

			# Parsing logic from experimental runner
			if prompt in output:
				return output.split(prompt)[-1].split("[end of text]")[0].strip()
			elif "Assistant:" in output:
				return output.split("Assistant:")[-1].split("[end of text]")[0].strip()

			# Fallback: return last non-empty line
			lines = [line.strip() for line in output.split("\n") if line.strip()]
			return lines[-1] if lines else ""

		except subprocess.TimeoutExpired:
			return "Error: Local BitNet inference timed out."
		except Exception as e:
			return f"Error: BitNet subprocess failed: {e}"

	def stream(self, prompt: str, **kwargs) -> Iterator[str]:
		# BitNet subprocess doesn't support easy streaming yet in this wrapper
		yield self.generate(prompt, **kwargs)
