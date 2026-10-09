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
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

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
	# 2026-09-11 candidates (multilingual / tool-calling / reasoning-distill)
	"tiny_aya": "tiny-aya-global-q4_k_m.gguf",
	"gemma4_e4b": "gemma-4-E4B-it-Q4_0.gguf",
	"r1_distill": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
}


@dataclass
class Probe:
	name: str
	system_prompt: str
	user_message: str
	# (raw_output: str) -> dict with at least {valid: bool, ...task-specific}
	validator: Callable[[str], dict]
	# None = "sin override": el runner aplica la conducta del modelo (perfil ⊕ task).
	max_tokens: Optional[int] = None
	temperature: Optional[float] = None


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
		self,
		model_name: str,
		gguf_path: str,
		chat_format: Optional[str] = None,
		n_ctx: int = 6144,
		n_gpu_layers: int = -1,
		use_mmap: bool = False,
		resolved: Optional[Any] = None,
	):
		from llama_cpp import Llama

		self.model_name = model_name
		self.gguf_path = gguf_path
		self.chat_format = chat_format
		self.n_ctx = n_ctx
		self.n_gpu_layers = n_gpu_layers
		self.resolved = resolved
		t0 = time.time()
		kwargs = dict(model_path=gguf_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, use_mmap=use_mmap, verbose=False)
		if chat_format:
			kwargs["chat_format"] = chat_format
		if resolved is not None:
			from red_pill.core import model_runtime as mr

			# MEM-009 D5: sin FA el scratch de prefill agota el headroom en estos
			# perfiles (Failed to create llama_context); el perfil lo declara.
			kwargs["flash_attn"] = mr.effective_flash_attn(resolved, "gpu")
		self.llm = Llama(**kwargs)
		self.load_time_s = time.time() - t0
		# RFC-HARNESS-003 corte 4: la conducta del modelo (handlers thinking,
		# chat_format) se aplica UNA vez al cargar; los samplers por probe.
		if self.resolved is not None:
			from red_pill.inference import conduct

			conduct.apply_python(self.llm, self.resolved)
		self.results: list[BattleResult] = []

	def run(self, probe: Probe) -> BattleResult:
		t0 = time.time()
		try:
			kwargs: dict = {}
			max_tokens = probe.max_tokens
			if self.resolved is not None:
				from red_pill.inference import conduct

				conduct.apply_python(self.llm, self.resolved)
				kwargs.update(conduct.sampling_kwargs(self.resolved, temperature=probe.temperature))
				max_tokens = probe.max_tokens or self.resolved.max_tokens
			elif probe.temperature is not None:
				kwargs["temperature"] = probe.temperature
			if max_tokens:
				kwargs["max_tokens"] = max_tokens
			out = self.llm.create_chat_completion(
				messages=[
					{"role": "system", "content": probe.system_prompt},
					{"role": "user", "content": probe.user_message},
				],
				**kwargs,
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


class RuntimeBattleRunner:
	"""BattleRunner sobre el runtime anclado del perfil (RFC-HARNESS-003).

	Sirve por el RuntimeServer dedicado (llama-server del runtime declarado —
	p.ej. fork PrismML para ternarios) en vez de llama-cpp-python. Mismo
	contrato que BattleRunner: run(probe) → BattleResult, run_all, close.
	"""

	def __init__(
		self,
		model_name: str,
		n_ctx: Optional[int] = None,
		extra_args: Optional[list[str]] = None,
		unload_daemon: bool = True,
	):
		from red_pill.core import model_runtime as mr
		from red_pill.inference.runtime_server import RuntimeServer

		self.model_name = model_name
		self.chat_format = None
		self.resolved = mr.resolve({"model": model_name})
		# ctx=None → el plan del RuntimeServer decide (contexto deseado del perfil + KV adaptativa §2.7).
		self._server = RuntimeServer(model_name, ctx=n_ctx, extra_args=extra_args, unload_daemon=unload_daemon)
		t0 = time.time()
		self._server.start()
		self.load_time_s = time.time() - t0
		self.kv_type = self._server.kv_type
		self.ctx = self._server.ctx
		self.results: list[BattleResult] = []

	def run(self, probe: Probe) -> BattleResult:
		t0 = time.time()
		try:
			from red_pill.inference import conduct

			kwargs = conduct.request_kwargs(self.resolved, temperature=probe.temperature, max_tokens=probe.max_tokens)
			resp = self._server.chat(
				messages=[
					{"role": "system", "content": probe.system_prompt},
					{"role": "user", "content": probe.user_message},
				],
				**kwargs,
			)
			raw = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or ""
			# El servidor HTTP separa la traza en `reasoning_content`: se
			# recompone al formato canónico para métricas y validadores.
			reasoning = (resp.get("choices") or [{}])[0].get("message", {}).get("reasoning_content") or ""
			if reasoning:
				raw = f"[Start thinking]{reasoning}[End thinking]\n{raw}"
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
		print(f"\n##### {self.model_name} (runtime dedicado, kv={self.kv_type}, ctx={self.ctx}) #####", flush=True)
		print(f"loaded in {self.load_time_s:.1f}s", flush=True)
		for p in probes:
			r = self.run(p)
			print(BattleRunner._fmt_line(r), flush=True)
		return self.results

	def close(self) -> None:
		self._server.stop()


class FastFlowLMRunner:
	"""Runner para el runtime FastFlowLM (NPU XDNA2) — mismo contrato que BattleRunner.

	Sirve vía `flm serve <model_tag>` (OpenAI-compatible en :52625) y ejecuta los
	mismos probes/validadores; registra el decode t/s que reporta FLM en la
	validación (`decode_tps`).
	"""

	FLM_URL = "http://127.0.0.1:52625"

	def __init__(self, model_name: str, startup_timeout: float = 240.0):
		from red_pill.core.model_registry import ModelRegistry
		from red_pill.core.paths import get_data_dir

		profile = ModelRegistry.get_profile(model_name) or {}
		self.model_name = model_name
		self.model_tag = str(profile.get("model_tag") or "")
		if not self.model_tag:
			raise ValueError(f"perfil '{model_name}' sin model_tag para FastFlowLM")
		self._serve_args = [str(a) for a in (profile.get("serve_args") or [])]
		self._request_params = dict(profile.get("request_params") or {})
		self.chat_format = None
		self.resolved = None
		log_dir = get_data_dir() / "runtime_servers"
		log_dir.mkdir(parents=True, exist_ok=True)
		self._log_path = log_dir / f"flm_{model_name}.log"
		t0 = time.time()
		self._proc = None
		self._daemon_was_active = False
		try:
			self._daemon_was_active = os.system("systemctl --user is-active --quiet redpill-llm.service") == 0
			if self._daemon_was_active:
				stop_daemon_if_active()
			with open(self._log_path, "a", encoding="utf-8") as logf:
				logf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} | {' '.join(self._serve_argv())} =====\n")
				logf.flush()
				self._proc = subprocess.Popen(self._serve_argv(), stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
			self._wait_ready(startup_timeout)
			self._warmup()
		except Exception:
			self.close()
			raise
		self.load_time_s = time.time() - t0
		self.results: list[BattleResult] = []

	def _serve_argv(self) -> list[str]:
		return ["flm", "serve", self.model_tag, *self._serve_args]

	def _wait_ready(self, timeout: float) -> None:
		import urllib.request

		deadline = time.time() + timeout
		while time.time() < deadline:
			if self._proc.poll() is not None:
				raise RuntimeError(f"flm serve murió durante el arranque (rc={self._proc.returncode}): {self._log_tail()}")
			try:
				with urllib.request.urlopen(f"{self.FLM_URL}/v1/models", timeout=2) as resp:
					if resp.status == 200:
						return
			except Exception:
				time.sleep(1.0)
		raise RuntimeError(f"timeout esperando a flm serve ({timeout:.0f}s): {self._log_tail()}")

	def _warmup(self) -> None:
		"""Fuerza la carga real del modelo (flm sirve lazy en el primer request).

		Sin warmup un fallo de asignación (XRT ENOMEM) se disfraza de probes
		inválidos; con él, `load_time_s` es real y el error de arranque sale
		con la cola del log.
		"""
		import urllib.request

		body = {"model": self.model_tag, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 4}
		req = urllib.request.Request(
			f"{self.FLM_URL}/v1/chat/completions",
			data=json.dumps(body).encode("utf-8"),
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		try:
			with urllib.request.urlopen(req, timeout=600) as resp:
				resp.read()
		except Exception as e:
			raise RuntimeError(f"warmup de '{self.model_tag}' falló (carga del modelo): {e} — {self._log_tail()}") from e

	def _log_tail(self, lines: int = 15) -> str:
		try:
			content = self._log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
			return "\n".join(content[-lines:]) if content else "(sin log)"
		except Exception:
			return "(log no disponible)"

	def _request_body(self, probe: Probe) -> dict:
		body = {
			"model": self.model_tag,
			"messages": [
				{"role": "system", "content": probe.system_prompt},
				{"role": "user", "content": probe.user_message},
			],
			"max_tokens": probe.max_tokens or 512,
			"temperature": probe.temperature if probe.temperature is not None else 0.7,
		}
		body.update(self._request_params)
		return body

	def run(self, probe: Probe) -> BattleResult:
		import urllib.request

		t0 = time.time()
		decode_tps = None
		body = self._request_body(probe)
		try:
			req = urllib.request.Request(
				f"{self.FLM_URL}/v1/chat/completions",
				data=json.dumps(body).encode("utf-8"),
				headers={"Content-Type": "application/json"},
				method="POST",
			)
			with urllib.request.urlopen(req, timeout=900) as resp:
				data = json.loads(resp.read().decode("utf-8"))
			msg = (data.get("choices") or [{}])[0].get("message", {})
			raw = msg.get("content") or ""
			reasoning = msg.get("reasoning_content") or ""
			if reasoning:
				raw = f"[Start thinking]{reasoning}[End thinking]\n{raw}"
			decode_tps = (data.get("usage") or {}).get("decoding_speed_tps")
		except Exception as e:
			raw = f"<<error: {e}>>"
		dt = time.time() - t0
		validation: dict = {}
		try:
			validation = probe.validator(raw)
		except Exception as e:
			validation = {"valid": False, "error": f"validator crashed: {e}"}
		if decode_tps is not None:
			validation["decode_tps"] = round(float(decode_tps), 1)
		res = BattleResult(model=self.model_name, probe_name=probe.name, latency_s=dt, raw_output=raw, validation=validation)
		self.results.append(res)
		return res

	def run_all(self, probes: list[Probe]) -> list[BattleResult]:
		print(f"\n##### {self.model_name} (runtime=fastflowlm, tag={self.model_tag}) #####", flush=True)
		print(f"loaded in {self.load_time_s:.1f}s", flush=True)
		for p in probes:
			r = self.run(p)
			print(BattleRunner._fmt_line(r), flush=True)
		return self.results

	def close(self) -> None:
		proc = getattr(self, "_proc", None)
		if proc is not None:
			try:
				if proc.poll() is None:
					proc.terminate()
					try:
						proc.wait(timeout=15)
					except subprocess.TimeoutExpired:
						proc.kill()
						proc.wait(timeout=5)
			finally:
				self._proc = None
		if getattr(self, "_daemon_was_active", False):
			self._daemon_was_active = False
			start_daemon_if_inactive()


def runner_for(
	model_name: str,
	*,
	gguf_path: Optional[str] = None,
	n_ctx: Optional[int] = None,
	chat_format: Optional[str] = None,
	n_gpu_layers: int = -1,
	use_mmap: bool = False,
	extra_args: Optional[list[str]] = None,
):
	"""Factory runtime-aware (RFC-HARNESS-003): RuntimeBattleRunner para perfiles
	con runtime declarado no-default; BattleRunner clásico (llama-cpp-python)
	para el resto. El modelo no-default no tiene camino python (fallo limpio)."""
	from red_pill.core.model_registry import ModelRegistry
	from red_pill.core.runtime_registry import RuntimeRegistry

	profile = ModelRegistry.get_profile(model_name) or {}
	runtime_id = profile.get("runtime")
	if runtime_id:
		runtime = RuntimeRegistry.get(str(runtime_id))
		if (runtime or {}).get("kind") == "fastflowlm":
			return FastFlowLMRunner(model_name)
	if runtime_id and runtime_id != RuntimeRegistry.default_id():
		return RuntimeBattleRunner(model_name, n_ctx=n_ctx, extra_args=extra_args)
	if not gguf_path:
		gguf_path = profile.get("model_path")
	if not gguf_path:
		raise ValueError(f"sin gguf_path para '{model_name}' (perfil no resuelto)")
	resolved = None
	try:
		from red_pill.core import model_runtime as mr

		resolved = mr.resolve({"model": model_name})
	except Exception as e:
		print(f"[runner_for] conducta no resoluble para '{model_name}' ({e}) — camino crudo", flush=True)
	stock_ctx = n_ctx or (resolved.resolved_n_ctx() if resolved is not None else 6144)
	return BattleRunner(model_name, gguf_path, chat_format=chat_format, n_ctx=stock_ctx, n_gpu_layers=n_gpu_layers, use_mmap=use_mmap, resolved=resolved)
