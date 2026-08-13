#!/usr/bin/env python3
"""calibrate_bakeoff.py — Verify llama-cpp-python (Python bindings) and llama.cpp
binary (used in production via SIP) produce equivalent outputs for the same probe.

Why: the bake-off harnesses use llama-cpp-python for ergonomics and to avoid
opening a SIP port. If the two backends diverge (chat template, stop tokens,
sampling), bake-off results won't predict production behaviour. This script
runs the same probe through both and compares the *structural* JSON output
(not token-by-token).

Usage:
  python scripts/calibrate_bakeoff.py <model_name> <path/to.gguf> [probe_set]

probe_set is one of: smoke, distill (default: smoke).
  smoke   — single short prompt "di hola" — fast, checks basic load parity.
  distill — 3 distillation probes — slower, checks JSON/dict structure parity.

Exit code 0 = match (within tolerance), 1 = mismatch, 2 = error.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_battle_lib import BattleRunner, Probe, start_daemon_if_inactive, stop_daemon_if_active

LLAMA_CLI = "/home/joan/Documents/IA/sharing/3rdparty/llama_official/build/bin/llama-cli"

PROBES_SMOKE = [
	Probe(
		name="smoke",
		system_prompt="You are a concise assistant.",
		user_message="di hola",
		validator=lambda raw: {"len": len(raw.strip()), "head": raw.strip()[:60]},
		max_tokens=30,
		temperature=0.0,
	),
]

PROBES_DISTILL = [
	Probe(
		name="decision",
		system_prompt=open("/home/joan/Documents/IA/sharing/src/red_pill/metabolism/prompts/distiller_v3_voice.txt")
		.read()
		.replace("{agent_name}", "Aleth")
		.replace("{operator_name}", "Joan"),
		user_message=(
			"USER: ¿migramos a Postgres o seguimos con SQLite? el volumen "
			"no justifica aún un motor nuevo\n\nASSISTANT: seguimos con SQLite "
			"por ahora; añadir Postgres traería más operaciones de las que "
			"resuelve\n\nUSER: de acuerdo, lo dejamos así y lo revisamos cuando crezca"
		),
		validator=lambda raw: _validate_distill(raw),
		max_tokens=450,
		temperature=0.1,
	),
]


def _validate_distill(raw: str) -> dict:
	"""Structural check: must contain a parseable JSON object with summary."""
	m = re.search(r"\{[\s\S]*\}", raw)
	if not m:
		return {"valid": False, "reason": "no JSON"}
	try:
		obj = json.loads(m.group(0))
	except Exception as e:
		return {"valid": False, "reason": f"JSON parse: {e}"}
	required = {"summary", "emotion", "intensity", "category"}
	missing = required - set(obj.keys())
	if missing:
		return {"valid": False, "reason": f"missing keys: {missing}"}
	return {"valid": True, "summary_head": obj["summary"][:80], "emotion": obj["emotion"]}


def _run_python(model_name: str, gguf: str, probes: list[Probe]) -> list[dict]:
	results = []
	runner = BattleRunner(model_name, gguf, chat_format=None)
	for p in probes:
		r = runner.run(p)
		results.append({"probe": p.name, "raw": r.raw_output, "validation": r.validation, "latency_s": r.latency_s})
	runner.close()
	return results


def _run_cli(model_name: str, gguf: str, probes: list[Probe], n_gpu_layers: int = -1) -> list[dict]:
	results = []
	for p in probes:
		# Build a single-string prompt: system + user, llama-cli style.
		# Use the -sys flag for system message and -p for user prompt.
		cmd = [
			LLAMA_CLI,
			"-m",
			gguf,
			"-sys",
			p.system_prompt,
			"-p",
			p.user_message,
			"-n",
			str(p.max_tokens),
			"--temp",
			str(p.temperature),
			"-ngl",
			str(n_gpu_layers),
			"-c",
			"6144",
			"--no-display-prompt",
			"--log-disable",
		]
		t0 = time.time()
		proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
		dt = time.time() - t0
		if proc.returncode != 0:
			results.append(
				{
					"probe": p.name,
					"raw": f"<<cli error: {proc.stderr[:200]}>>",
					"validation": {"valid": False, "reason": "cli failed"},
					"latency_s": dt,
				}
			)
			continue
		raw = proc.stdout.strip()
		validation = {}
		try:
			validation = p.validator(raw)
		except Exception as e:
			validation = {"valid": False, "error": f"validator crashed: {e}"}
		results.append({"probe": p.name, "raw": raw, "validation": validation, "latency_s": dt})
	return results


def _compare(py_results: list[dict], cli_results: list[dict]) -> tuple[bool, list[str]]:
	"""Structural comparison, not exact string match."""
	notes = []
	if len(py_results) != len(cli_results):
		return False, [f"count mismatch: py={len(py_results)} cli={len(cli_results)}"]
	for py, cli in zip(py_results, cli_results):
		if py["probe"] != cli["probe"]:
			return False, [f"probe name mismatch: {py['probe']} vs {cli['probe']}"]
		py_v = py["validation"]
		cli_v = cli["validation"]
		# Both must be valid (or both invalid for the same reason).
		py_ok = py_v.get("valid")
		cli_ok = cli_v.get("valid")
		if py_ok != cli_ok:
			notes.append(f"[{py['probe']}] valid mismatch: py={py_ok} cli={cli_ok} py_reason={py_v.get('reason')} cli_reason={cli_v.get('reason')}")
			continue
		if py_ok is False:
			# Both failed — check if reason is similar.
			py_r = py_v.get("reason", "")
			cli_r = cli_v.get("reason", "")
			if py_r and cli_r and not _similar_reason(py_r, cli_r):
				notes.append(f"[{py['probe']}] both invalid, different reasons: py={py_r!r} cli={cli_r!r}")
			continue
		# Both valid — compare key structural fields if present.
		for k in ("emotion", "lang", "category", "tool"):
			if k in py_v and k in cli_v and py_v[k] != cli_v[k]:
				notes.append(f"[{py['probe']}] {k} mismatch: py={py_v[k]!r} cli={cli_v[k]!r}")
		# Summary heads don't need to match exactly — log similarity score.
		if "summary_head" in py_v and "summary_head" in cli_v:
			overlap = _word_overlap(py_v["summary_head"], cli_v["summary_head"])
			notes.append(f"[{py['probe']}] summary head overlap={overlap:.0%} py={py_v['summary_head'][:50]!r} cli={cli_v['summary_head'][:50]!r}")
	mismatch = [n for n in notes if "mismatch" in n]
	return (len(mismatch) == 0), notes


def _similar_reason(a: str, b: str) -> bool:
	# Loose: same first word or share a key token.
	tokens_a = set(re.findall(r"\w+", a.lower()))
	tokens_b = set(re.findall(r"\w+", b.lower()))
	return bool(tokens_a & tokens_b)


def _word_overlap(a: str, b: str) -> float:
	ta = set(re.findall(r"\w+", a.lower())) - {"the", "a", "y", "de", "la", "el", "que"}
	tb = set(re.findall(r"\w+", b.lower())) - {"the", "a", "y", "de", "la", "el", "que"}
	if not ta or not tb:
		return 0.0
	return len(ta & tb) / len(ta | tb)


def main(model_name: str, gguf: str, probe_set: str = "smoke"):
	probes = PROBES_SMOKE if probe_set == "smoke" else PROBES_DISTILL
	stop_daemon_if_active()
	try:
		print(f"=== calibrate {model_name} ({probe_set}) ===", flush=True)
		print("[py] running...", flush=True)
		py_results = _run_python(model_name, gguf, probes)
		print("[cli] running...", flush=True)
		cli_results = _run_cli(model_name, gguf, probes)
		ok, notes = _compare(py_results, cli_results)
		print(f"\n=== result: {'MATCH' if ok else 'MISMATCH'} ===", flush=True)
		for n in notes:
			print(f"  {n}", flush=True)
		# Persist for diffing later.
		out = Path(__file__).resolve().parents[1] / "docs" / "BENCHMARKS" / f"CALIBRATION_{model_name}_{probe_set}_{int(time.time())}.json"
		out.parent.mkdir(parents=True, exist_ok=True)
		out.write_text(
			json.dumps(
				{
					"model": model_name,
					"probe_set": probe_set,
					"ok": ok,
					"python": py_results,
					"cli": cli_results,
					"notes": notes,
				},
				ensure_ascii=False,
				indent=2,
			)
		)
		print(f"\n→ wrote {out}", flush=True)
		sys.exit(0 if ok else 1)
	finally:
		start_daemon_if_inactive()


if __name__ == "__main__":
	if len(sys.argv) < 3:
		print(__doc__, file=sys.stderr)
		sys.exit(2)
	main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "smoke")
