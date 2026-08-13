"""llama_cli_runner.py — BattleRunner alternative that uses the llama.cpp binary.

Why: the llama-cpp-python wheel has been failing to install libggml-cuda.so in
this environment (CUDA 13 + GCC 15 + scikit-build + llama.cpp 0.3.34 packaging
issues). The llama.cpp binary we already have at
`~/3rdparty/llama_official/build/bin/llama-cli` was built with CUDA, detects
the RTX 5070, and is the EXACT binary used in production via SIP — so
behavioural equivalence is guaranteed by construction.

Uses CLI mode (no port), one subprocess per probe. ~1-2s spawn overhead per
probe vs the Python bindings in-process.

Output format: llama-cli outputs the response prefixed with `| ` (single
pipe-space). We extract the response body between the `| ` line and the
perf summary (`[ Prompt:` or `common_memory_breakdown_print:`).
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

LLAMA_CLI = Path("/home/joan/Documents/IA/sharing/3rdparty/llama_official/build/bin/llama-cli")


@dataclass
class CliProbe:
	name: str
	system_prompt: str
	user_message: str
	validator: Callable[[str], dict]
	max_tokens: int = 450
	temperature: float = 0.1
	tools_json: list[dict] = field(default_factory=list)


# Pattern to extract the response body. llama-cli emits the response lines
# starting with `| ` (it's a visual indicator). Everything after the LAST line
# starting with `| ` and before the perf summary is the response.
_RESPONSE_RE = re.compile(r"^\|\s?(.*)$", re.MULTILINE)
_PERF_RE = re.compile(r"\[ (Prompt|Generation):.*\]", re.MULTILINE)


def _parse_cli_output(stdout: str) -> str:
	"""Extract the model response from llama-cli stdout."""
	# Find the last `| ...` line and collect until perf summary.
	lines = stdout.splitlines()
	collecting = False
	body: list[str] = []
	for line in lines:
		if line.startswith("| "):
			collecting = True
			body.append(line[2:])  # strip `| `
		elif line.startswith("|"):
			collecting = True
			# `|something` without space — keep as-is
			body.append(line[1:])
		elif collecting:
			# Stop if we hit a perf summary or memory breakdown.
			if line.startswith("[ Prompt:") or line.startswith("[ Generation:") or line.startswith("common_memory"):
				break
			# Continuation of the response (e.g. multi-line).
			body.append(line)
	return "\n".join(body).strip()


class LlamaCliRunner:
	def __init__(self, model_name: str, gguf_path: str, n_ctx: int = 6144, n_gpu_layers: int = -1, chat_template_file: Optional[str] = None):
		self.model_name = model_name
		self.gguf_path = gguf_path
		self.n_ctx = n_ctx
		self.n_gpu_layers = n_gpu_layers
		self.chat_template_file = chat_template_file
		if not LLAMA_CLI.exists():
			raise FileNotFoundError(f"llama-cli not found at {LLAMA_CLI}. Build it first via the 3rdparty/llama_official build system.")
		self.cli_path = LLAMA_CLI

	def run(self, probe: CliProbe) -> "CliResult":
		cmd = [
			str(self.cli_path),
			"-m",
			self.gguf_path,
			"-sys",
			probe.system_prompt,
			"-p",
			probe.user_message,
			"-n",
			str(probe.max_tokens),
			"--temp",
			str(probe.temperature),
			"-ngl",
			str(self.n_gpu_layers),
			"-c",
			str(self.n_ctx),
			"--single-turn",  # exit after one response (no REPL)
			"--no-display-prompt",  # don't echo our prompt
		]
		if self.chat_template_file:
			cmd.extend(["--chat-template-file", self.chat_template_file])
		t0 = time.time()
		proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
		dt = time.time() - t0
		raw = _parse_cli_output(proc.stdout)
		validation = {}
		try:
			validation = probe.validator(raw)
		except Exception as e:
			validation = {"valid": False, "error": f"validator crashed: {e}"}
		return CliResult(probe_name=probe.name, latency_s=dt, raw_output=raw, validation=validation, cli_returncode=proc.returncode)


@dataclass
class CliResult:
	probe_name: str
	latency_s: float
	raw_output: str
	validation: dict
	cli_returncode: int
