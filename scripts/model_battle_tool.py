#!/usr/bin/env python3
"""model_battle_tool.py — Tool / function calling bake-off.

Measures how well a model emits valid tool_calls for representative scenarios:

  1. simple     — single tool, clear intent, model should emit one tool_call.
  2. multi_sel  — 3 tools available, pick the right one (no false-positive).
  3. json_args  — complex typed args (list[str], int, ISO8601) parsed correctly.
  4. no_tool    — model should NOT emit tool_calls; conversational reply.
  5. multi_step — chain of tool calls (plan + execute).

Mirrors the OpenAI tool_calls format the daemon already uses via
`minion_chat_format: chatml-function-calling`. Per-probe results written to
docs/BENCHMARKS/TOOL_<MODEL>_<DATE>.jsonl.

Usage:
  python scripts/model_battle_tool.py <model_name> <path/to.gguf> [chat_format]

Examples:
  python scripts/model_battle_tool.py granite_8b \\
      /home/joan/.local/share/red-pill/models/Granite-4.1-8B-Q4_K_M.gguf \\
      chatml-function-calling
  python scripts/model_battle_tool.py smollm3_3b \\
      /home/joan/.local/share/red-pill/models/SmolLM3-3B-Q4_K_M.gguf
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Allow `python scripts/model_battle_tool.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_battle_lib import (
	BattleResult,
	BattleRunner,
	Probe,
	start_daemon_if_inactive,
	stop_daemon_if_active,
	write_jsonl,
)

# ── Tool definitions (OpenAI-style) ──────────────────────────────────────────

WEATHER_TOOL = {
	"type": "function",
	"function": {
		"name": "get_weather",
		"description": "Get current weather for a city.",
		"parameters": {
			"type": "object",
			"properties": {
				"city": {"type": "string"},
				"unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
			},
			"required": ["city"],
		},
	},
}

SEARCH_TOOL = {
	"type": "function",
	"function": {
		"name": "search_files",
		"description": "Search files matching a query in the repository.",
		"parameters": {
			"type": "object",
			"properties": {
				"query": {"type": "string"},
				"path": {"type": "string"},
			},
			"required": ["query"],
		},
	},
}

SEND_MSG_TOOL = {
	"type": "function",
	"function": {
		"name": "send_message",
		"description": "Send a chat message to a person.",
		"parameters": {
			"type": "object",
			"properties": {
				"to": {"type": "string"},
				"body": {"type": "string"},
			},
			"required": ["to", "body"],
		},
	},
}

SCHEDULE_TOOL = {
	"type": "function",
	"function": {
		"name": "schedule_meeting",
		"description": "Schedule a meeting on the calendar.",
		"parameters": {
			"type": "object",
			"properties": {
				"title": {"type": "string"},
				"when": {"type": "string", "description": "ISO 8601 datetime"},
				"attendees": {"type": "array", "items": {"type": "string"}},
				"duration_min": {"type": "integer"},
			},
			"required": ["title", "when", "attendees"],
		},
	},
}

LISTDIR_TOOL = {
	"type": "function",
	"function": {
		"name": "list_dir",
		"description": "List the contents of a directory.",
		"parameters": {
			"type": "object",
			"properties": {"path": {"type": "string"}},
			"required": ["path"],
		},
	},
}

GREP_TOOL = {
	"type": "function",
	"function": {
		"name": "grep",
		"description": "Search a regex pattern in files.",
		"parameters": {
			"type": "object",
			"properties": {
				"pattern": {"type": "string"},
				"path": {"type": "string"},
			},
			"required": ["pattern"],
		},
	},
}

# ── Probes ───────────────────────────────────────────────────────────────────

SYS_GENERIC = "You are a helpful assistant. Use the provided tools when appropriate."


def _build_system_prompt(tools: list[dict]) -> str:
	# llama-cpp's chat-completion `tools` kwarg handles tool serialization; we
	# pass tools via the messages path only if we want to test the raw prompt
	# path. Default: tools are passed via `create_chat_completion(tools=...)`.
	return SYS_GENERIC


PROBES = [
	Probe(
		name="simple",
		system_prompt=SYS_GENERIC,
		user_message="USER: ¿qué tiempo hace en Barcelona?",
		validator=lambda out: _validate_tool_call(out, expected_name="get_weather", expected_args_substr=["Barcelona"]),
	),
	Probe(
		name="multi_sel",
		system_prompt=SYS_GENERIC,
		user_message="USER: busca el archivo config.yaml en mi repo",
		validator=lambda out: _validate_tool_call(
			out, expected_name="search_files", expected_args_substr=["config.yaml"], forbidden_names=["get_weather", "send_message"]
		),
	),
	Probe(
		name="json_args",
		system_prompt=SYS_GENERIC,
		user_message=("USER: apunta una reunión mañana a las 10 con Ana y Beti durante media hora"),
		validator=lambda out: _validate_schedule_meeting(out),
	),
	Probe(
		name="no_tool",
		system_prompt=SYS_GENERIC,
		user_message="USER: háblame de la diferencia entre SQL y NoSQL",
		validator=lambda out: _validate_no_tool(out),
	),
	Probe(
		name="multi_step",
		system_prompt=SYS_GENERIC,
		user_message="USER: encuentra todas las funciones async en src/",
		validator=lambda out: _validate_multi_step(out),
	),
]

# Tools available per probe (parallel to PROBES list).
TOOLS_PER_PROBE = [
	[WEATHER_TOOL],
	[WEATHER_TOOL, SEARCH_TOOL, SEND_MSG_TOOL],
	[SCHEDULE_TOOL],
	[WEATHER_TOOL, SEARCH_TOOL],  # tools available but model shouldn't call them
	[LISTDIR_TOOL, GREP_TOOL],
]


# ── Validators ───────────────────────────────────────────────────────────────


def _try_parse_tool_call(raw: str) -> dict | None:
	"""Robustly find a tool_call JSON object in the raw output.

	llama-cpp with `chatml-function-calling` may emit either:
	  - a single JSON object with {name, arguments}
	  - raw tool_calls array (OpenAI style)
	  - free text that needs to be regex-extracted
	"""
	# Try direct JSON parse first.
	try:
		obj = json.loads(raw.strip())
		if isinstance(obj, dict) and ("name" in obj or "tool_calls" in obj):
			return obj
	except Exception:
		pass
	# Try extracting first JSON object/array.
	m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
	if not m:
		return None
	candidate = m.group(1)
	try:
		obj = json.loads(candidate)
	except Exception:
		return None
	if isinstance(obj, dict):
		return obj
	if isinstance(obj, list) and obj and isinstance(obj[0], dict):
		return obj[0]
	return None


def _validate_tool_call(
	raw: str, expected_name: str, expected_args_substr: list[str] | None = None, forbidden_names: list[str] | None = None
) -> dict:
	obj = _try_parse_tool_call(raw)
	if obj is None:
		return {"valid": False, "reason": "no JSON parseable"}
	# Normalize: support OpenAI shape {tool_calls: [{function: {name, arguments}}]}
	name = obj.get("name") or (obj.get("function") or {}).get("name") or ((obj.get("tool_calls") or [{}])[0].get("function") or {}).get("name")
	if forbidden_names and name in forbidden_names:
		return {"valid": False, "reason": f"wrong tool: {name}", "tool": name}
	if name != expected_name:
		return {"valid": False, "reason": f"expected {expected_name}, got {name or '?'}", "tool": name}
	args_raw = (
		obj.get("arguments")
		or (obj.get("function") or {}).get("arguments")
		or ((obj.get("tool_calls") or [{}])[0].get("function") or {}).get("arguments")
		or obj
	)
	if isinstance(args_raw, str):
		try:
			args = json.loads(args_raw)
		except Exception:
			args = {}
	elif isinstance(args_raw, dict):
		args = args_raw
	else:
		args = {}
	missing_subs = []
	if expected_args_substr:
		flat = json.dumps(args, ensure_ascii=False).lower()
		for s in expected_args_substr:
			if s.lower() not in flat:
				missing_subs.append(s)
	if missing_subs:
		return {"valid": False, "reason": f"missing args: {missing_subs}", "tool": name, "args": args}
	return {"valid": True, "tool": name, "args": args}


def _validate_schedule_meeting(raw: str) -> dict:
	obj = _try_parse_tool_call(raw)
	if obj is None:
		return {"valid": False, "reason": "no JSON parseable"}
	name = obj.get("name") or (obj.get("function") or {}).get("name")
	if name != "schedule_meeting":
		return {"valid": False, "reason": f"expected schedule_meeting, got {name or '?'}"}
	args_raw = obj.get("arguments") or (obj.get("function") or {}).get("arguments")
	if isinstance(args_raw, str):
		try:
			args = json.loads(args_raw)
		except Exception:
			return {"valid": False, "reason": "arguments not JSON"}
	else:
		args = args_raw or {}
	problems = []
	if not isinstance(args.get("attendees"), list) or len(args.get("attendees", [])) < 2:
		problems.append("attendees < 2")
	if not isinstance(args.get("duration_min"), int):
		problems.append("duration_min not int")
	if not isinstance(args.get("when"), str) or "T" not in args.get("when", ""):
		problems.append("when not ISO8601-ish")
	if problems:
		return {"valid": False, "reason": "; ".join(problems), "args": args}
	return {"valid": True, "tool": "schedule_meeting", "args": args}


def _validate_no_tool(raw: str) -> dict:
	obj = _try_parse_tool_call(raw)
	if obj is not None and (obj.get("name") or obj.get("tool_calls")):
		return {"valid": False, "reason": "emitted tool_call when shouldn't"}
	# Expect non-trivial conversational reply.
	if len(raw.strip()) < 30:
		return {"valid": False, "reason": "reply too short"}
	return {"valid": True, "reply_chars": len(raw.strip())}


def _validate_multi_step(raw: str) -> dict:
	# Look for at least 2 distinct tool calls (listdir + grep typical).
	calls = re.findall(r'"name"\s*:\s*"(list_dir|grep)"', raw)
	if len(set(calls)) >= 2:
		return {"valid": True, "tools_called": list(set(calls))}
	# Fallback: single tool_call is acceptable if it's grep (the final step).
	obj = _try_parse_tool_call(raw)
	if obj:
		name = obj.get("name") or (obj.get("function") or {}).get("name")
		if name == "grep":
			return {"valid": True, "tools_called": ["grep"], "partial": True}
	return {"valid": False, "reason": "no multi-tool chain detected"}


# ── Main ─────────────────────────────────────────────────────────────────────


def main(model_name: str, gguf_path: str, chat_format: str | None = None):
	stop_daemon_if_active()
	try:
		runner = BattleRunner(model_name, gguf_path, chat_format=chat_format)
		results = []
		# Run probes manually because tools vary per probe (BattleRunner.run_all
		# doesn't pass `tools=`). We patch by re-using the runner's llm.
		print(f"\n##### {model_name} (chat_format={chat_format or 'auto'}) #####", flush=True)
		print(f"loaded in {runner.load_time_s:.1f}s", flush=True)
		import time as _t

		for probe, tools in zip(PROBES, TOOLS_PER_PROBE):
			t0 = _t.time()
			try:
				out = runner.llm.create_chat_completion(
					messages=[
						{"role": "system", "content": probe.system_prompt},
						{"role": "user", "content": probe.user_message},
					],
					tools=tools,
					temperature=probe.temperature,
					max_tokens=probe.max_tokens,
				)
				raw = out["choices"][0]["message"].get("content") or ""
				# If the chat-format wraps tool_calls separately, capture them too.
				tcs = out["choices"][0]["message"].get("tool_calls") or []
				if tcs and not raw:
					raw = json.dumps(
						[{"name": (tc.get("function") or {}).get("name"), "arguments": (tc.get("function") or {}).get("arguments")} for tc in tcs],
						ensure_ascii=False,
					)
			except Exception as e:
				raw = f"<<error: {e}>>"
			dt = _t.time() - t0
			validation = {}
			try:
				validation = probe.validator(raw)
			except Exception as e:
				validation = {"valid": False, "error": f"validator crashed: {e}"}
			r = BattleResult(model=model_name, probe_name=probe.name, latency_s=dt, raw_output=raw, validation=validation)
			results.append(r)
			print(BattleRunner._fmt_line(r), flush=True)
		runner.close()
	finally:
		start_daemon_if_inactive()
	# Persist JSONL alongside other benchmarks.
	date = datetime.now().strftime("%Y%m%d-%H%M")
	out_path = Path(__file__).resolve().parents[1] / "docs" / "BENCHMARKS" / f"TOOL_{model_name}_{date}.jsonl"
	write_jsonl(results, out_path)
	print(f"\n→ wrote {out_path}", flush=True)


if __name__ == "__main__":
	if len(sys.argv) < 3:
		print(__doc__, file=sys.stderr)
		sys.exit(1)
	main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
