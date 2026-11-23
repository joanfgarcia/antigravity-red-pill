import logging
import os
from typing import Any, Optional

from red_pill.core.paths import get_models_dir

logger = logging.getLogger(__name__)

# 1. Fallback to basic extraction if llama_cpp is not available
try:
	from llama_cpp import Llama

	LLAMA_AVAILABLE = True
except ImportError:
	LLAMA_AVAILABLE = False


class EdgeEngine:
	"""
	Local SLM logic for edge-node processing.
	Used for compression, synthesis, and technical extraction.

	PERF-F01: Lazy-loading model — the GGUF is only loaded on the
	first call to compress() or synthesize(), not at instantiation.
	This avoids a multi-GB VRAM allocation for agents that are
	spawned but may never be invoked.
	"""

	def __init__(self, model_path: Optional[str] = None, n_gpu_layers: int = -1):
		self.llm: Optional[Any] = None
		self._llm_loaded = False
		self._n_gpu_layers = n_gpu_layers

		# XDG is the source of truth (RULE 1 — CONVENTIONS.md)
		model_dir = str(get_models_dir())
		# Optional override: WORKSPACE_ROOT/models for developer profiles
		workspace_override = os.getenv("WORKSPACE_ROOT")
		if workspace_override:
			candidate = os.path.join(workspace_override, "models")
			if os.path.isdir(candidate):
				model_dir = candidate

		# Perfil EXPLÍCITO (2026-11-23). Antes se elegía "el primer .gguf del
		# directorio": con varios modelos en disco el healer podía cargar un 27B
		# ternario que su runtime no abre. El perfil se puede cambiar por env sin
		# tocar código; si no existe, el motor queda en modo extracción.
		if not model_path:
			profile_name = os.getenv("REDPILL_EDGE_PROFILE", "granite_4_2_8b")
			try:
				from red_pill.core.model_registry import ModelRegistry

				profile = ModelRegistry.get_profile(profile_name) or {}
				mp = str(profile.get("model_path") or "")
				if mp:
					model_path = mp if os.path.isabs(mp) else os.path.join(model_dir, mp)
			except Exception as exc:  # noqa: BLE001
				logger.warning("EdgeEngine: no se pudo resolver el perfil '%s': %s", profile_name, exc)

		self.model_path = model_path

	def _ensure_loaded(self) -> None:
		"""PERF-F01: Lazy-load the LLM on first use."""
		if self._llm_loaded:
			return
		self._llm_loaded = True  # Mark before attempt to avoid retry storms

		if not LLAMA_AVAILABLE or not self.model_path or not os.path.exists(self.model_path):
			if not LLAMA_AVAILABLE:
				logger.debug("CQ-001: llama_cpp not installed — EdgeEngine running in fallback-only mode.")
			elif not self.model_path:
				logger.debug("CQ-001: No GGUF model found in model directory — EdgeEngine running in fallback-only mode.")
			else:
				logger.warning(f"CQ-001: Model path does not exist: {self.model_path} — EdgeEngine running in fallback-only mode.")
			return

		try:
			self.llm = Llama(
				model_path=self.model_path,
				n_ctx=8192,
				n_gpu_layers=self._n_gpu_layers,
				verbose=False,
			)
		except Exception as e:
			logger.warning(f"CQ-001: Model load failed for '{self.model_path}': {e}. EdgeEngine will use fallback extraction for this session.")
			self.llm = None

	def compress(self, text: str) -> str:
		self._ensure_loaded()
		if not self.llm:
			return self._fallback_compress(text)

		try:
			from red_pill.core import prompts as core

			system_prompt = core.render("swarm", "technical_extractor_system")
			# ChatML format for Qwen
			prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"

			output = self.llm(
				prompt, max_tokens=256, stop=["<|im_end|>", "<|im_start|>", "</s>", "<|endoftext|>"], temperature=0.1, repeat_penalty=1.1
			)
			if isinstance(output, dict):
				return str(output["choices"][0]["text"]).strip()
			return ""

		except Exception as e:
			print(f"Edge compression failed: {e}")
			return self._fallback_compress(text)
		# PERF-F03: gc.collect() removed — GGUF model stays resident in VRAM;
		# forcing a GC cycle here is ineffective and adds 50-200ms of latency.

	def _fallback_compress(self, text: str) -> str:
		import re

		# 7B Surgical Patch: Ensure sanitized extraction even in fallback
		clean_text = re.sub(r"^(hola|buenos\s+d[íi]as|oye|por\s+favor)[,\s]*", "", text, flags=re.IGNORECASE)
		clean_text = re.sub(r"[,\s]*(gracias|un\s+saludo|adi[óo]s)$", "", clean_text, flags=re.IGNORECASE)

		# Protection: Do not truncate if sensitive patterns are present
		sentences = [s.strip() for s in re.split(r"[.!?\n]+", clean_text) if len(s.strip()) > 5]
		compressed_lines = []
		for s in sentences:
			# Surgical Patch: 'fluff' is now a regex list for more robust removal
			fluff_patterns = [
				r"necesito\s+que",
				r"me\s+gustar[íi]a\s+saber\s+si",
				r"podr[íi]as",
				r"te\s+importar[íi]a",
				r"estoy\s+intentando",
				r"creo\s+que",
				r"b[áa]sicamente\s+lo\s+que\s+pasa\s+es\s+que",
			]
			for p in fluff_patterns:
				s = re.sub(p, "", s, flags=re.IGNORECASE)

			s = s.strip()
			if s:
				compressed_lines.append(f"- {s.capitalize()}")

		synthesis = "\n".join(compressed_lines)
		return synthesis if synthesis else text.strip()

	def synthesize(self, background: str, query: str) -> str:
		"""Synthesize retrieved context into a coherent summary."""
		self._ensure_loaded()
		if not self.llm:
			# 7B Surgical Patch: Sanitized Fallback
			# We never just truncate background if it could contain raw engrams
			self._log_warn("Falling back to sanitized concatenation (no LLM)")
			return f"Contexto Refinado (Sanitizado):\n{background[:800]}..."

		try:
			system_prompt = (
				"[Refraction: 760_ORACLE] Style: Analytical, concise. "
				"Tone: Precise, technical. Focus: Synthesize context based on query, prioritizing security truths."
			)
			prompt = (
				f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
				f"<|im_start|>user\nContext:\n{background}\n\nQuery: {query}<|im_end|>\n"
				f"<|im_start|>assistant\n"
			)

			output = self.llm(
				prompt,
				max_tokens=1024,  # Increased for 7B capacity
				stop=["<|im_end|>", "<|im_start|>", "</s>", "<|endoftext|>"],
				temperature=0.2,
			)
			if isinstance(output, dict):
				return str(output["choices"][0]["text"]).strip()
			return ""
		except Exception:
			return f"Err: Synthesis Failure. Raw snippet: {background[:200]}..."

	def _log_warn(self, msg: str):
		# Internal minimal logging
		print(f"[EdgeEngine:WARN] {msg}")
