"""Minimal in-house agentic minion: local LLM (SIP) + bounded tool loop.

This is NOT a general autonomous agent. It is a small, bounded, in-memory loop
for well-scoped headless tasks driven by the local model (Granite via SIP). The
model emits OpenAI-style tool_calls; we execute them in-process and feed the
results back until the model returns a final answer or the loop hits its cap.

Tools (v1): RedPill-Kernel MCP tools (in-process via the tool registry) + a
bash runner (real shell, sandboxed by cwd + timeout).
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_TOOL_ITERS = 8  # hard cap on model turns (enforced, not just prompted)
MAX_CONSECUTIVE_ERRORS = 3  # give up if the model keeps producing failing tool calls
BASH_TIMEOUT = 60  # seconds per command
_RESULT_CLAMP = 4000  # chars of tool output fed back to the model

TOOLS: List[Dict[str, Any]] = [
	{
		"type": "function",
		"function": {
			"name": "run_bash",
			"description": (
				"Run a shell command via /bin/sh (pipes, redirection and globs work). "
				"Returns JSON with stdout, stderr and returncode. Prefer read-only "
				"inspection unless the task explicitly requires changes."
			),
			"parameters": {
				"type": "object",
				"properties": {"command": {"type": "string", "description": "Command line, e.g. 'ls -1 /path'."}},
				"required": ["command"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "bunker_memory_api",
			"description": (
				"RedPill Bünker memory. Common actions: search_memory_research "
				"(payload {query}), list_workspace_memory / read_workspace_memory / "
				"write_workspace_memory (payload {workspace, filename[, content]}), "
				"get_emotional_sync."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"action": {"type": "string"},
					"payload": {"type": "object"},
				},
				"required": ["action", "payload"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "swarm_orchestrator_api",
			"description": ("RedPill swarm orchestrator. Common actions: check_minion_inbox, run_agent_task, control_bunker."),
			"parameters": {
				"type": "object",
				"properties": {
					"action": {"type": "string"},
					"payload": {"type": "object"},
				},
				"required": ["action", "payload"],
			},
		},
	},
]

SYSTEM_PROMPT = (
	"You are a local minion. You have EXACTLY these tools: "
	"`run_bash` (run a shell command via /bin/sh — pipes, redirection and globs work), "
	"`bunker_memory_api` (RedPill memory: search_memory_research, workspace memory, ...), "
	"`swarm_orchestrator_api` (check_minion_inbox, run_agent_task, control_bunker). "
	"Do NOT invent tools; if none of these fits, answer with NO tool call. "
	"Call ONE tool at a time, read its result, then decide the next step. "
	"When the task is complete, reply with a short final answer and DO NOT call a tool. "
	f"Budget: at most {MAX_TOOL_ITERS} tool calls — be economical and stop early when done."
)


def _clamp(text: str) -> str:
	return text if len(text) <= _RESULT_CLAMP else text[:_RESULT_CLAMP] + "…[truncated]"


def _pretty_result(raw: str) -> str:
	"""Render a raw tool result for the final-answer prompt.

	A run_bash result is a JSON blob ({returncode, stdout, stderr}); show stdout
	plainly — an 8B reads a shell output far better than escaped JSON.
	"""
	try:
		d = json.loads(raw)
	except (TypeError, ValueError):
		return raw
	if isinstance(d, dict) and "stdout" in d:
		out = (d.get("stdout") or "").strip()
		err = (d.get("stderr") or "").strip()
		return out + (f"  [stderr: {err}]" if err else "")
	return raw


def _normalize_native_toolcalls(parsed: List[dict]) -> List[Dict[str, Any]]:
	"""Convert `extract_toolcalls()` output into OpenAI tool_calls.

	The shared parser returns {"function": {"name", "arguments": <dict>}}; the
	loop expects OpenAI shape with a JSON-string arguments field.
	"""
	out: List[Dict[str, Any]] = []
	for i, tc in enumerate(parsed):
		fn = tc.get("function", tc) or {}
		args = fn.get("arguments", {})
		if isinstance(args, str):
			try:
				args = json.loads(args)
			except (TypeError, ValueError):
				args = {}
		# Keep arguments as a MAPPING (not a JSON string): the Granite native
		# template renders assistant tool_calls via `tool_call.arguments|items`,
		# which raises on a string. `_dispatch` accepts both shapes.
		out.append({
			"id": f"call_native_{i}",
			"type": "function",
			"function": {"name": fn.get("name", ""), "arguments": args},
		})
	return out


def _parse_native_toolcalls(text: str) -> List[Dict[str, Any]]:
	"""Recover tool_calls emitted as TEXT.

	Some models use a native Jinja template whose tool-call output llama_cpp does
	NOT parse into structured `tool_calls` — Granite 4.2 emits
	`<tool_call><function=NAME><parameter=k>v</parameter></function></tool_call>`
	as plain content. `model_runtime.extract_toolcalls` knows that format (and the
	qwen/gemma/openai ones); it was defined and tested but never wired in. Empty
	→ no tool call (the caller then treats the content as the final answer).
	"""
	if not text or ("<tool_call" not in text and "<|tool_call|>" not in text):
		return []
	from red_pill.core.model_runtime import extract_toolcalls

	return _normalize_native_toolcalls(extract_toolcalls(text, "auto"))


def _finalize(provider, task: str, tool_results: List[str]) -> str:
	"""Extract a plain-text final answer from the collected tool results.

	The chatml-function-calling handler sometimes returns empty content once it is
	done calling tools. We recover the answer with a plain (no-tools) chatml call
	that hands the model the task + tool output and asks for the answer directly.
	"""
	tool_notes = "\n".join(_pretty_result(r) for r in tool_results)
	msgs = [
		{"role": "system", "content": (
			"You are a local minion. Answer the task using the tool output. "
			"Be concise and give only what was asked."
		)},
		{"role": "user", "content": f"Task: {task}\n\nTool output:\n{tool_notes or '(none)'}\n\nAnswer:"},
	]
	final = provider.chat(msgs)  # no tools -> plain chatml formatter
	return (final.get("content") or "").strip()


async def _dispatch(name: str, args: Dict[str, Any], cwd: Optional[str]) -> str:
	"""Execute one tool call in-process. Returns a string result (errors prefixed ERROR:)."""
	try:
		if name == "run_bash":
			cmd = args.get("command", "")
			if not cmd:
				return "ERROR: run_bash called without a command"
			# Real shell (pipes/redirection work). Sandbox = cwd + timeout. The command
			# originates from OUR local model, not untrusted external input.
			proc = await asyncio.create_subprocess_shell(
				cmd,
				cwd=cwd,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
			)
			try:
				out, err = await asyncio.wait_for(proc.communicate(), timeout=BASH_TIMEOUT)
			except asyncio.TimeoutError:
				proc.kill()
				return f"ERROR: run_bash timed out after {BASH_TIMEOUT}s"
			return _clamp(
				json.dumps(
					{
						"returncode": proc.returncode,
						"stdout": out.decode(errors="replace"),
						"stderr": err.decode(errors="replace"),
					}
				)
			)
		if name in ("bunker_memory_api", "swarm_orchestrator_api"):
			import red_pill.mcp_server  # noqa: F401 — side-effect: registers tool handlers
			from red_pill.registry import registry

			payload = args.get("payload", {})
			if isinstance(payload, str):
				# Some models emit the MCP payload as a JSON string, not an object.
				try:
					payload = json.loads(payload)
				except (TypeError, ValueError):
					payload = {}
			if not isinstance(payload, dict):
				payload = {}
			res = await registry.execute(name, {"action": args.get("action"), "payload": payload})
			return _clamp(res if isinstance(res, str) else json.dumps(res, default=str))
		return f"ERROR: unknown tool {name}"
	except asyncio.TimeoutError:
		return f"ERROR: '{name}' timed out after {BASH_TIMEOUT}s"
	except Exception as e:  # noqa: BLE001 — surface any tool failure back to the model
		return f"ERROR: {name} failed: {e!r}"


async def run_local_minion(task: str, *, cwd: Optional[str] = None, provider_name: str = "sip") -> Dict[str, Any]:
	"""Run a bounded tool loop for `task` on the local model. Returns a result dict."""
	from red_pill.core.providers import ProviderRegistry

	provider = ProviderRegistry.get_inference_provider(provider_name)
	loop = asyncio.get_event_loop()

	messages: List[Dict[str, Any]] = [
		{"role": "system", "content": SYSTEM_PROMPT},
		{"role": "user", "content": task},
	]
	consecutive_errors = 0
	tool_calls_made = 0
	tool_results: List[str] = []

	for step in range(MAX_TOOL_ITERS):
		msg = await loop.run_in_executor(None, lambda: provider.chat(messages, tools=TOOLS, tool_choice="auto"))
		tool_calls = msg.get("tool_calls") or []
		if not tool_calls:
			# Native-text tool call (e.g. Granite 4.2 template) → structured.
			native = _parse_native_toolcalls(msg.get("content") or "")
			if native:
				msg = {**msg, "tool_calls": native, "content": None}
				tool_calls = native
		messages.append(msg)

		if not tool_calls:
			answer = (msg.get("content") or "").strip()
			if answer:
				from red_pill.core.model_runtime import extract_thinking

				answer = extract_thinking(answer)[1]
			if not answer:
				# Handler returned empty when done; recover the answer in plain chatml.
				answer = await loop.run_in_executor(None, lambda: _finalize(provider, task, tool_results))
			return {
				"ok": True,
				"answer": answer,
				"steps": step,
				"used_tools": tool_calls_made > 0,
				"tool_calls": tool_calls_made,
				"messages": messages,
			}

		for tc in tool_calls:
			fn = tc.get("function", {})
			name = fn.get("name", "")
			raw_args = fn.get("arguments")
			if isinstance(raw_args, dict):
				args = raw_args
			else:
				try:
					args = json.loads(raw_args or "{}")
				except (TypeError, ValueError):
					args = {}
			logger.info("[local-minion] step %d: %s(%s)", step, name, args)
			result = await _dispatch(name, args, cwd)
			tool_calls_made += 1
			tool_results.append(result)
			consecutive_errors = consecutive_errors + 1 if result.startswith("ERROR") else 0
			# Feed the result back as a USER message. The chatml-function-calling
			# handler (llama_cpp 0.3.31) has NO branch for role="tool" and drops it
			# silently — the model would then repeat the call blindly. A user turn
			# is rendered by every handler and keeps the loop grounded.
			messages.append({
				"role": "user",
				"content": (
					f"Tool `{name}` result:\n{result}\n\n"
					"If this is enough to answer the task, reply with the final answer "
					"now and DO NOT call a tool."
				),
			})

		if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
			return {
				"ok": False,
				"answer": "mala tarde: too many consecutive tool errors",
				"steps": step,
				"used_tools": tool_calls_made > 0,
				"tool_calls": tool_calls_made,
				"messages": messages,
			}

	return {
		"ok": False,
		"answer": "mala tarde: hit the tool-call cap without finishing",
		"steps": MAX_TOOL_ITERS,
		"used_tools": tool_calls_made > 0,
		"tool_calls": tool_calls_made,
		"messages": messages,
	}
