import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


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

	def register_capability(self, task_name: str):
		"""Marks this provider as validated for a specific task (The Exam)."""
		if not hasattr(self, "_capabilities"):
			self._capabilities = ["general"]
		if task_name not in self._capabilities:
			self._capabilities.append(task_name)

	def validate_task_capability(self, task_name: str) -> bool:
		"""Returns True if the provider is authorized for the task."""
		if not hasattr(self, "_capabilities"):
			return task_name == "general"
		return task_name in self._capabilities or "all" in self._capabilities

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
		if "response_format" in kwargs:
			payload["response_format"] = kwargs["response_format"]

		conn = UnixHTTPConnection(self.socket_path)
		headers = {"Content-Type": "application/json"}
		conn.request("POST", "/v1/chat/completions", body=json.dumps(payload), headers=headers)
		response = conn.getresponse()
		raw_resp = response.read().decode()
		try:
			data = json.loads(raw_resp)
			return str(data["choices"][0]["message"]["content"])
		except (KeyError, IndexError, json.JSONDecodeError) as e:
			print(f"[SIP DEBUG] KeyError or parse error: {e}. Raw response: {raw_resp[:1000]}")
			raise e

	def chat(self, messages, *, tools=None, tool_choice=None, temperature=0.3, max_tokens=1024, response_format=None, timeout=600):
		"""Full chat call returning the assistant MESSAGE dict (incl. tool_calls).

		Unlike generate() (which returns only text content, used by the distiller),
		this forwards tools/tool_choice so the endpoint emits OpenAI-style tool_calls.
		"""
		import http.client
		import json
		import socket

		class UnixHTTPConnection(http.client.HTTPConnection):
			def __init__(self, path: str, timeout: int):
				super().__init__("localhost", timeout=timeout)
				self.path = path

			def connect(self):
				self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
				self.sock.settimeout(self.timeout)
				self.sock.connect(self.path)

		payload = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
		if tools:
			payload["tools"] = tools
		if tool_choice:
			payload["tool_choice"] = tool_choice
		if response_format:
			payload["response_format"] = response_format

		conn = UnixHTTPConnection(self.socket_path, timeout=timeout)
		conn.request("POST", "/v1/chat/completions", body=json.dumps(payload), headers={"Content-Type": "application/json"})
		response = conn.getresponse()
		data = json.loads(response.read().decode())
		return data["choices"][0]["message"]

	def stream(self, prompt: str, **kwargs) -> Iterator[str]:
		return iter([])


