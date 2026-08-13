"""model_battle_lib.py — shared infrastructure for per-task model battle harnesses.

Provides:
  - BattleRunner: load GGUF, measure load time + VRAM peak, run probes.
  - Probe, BattleResult dataclasses.
  - format_summary: compact per-model summary table.
  - KNOWN_GGUF: central registry (kept in sync with model_profiles.yaml basenames).

Each per-task script imports this and defines its own probes + validators.
"""

from __future__ import annotations

import gc
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Single source of truth for the harness basenames. The profile paths in
# ~/.config/red-pill/model_profiles.yaml are authoritative for resolution.
KNOWN_GGUF: dict[str, str] = {
	"granite_8b": "Granite-4.1-8B-Q4_K_M.gguf",
	"granite_3b": "granite-4.1-3b-Q4_K_M.gguf",
	"hermes_8b": "Hermes-3-Llama-3.1-8B.Q4_K_M.gguf",
	"llama_32": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
	"phi_mini": "microsoft_Phi-4-mini-instruct-Q4_K_M.gguf",
	"gemma_3_4b": "google_gemma-3-4b-it-Q4_K_M.gguf",
	"mistral_nemo_12b": "Mistral-Nemo-Instruct-2407-Q3_K_M.gguf",
	"smollm3_3b": "SmolLM3-3B-Q4_K_M.gguf",
	"samantha": "samantha-mistral-instruct-7b.i1-Q4_K_M.gguf",
	"qwen35_9b": "Qwen3.5-9B-Q4_K_M.gguf",
	"qwen3_8b": "Qwen3-8B-Q4_K_M.gguf",
	"coder_heavy": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
}


@dataclass
class Probe:
	name: str
	system_prompt: str
	user_message: str
	# (raw_output: str) -> dict with at least {valid: bool, ...task-specific}
	validator: Callable[[str], dict]
	max_tokens: int = 450
	temperature: float = 0.1


@dataclass
class BattleResult:
	model: str
	probe_name: str
	latency_s: float
	raw_output: str
	validation: dict = field(default_factory=dict)

	def to_dict(self) -> dict:
		return asdict(self)


class BattleRunner:
	"""Load a GGUF once, run multiple probes, return BattleResults.

	Usage:
		runner = BattleRunner("granite_8b", "/path/to.gguf", chat_format="chatml")
		results = runner.run_all([probe1, probe2, ...])
		runner.close()
	"""

	def __init__(
		self, model_name: str, gguf_path: str, chat_format: Optional[str] = None, n_ctx: int = 6144, n_gpu_layers: int = -1, use_mmap: bool = False
	):
		from llama_cpp import Llama

		self.model_name = model_name
		self.gguf_path = gguf_path
		self.chat_format = chat_format
		self.n_ctx = n_ctx
		self.n_gpu_layers = n_gpu_layers
		t0 = time.time()
		kwargs = dict(model_path=gguf_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, use_mmap=use_mmap, verbose=False)
		if chat_format:
			kwargs["chat_format"] = chat_format
		self.llm = Llama(**kwargs)
		self.load_time_s = time.time() - t0
		self.results: list[BattleResult] = []

	def run(self, probe: Probe) -> BattleResult:
		t0 = time.time()
		try:
			out = self.llm.create_chat_completion(
				messages=[
					{"role": "system", "content": probe.system_prompt},
					{"role": "user", "content": probe.user_message},
				],
				temperature=probe.temperature,
				max_tokens=probe.max_tokens,
			)
			raw = out["choices"][0]["message"]["content"]
		except Exception as e:
			raw = f"<<error: {e}>>"
		dt = time.time() - t0
		validation = {}
		try:
			validation = probe.validator(raw)
		except Exception as e:
			validation = {"valid": False, "error": f"validator crashed: {e}"}
		res = BattleResult(model=self.model_name, probe_name=probe.name, latency_s=dt, raw_output=raw, validation=validation)
		self.results.append(res)
		return res

	def run_all(self, probes: list[Probe]) -> list[BattleResult]:
		print(f"\n##### {self.model_name} (chat_format={self.chat_format or 'auto'}) #####", flush=True)
		print(f"loaded in {self.load_time_s:.1f}s", flush=True)
		for p in probes:
			r = self.run(p)
			print(self._fmt_line(r), flush=True)
		return self.results

	@staticmethod
	def _fmt_line(r: BattleResult) -> str:
		v = r.validation
		if "valid" in v:
			ok = "OK" if v["valid"] else "FAIL"
		else:
			ok = "?"
		# Task-specific extras
		extras = []
		for k, val in v.items():
			if k in ("valid", "error"):
				continue
			extras.append(f"{k}={val}")
		extra_str = (" " + " ".join(extras)) if extras else ""
		return f"[{r.probe_name}] {r.latency_s:.1f}s {ok}{extra_str}\n  out: {r.raw_output[:160].replace(chr(10), ' ')}"

	def close(self) -> None:
		del self.llm
		gc.collect()


def format_summary(all_results: dict[str, list[BattleResult]]) -> str:
	"""Render a compact matrix: models × probes, with OK/FAIL and latency."""
	if not all_results:
		return "(no results)"
	probe_names = list({r.probe_name for rs in all_results.values() for r in rs})
	header = f"{'model':18s}" + "".join(f"{p:>22s}" for p in probe_names)
	lines = [header, "-" * len(header)]
	for model, results in all_results.items():
		row = {r.probe_name: r for r in results}
		cells = []
		for p in probe_names:
			r = row.get(p)
			if not r:
				cells.append(f"{'—':>22s}")
				continue
			v = r.validation
			ok = "✓" if v.get("valid") else ("✗" if "valid" in v else "?")
			cells.append(f"{ok} {r.latency_s:.1f}s".rjust(22))
		lines.append(f"{model:18s}" + "".join(cells))
	return "\n".join(lines)


def write_jsonl(results: list[BattleResult], path: Path) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as f:
		for r in results:
			f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")


def stop_daemon_if_active(unit: str = "redpill-llm.service") -> None:
	"""Best-effort stop to free VRAM for the bake-off. Idempotent."""
	os.system(f"systemctl --user stop {unit} >/dev/null 2>&1")


def start_daemon_if_inactive(unit: str = "redpill-llm.service") -> None:
	os.system(f"systemctl --user start {unit} >/dev/null 2>&1")
