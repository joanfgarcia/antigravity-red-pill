"""
Samantha On-Demand — Ephemeral local LLM invocation.

Lifecycle:
1. Check if the Hypervisor (SIP) is already running → use it.
2. If not running, check if the model/binary exist → start it ephemerally.
3. Do the work (prompt).
4. If we started it → stop it.

This avoids consuming Flash/cloud tokens for mechanical tasks
like session compaction, summarization, or classification.
"""

import json
import logging
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import Optional

from red_pill.config import get_config

logger = logging.getLogger(__name__)

# Default port for ephemeral instances (different from hypervisor's 8760)
_EPHEMERAL_PORT = 8790
_BOOT_TIMEOUT_S = 60
_REQUEST_TIMEOUT_S = 30


def _is_port_open(port: int) -> bool:
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			s.settimeout(1)
			return s.connect_ex(("127.0.0.1", port)) == 0
	except Exception:
		return False


def _is_hypervisor_alive() -> bool:
	"""Check if the persistent Hypervisor (SIP) is reachable on 8760."""
	return _is_port_open(8760)


def _find_model_path() -> Optional[str]:
	"""Resolve the model binary from the model registry."""
	try:
		from red_pill.core.model_registry import ModelRegistry

		_, profile = ModelRegistry.get_profile_by_capability("logic")
		if profile:
			model_path = profile.get("model_path", "")
			cfg = get_config()
			abs_path = os.path.join(cfg.APP_ROOT, model_path)
			if os.path.exists(abs_path):
				return abs_path
	except Exception as e:
		logger.warning(f"[Samantha] Failed to resolve model path from registry: {e}")
	return None


def _find_llama_binary() -> Optional[str]:
	"""Find llama-server binary."""
	cfg = get_config()
	bitnet_path = os.path.join(cfg.APP_ROOT, "3rdparty", "BitNet-1.58b", "build", "bin", "llama-server")
	if os.path.exists(bitnet_path):
		return bitnet_path

	import shutil

	system_path = shutil.which("llama-server")
	if system_path:
		return system_path
	return None


def _start_ephemeral() -> Optional[subprocess.Popen]:
	"""Start an ephemeral llama-server instance on _EPHEMERAL_PORT."""
	model_path = _find_model_path()
	llama_bin = _find_llama_binary()

	if not model_path:
		logger.warning("[Samantha] No model file found — cannot start on-demand.")
		return None
	if not llama_bin:
		logger.warning("[Samantha] No llama-server binary found — cannot start on-demand.")
		return None

	cmd = [
		llama_bin,
		"-m",
		model_path,
		"--port",
		str(_EPHEMERAL_PORT),
		"-c",
		"2048",
		"-ngl",
		"999",
	]

	logger.info(f"[Samantha] Starting ephemeral instance: {' '.join(cmd)}")
	try:
		proc = subprocess.Popen(
			cmd,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
			preexec_fn=os.setpgrp,
		)

		# Wait for port to open
		for _ in range(int(_BOOT_TIMEOUT_S * 2)):
			if proc.poll() is not None:
				logger.error(f"[Samantha] Ephemeral instance died during boot (exit={proc.returncode})")
				return None
			if _is_port_open(_EPHEMERAL_PORT):
				logger.info(f"[Samantha] Ephemeral instance ready on port {_EPHEMERAL_PORT}")
				return proc
			time.sleep(0.5)

		logger.error(f"[Samantha] Ephemeral instance failed to boot within {_BOOT_TIMEOUT_S}s")
		proc.kill()
		return None
	except Exception as e:
		logger.error(f"[Samantha] Failed to start ephemeral instance: {e}")
		return None


def _stop_ephemeral(proc: subprocess.Popen) -> None:
	"""Gracefully stop an ephemeral instance."""
	try:
		os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
		proc.wait(timeout=10)
		logger.info("[Samantha] Ephemeral instance stopped cleanly.")
	except subprocess.TimeoutExpired:
		os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
		logger.warning("[Samantha] Ephemeral instance killed (timeout).")
	except Exception as e:
		logger.warning(f"[Samantha] Error stopping ephemeral instance: {e}")


def _call_llm(port: int, prompt: str, system_prompt: str = "", max_tokens: int = 300) -> Optional[str]:
	"""Send a completion request to llama-server."""
	url = f"http://127.0.0.1:{port}/v1/chat/completions"
	messages = []
	if system_prompt:
		messages.append({"role": "system", "content": system_prompt})
	messages.append({"role": "user", "content": prompt})

	payload = json.dumps(
		{
			"messages": messages,
			"temperature": 0.0,
			"max_tokens": max_tokens,
			"seed": 770,
			"stop": ["<|im_end|>", "<|endoftext|>"],
		}
	).encode("utf-8")

	req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
	try:
		with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as response:
			data = json.loads(response.read().decode())
			content = data["choices"][0]["message"]["content"]
			if isinstance(content, str):
				return content.strip()
			return None
	except Exception as e:
		logger.error(f"[Samantha] LLM request failed: {e}")
		return None


def invoke(
	prompt: str,
	system_prompt: str = "",
	max_tokens: int = 300,
) -> Optional[str]:
	"""
	Invoke Samantha on-demand.

	1. If the Hypervisor is up → use port 8760.
	2. If not, try to start an ephemeral instance → use it → stop it.
	3. Returns the response text, or None if all paths fail.
	"""
	# Path 1: Hypervisor is already running
	if _is_hypervisor_alive():
		logger.info("[Samantha] Using persistent Hypervisor on port 8760")
		return _call_llm(8760, prompt, system_prompt, max_tokens)

	# Path 2: Ephemeral on-demand
	logger.info("[Samantha] Hypervisor offline — attempting ephemeral boot")

	# Check if ephemeral port is already occupied (avoid double-start)
	if _is_port_open(_EPHEMERAL_PORT):
		logger.info(f"[Samantha] Port {_EPHEMERAL_PORT} already in use — trying it")
		return _call_llm(_EPHEMERAL_PORT, prompt, system_prompt, max_tokens)

	proc = _start_ephemeral()
	if not proc:
		return None

	try:
		result = _call_llm(_EPHEMERAL_PORT, prompt, system_prompt, max_tokens)
		return result
	finally:
		_stop_ephemeral(proc)