class BitNetInferenceProvider(BaseInferenceProvider):
	"""
	Provider for 1.58-bit (ternary) inference using local llama-cli.
	Optimized for 8GB VRAM (RTX 5070 Laptop GPU).
	Max context: 16384 (CUDA) / 2048 (CPU).
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

		# Dynamically calculate minimal context size if not explicitly set to prevent VRAM wastage/OOM
		if "ctx_size" not in kwargs:
			prompt_tokens_est = len(prompt.split()) * 2
			required_tokens = prompt_tokens_est + max_tokens + 16
			ctx_size = 32
			while ctx_size < required_tokens:
				ctx_size *= 2
		else:
			ctx_size = kwargs["ctx_size"]

		cmd = [
			str(self.runner_path),
			"-m",
			str(model_path),
			"-p",
			str(prompt),
			"-n",
			str(max_tokens),
			"--temp",
			str(temp),
			"-ngl",
			str(ngl),
			"-c",
			str(ctx_size),
		]

		if not use_mmap:
			cmd.append("--no-mmap")

		if grammar_path and os.path.exists(str(grammar_path)):
			cmd.extend(["--grammar-file", str(grammar_path)])

		try:
			# LD_LIBRARY_PATH must be explicitly set for local subprocesses or they will fail to find libllama.so
			env = os.environ.copy()
			build_dir = os.path.dirname(os.path.dirname(str(self.runner_path)))
			lib_path = os.path.join(build_dir, "3rdparty", "llama.cpp", "src")
			ggml_path = os.path.join(build_dir, "3rdparty", "llama.cpp", "ggml", "src")
			env["LD_LIBRARY_PATH"] = f"{lib_path}:{ggml_path}:" + env.get("LD_LIBRARY_PATH", "")

			# Use a short timeout for humble hardware to prevent hangs
			result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
			output = result.stdout
			if result.stderr:
				print(f"DEBUG (stderr):\n{result.stderr}")

			# Parsing logic - handle Falcon3 chat template delimiters
			if "<|assistant|>" in output:
				return output.split("<|assistant|>")[-1].split("[end of text]")[0].strip()
			elif prompt in output:
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


class LlamaCppInferenceProvider(BaseInferenceProvider):
	"""
	Provider for local GGUF inference using llama-cli directly.
	Implements BE_WATER: auto-detects CUDA VRAM, systemd-run for OOM shielding,
	and gracefully degrades to CPU if necessary.
	"""

	def __init__(self, runner_path: str, model_path: str, use_oom_shield: bool = False, memory_max: str = "10G", ngl: int = 0):
		self.runner_path = runner_path
		self.model_path = model_path
		self.use_oom_shield = use_oom_shield
		self.memory_max = memory_max
		self.ngl = ngl
		self._llm: Optional[Any] = None

	@classmethod
	def create_be_water(cls, model_name_or_path: str) -> Optional["LlamaCppInferenceProvider"]:
		import os
		import shutil

		# 1. Locate runner
		workspace = os.getenv("WORKSPACE_ROOT", os.path.expanduser("~/Documents/IA"))
		runner_path = os.path.join(workspace, "sharing", "3rdparty", "llama_official", "build", "bin", "llama-cli")
		if not os.path.exists(runner_path):
			runner_path_opt = shutil.which("llama-cli")
			if not runner_path_opt:
				return None
			runner_path = runner_path_opt

		# 2. Locate model and apply guards
		model_path = None
		if os.path.exists(model_name_or_path) and os.path.isfile(model_name_or_path):
			model_path = os.path.abspath(model_name_or_path)
		else:
			# Preset search paths
			search_paths = [
				os.path.join(workspace, "models", "gguf", model_name_or_path),
				os.path.join(workspace, "sharing", "models", "gguf", model_name_or_path),
				os.path.join(workspace, "sharing", "3rdparty", "BitNet-1.58b", "models", model_name_or_path),
				os.path.join(workspace, "experimental", "Samantha", model_name_or_path),
			]
			for p in search_paths:
				if os.path.exists(p) and os.path.isfile(p):
					model_path = os.path.abspath(p)
					break

		# Guard 1: Verify model existence
		if not model_path:
			logger.error(f"[LlamaCppInferenceProvider] Model not found: '{model_name_or_path}'")
			return None

		# Guard 2: Verify model file size (must be >= 10MB) to prevent corrupt loading
		try:
			file_size = os.path.getsize(model_path)
			if file_size < 10 * 1024 * 1024:
				logger.error(
					f"[LlamaCppInferenceProvider] Guard failure: Model file is too small ({file_size / (1024 * 1024):.1f} MB), likely corrupt: {model_path}"
				)
				return None
		except Exception as e:
			logger.error(f"[LlamaCppInferenceProvider] Guard failure checking file size: {e}")
			return None

		# Guard 3: Verify extension
		ext = os.path.splitext(model_path)[1].lower()
		if ext not in (".gguf", ".bin"):
			logger.warning(f"[LlamaCppInferenceProvider] Model extension is unusual ({ext}), proceeding with caution: {model_path}")

		# 3. Detect VRAM & NGL
		ngl = 0
		try:
			import torch

			if torch.cuda.is_available():
				vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
				if vram_gb > 3.0:
					ngl = 99
		except Exception:
			pass

		# 4. Detect OOM Shield capabilities
		use_oom_shield = shutil.which("systemd-run") is not None
		memory_max = "10G"  # Sensible default for 32GB systems, could be dynamic

		logger.info(f"[LlamaCppInferenceProvider] Guard success. Loaded model from: {model_path}")
		return cls(runner_path=runner_path, model_path=model_path, use_oom_shield=use_oom_shield, memory_max=memory_max, ngl=ngl)

	def generate(self, prompt: str, **kwargs) -> str:
		if kwargs.get("backtrack_mode") and kwargs["backtrack_mode"] != "none":
			return self.generate_with_backtrack(prompt, **kwargs)

		import os
		import subprocess

		import torch

		max_tokens = kwargs.get("max_tokens", 256)
		temp = kwargs.get("temperature", 0.1)

		# Dynamically calculate minimal context size if not explicitly set to prevent VRAM wastage/OOM
		if "ctx_size" not in kwargs:
			# Estimate prompt length by words with safety factor of 2 (to cover BPE tokens)
			prompt_tokens_est = len(prompt.split()) * 2
			# Add max_tokens plus a small padding
			required_tokens = prompt_tokens_est + max_tokens + 16
			# Find the nearest power of 2 starting at 32
			ctx_size = 32
			while ctx_size < required_tokens:
				ctx_size *= 2
		else:
			ctx_size = kwargs["ctx_size"]

		chat_prompt = f"<|user|>\n{prompt}\n<|assistant|>\n"

		# Hardware selection override
		device = kwargs.get("device", "cuda" if torch.cuda.is_available() else "cpu").lower()
		ngl = self.ngl
		runner_path = self.runner_path
		env = os.environ.copy()

		if device in ("vulkan", "igpu"):
			# Resolve Vulkan runner
			workspace = os.getenv("WORKSPACE_ROOT", os.path.expanduser("~/Documents/IA"))
			vulkan_runner = os.path.join(workspace, "sharing", "3rdparty", "BitNet-1.58b", "build_vulkan", "bin", "llama-cli")
			if os.path.exists(vulkan_runner):
				runner_path = vulkan_runner
			ngl = kwargs.get("ngl", 99)  # Offload all layers to iGPU
			# Cap context size to avoid OutOfDeviceMemory on iGPU
			if "ctx_size" not in kwargs:
				ctx_size = min(ctx_size, 2048)
			# Set Vulkan AMD Mesa RADV driver automatically if available
			if os.path.exists("/usr/share/vulkan/icd.d/radeon_icd.json"):
				env["VK_ICD_FILENAMES"] = "/usr/share/vulkan/icd.d/radeon_icd.json"

		cmd = []
		if self.use_oom_shield:
			cmd.extend(["systemd-run", "--user", "--scope", "-p", f"MemoryMax={self.memory_max}"])

		cmd.extend(
			[
				str(runner_path),
				"-m",
				str(self.model_path),
				"-p",
				chat_prompt,
				"-n",
				str(max_tokens),
				"-c",
				str(ctx_size),
				"-ngl",
				str(ngl),
				"--temp",
				str(temp),
				"--simple-io",  # Prevent interactive hang
			]
		)

		# Clean LD_LIBRARY_PATH for Vulkan/Native clashes
		if "LD_LIBRARY_PATH" in env:
			paths = env["LD_LIBRARY_PATH"].split(":")
			clean_paths = [p for p in paths if "BitNet" not in p and "ollama" not in p]
			env["LD_LIBRARY_PATH"] = ":".join(clean_paths)

		try:
			result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, env=env)
			output = result.stdout

			if "<|assistant|>" in output:
				return output.split("<|assistant|>")[-1].strip()
			elif "Assistant:" in output:
				return output.split("Assistant:")[-1].strip()

			lines = [line.strip() for line in output.split("\n") if line.strip()]
			return lines[-1] if lines else ""
		except subprocess.TimeoutExpired:
			return "Error: Local Inference timed out."
		except Exception as e:
			return f"Error: Local subprocess failed: {e}"

	def generate_with_backtrack(self, prompt: str, **kwargs) -> str:
		"""
		Generates text using the python-native llama_cpp.Llama
		with token-by-token backtracking and automatic KV-cache recycling.
		"""
		import numpy as np
		from llama_cpp import Llama, llama_get_logits

		max_tokens = kwargs.get("max_tokens", 256)
		temp = kwargs.get("temperature", 0.7)
		mode = kwargs.get("backtrack_mode", "confidence")
		conf_thresh = kwargs.get("conf_thresh", 0.05)
		lookahead_thresh = kwargs.get("lookahead_thresh", 0.02)
		entropy_thresh = kwargs.get("entropy_thresh", 4.0)
		max_backtracks = kwargs.get("max_backtracks", 15)

		if not hasattr(self, "_llm") or self._llm is None:
			self._llm = Llama(model_path=self.model_path, n_ctx=kwargs.get("ctx_size", 1024), n_gpu_layers=self.ngl, verbose=False)

		llm = self._llm
		prompt_tokens = llm.tokenize(prompt.encode("utf-8"))
		current_tokens = list(prompt_tokens)
		generated: List[int] = []

		blacklist_by_depth: Dict[int, set[int]] = {}
		depth = 0
		backtrack_count = 0

		llm.reset()
		llm.eval(current_tokens)
		vocab_size = llm.n_vocab()

		while len(generated) < max_tokens:
			logits_ptr = llama_get_logits(llm.ctx)
			logits = np.copy(np.ctypeslib.as_array(logits_ptr, shape=(vocab_size,)))
			curr_blacklist = blacklist_by_depth.get(depth, set())

			if curr_blacklist:
				for token_id in curr_blacklist:
					logits[token_id] = -float("Inf")

			if temp <= 0.0:
				next_token = int(np.argmax(logits))
				prob = 1.0
				probs = np.zeros(vocab_size)
				probs[next_token] = 1.0
			else:
				exp_logits = np.exp(logits - np.max(logits))
				probs = exp_logits / np.sum(exp_logits)

				top_k = kwargs.get("top_k", 40)
				if top_k > 0:
					top_k_indices = np.argpartition(probs, -top_k)[-top_k:]
					min_top_prob = np.min(probs[top_k_indices])
					probs[probs < min_top_prob] = 0.0
					probs /= np.sum(probs)

				top_p = kwargs.get("top_p", 0.9)
				if top_p < 1.0:
					sorted_indices = np.argsort(probs)[::-1]
					sorted_probs = probs[sorted_indices]
					cumulative_probs = np.cumsum(sorted_probs)
					indices_to_remove = cumulative_probs > top_p
					indices_to_remove[1:] = indices_to_remove[:-1].copy()
					indices_to_remove[0] = False
					probs[sorted_indices[indices_to_remove]] = 0.0
					probs /= np.sum(probs)

				try:
					next_token = int(np.random.choice(len(probs), p=probs))
					prob = probs[next_token]
				except ValueError:
					next_token = int(np.argmax(logits))
					prob = probs[next_token]

			entropy = -np.sum(probs * np.log(probs + 1e-9))
			trigger_backtrack = False

			if mode == "confidence" and prob < conf_thresh:
				trigger_backtrack = True
			elif mode == "entropy" and entropy > entropy_thresh:
				trigger_backtrack = True
			elif mode == "lookahead" and len(generated) < max_tokens - 1:
				llm.eval([next_token])
				next_logits_ptr = llama_get_logits(llm.ctx)
				next_logits = np.copy(np.ctypeslib.as_array(next_logits_ptr, shape=(vocab_size,)))
				exp_logits = np.exp(next_logits - np.max(next_logits))
				next_probs = exp_logits / np.sum(exp_logits)
				max_next_prob = np.max(next_probs)

				if max_next_prob < lookahead_thresh:
					trigger_backtrack = True
					llm.n_tokens -= 1

			if trigger_backtrack and backtrack_count < max_backtracks:
				backtrack_count += 1
				if depth not in blacklist_by_depth:
					blacklist_by_depth[depth] = set()
				blacklist_by_depth[depth].add(next_token)

				if len(blacklist_by_depth[depth]) >= 4 and depth > 0:
					blacklist_by_depth[depth] = set()
					depth -= 1
					if generated:
						generated.pop()
						current_tokens.pop()
						llm.n_tokens -= 1

				llm.eval(current_tokens)
				continue

			generated.append(next_token)
			current_tokens.append(next_token)
			depth += 1
			blacklist_by_depth[depth] = set()

			if mode != "lookahead":
				llm.eval([next_token])

			if next_token == llm.token_eos():
				break

		return llm.detokenize(generated).decode("utf-8", errors="ignore").strip()

	def stream(self, prompt: str, **kwargs) -> Iterator[str]:
		yield self.generate(prompt, **kwargs)


class FastFlowLMInferenceProvider(BaseInferenceProvider):
	"""
	Provider for AMD XDNA2 NPU inference via FastFlowLM server.
	Uses the OpenAI-compatible /v1/chat/completions API.

	Performance (measured):
		- Qwen3-0.6B: 96 tok/s @ ~2W
		- Qwen3-8B:   10.6 tok/s @ ~2W

	Requirements:
		- FastFlowLM v0.9.42+ installed
		- NPU validated: `flm validate`
		- memlock=unlimited for the serving process
		- Server running: `flm serve <model_tag>`
	"""

	def __init__(
		self,
		base_url: str = "http://localhost:52625",
		model: str = "qwen3:8b",
		timeout: float = 120.0,
	):
		self.base_url = base_url.rstrip("/")
		self.model = model
		self.timeout = timeout
		self._available: Optional[bool] = None

	def is_available(self) -> bool:
		"""Check if the FastFlowLM server is reachable."""
		try:
			import httpx

			with httpx.Client(timeout=2.0) as client:
				resp = client.get(f"{self.base_url}/v1/models")
				self._available = resp.status_code == 200
		except Exception:
			self._available = False
		return self._available

	def generate(self, prompt: str, **kwargs) -> str:
		import httpx

		model = kwargs.get("model", self.model)
		temperature = kwargs.get("temperature", 0.7)
		max_tokens = kwargs.get("max_tokens", 256)

		# Build messages from kwargs or wrap prompt
		messages = kwargs.get("messages")
		if not messages:
			system_prompt = kwargs.get("system_prompt")
			messages = []
			if system_prompt:
				messages.append({"role": "system", "content": system_prompt})
			messages.append({"role": "user", "content": prompt})

		payload: Dict[str, Any] = {
			"model": model,
			"messages": messages,
			"temperature": temperature,
			"max_tokens": max_tokens,
		}

		try:
			timeout_cfg = httpx.Timeout(self.timeout, connect=5.0)
			with httpx.Client(timeout=timeout_cfg) as client:
				response = client.post(
					f"{self.base_url}/v1/chat/completions",
					json=payload,
				)
				response.raise_for_status()
				data = response.json()

				content = str(data["choices"][0]["message"]["content"])

				# Strip Qwen3 <think> blocks if present (thinking mode)
				if "<think>" in content:
					if "</think>" in content:
						content = content.split("</think>")[-1].strip()
					else:
						# Truncated think block (max_tokens hit mid-thought)
						content = content.split("<think>")[0].strip()

				# Log performance metrics if available
				usage = data.get("usage", {})
				decode_tps = usage.get("decoding_speed_tps")
				if decode_tps:
					logger.debug(f"[NPU] {model}: {decode_tps:.1f} tok/s, {usage.get('total_tokens', '?')} tokens")

				return content

		except httpx.TimeoutException:
			logger.warning(f"[NPU] FastFlowLM timeout after {self.timeout}s")
			return "Error: NPU inference timed out."
		except httpx.HTTPStatusError as e:
			logger.error(f"[NPU] FastFlowLM HTTP error: {e.response.status_code}")
			return f"Error: NPU inference HTTP {e.response.status_code}"
		except Exception as e:
			logger.error(f"[NPU] FastFlowLM error: {e}")
			return f"Error: NPU inference failed: {e}"

	def stream(self, prompt: str, **kwargs) -> Iterator[str]:
		"""FastFlowLM supports streaming via SSE. Fallback to full generation."""
		import httpx

		model = kwargs.get("model", self.model)
		temperature = kwargs.get("temperature", 0.7)
		max_tokens = kwargs.get("max_tokens", 256)

		messages = kwargs.get("messages")
		if not messages:
			messages = [{"role": "user", "content": prompt}]

		payload: Dict[str, Any] = {
			"model": model,
			"messages": messages,
			"temperature": temperature,
			"max_tokens": max_tokens,
			"stream": True,
		}

		try:
			import json

			timeout_cfg = httpx.Timeout(self.timeout, connect=5.0)
			with httpx.Client(timeout=timeout_cfg) as client:
				with client.stream("POST", f"{self.base_url}/v1/chat/completions", json=payload) as response:
					for line in response.iter_lines():
						if not line or not line.startswith("data: "):
							continue
						chunk_str = line[6:]  # strip "data: "
						if chunk_str == "[DONE]":
							break
						try:
							chunk = json.loads(chunk_str)
							delta = chunk.get("choices", [{}])[0].get("delta", {})
							token = delta.get("content", "")
							if token:
								yield token
						except json.JSONDecodeError:
							continue
		except Exception:
			# Fallback to non-streaming
			yield self.generate(prompt, **kwargs)


# Self-registration of default providers
try:
	import red_pill.config as cfg

	ProviderRegistry.register_inference_provider("sip", SipInferenceProvider(socket_path=cfg.SIP_SOCKET_PATH), default=True)
except Exception:
	pass

# NPU Provider: auto-register if FastFlowLM server is reachable
try:
	import red_pill.config as cfg  # noqa: F811

	_flm_url = os.environ.get("FLM_BASE_URL", "http://localhost:52625")
	_flm_model = os.environ.get("FLM_MODEL", "qwen3:8b")
	_npu_provider = FastFlowLMInferenceProvider(base_url=_flm_url, model=_flm_model)
	if _npu_provider.is_available():
		ProviderRegistry.register_inference_provider("npu", _npu_provider)
		logger.info(f"[NPU] FastFlowLM provider registered: {_flm_url} ({_flm_model})")
except Exception:
	pass
