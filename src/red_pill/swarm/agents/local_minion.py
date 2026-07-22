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

MAX_TOOL_ITERS = 8          # hard cap on model turns (enforced, not just prompted)
MAX_CONSECUTIVE_ERRORS = 3  # give up if the model keeps producing failing tool calls
BASH_TIMEOUT = 60           # seconds per command
_RESULT_CLAMP = 4000        # chars of tool output fed back to the model

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
			"description": (
				"RedPill swarm orchestrator. Common actions: check_minion_inbox, "
				"run_agent_task, control_bunker."
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
]

SYSTEM_PROMPT = (
	"You are a local minion. Complete the user's task using the provided tools. "
	"Call ONE tool at a time, read its result, then decide the next step. "
	"When the task is complete, reply with a short final answer and DO NOT call a tool. "
	f"Budget: at most {MAX_TOOL_ITERS} tool calls — be economical and stop early when done."
)


def _clamp(text: str) -> str:
	return text if len(text) <= _RESULT_CLAMP else text[:_RESULT_CLAMP] + "…[truncated]"


def _finalize(provider, task: str, messages: List[Dict[str, Any]]) -> str:
	"""Extract a plain-text final answer.

	The chatml-function-calling handler sometimes returns empty content once it is
	done calling tools. We recover the answer with a plain (no-tools) chatml call
	that hands the model the task + tool results and asks for the answer directly.
	"""
	tool_notes = "\n".join(
		f"- {m.get('content', '')}" for m in messages if m.get("role") == "tool"
	)
	msgs = [
		{"role": "system", "content": "Answer the user's task using the tool results provided. Be concise."},
		{"role": "user", "content": f"Task: {task}\n\nTool results:\n{tool_notes or '(none)'}\n\nGive the final answer now."},
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
				cmd, cwd=cwd,
				stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
			)
			try:
				out, err = await asyncio.wait_for(proc.communicate(), timeout=BASH_TIMEOUT)
			except asyncio.TimeoutError:
				proc.kill()
				return f"ERROR: run_bash timed out after {BASH_TIMEOUT}s"
			return _clamp(json.dumps({
				"returncode": proc.returncode,
				"stdout": out.decode(errors="replace"),
				"stderr": err.decode(errors="replace"),
			}))
		if name in ("bunker_memory_api", "swarm_orchestrator_api"):
			import red_pill.mcp_server  # noqa: F401 — side-effect: registers tool handlers
			from red_pill.registry import registry
			payload = {"action": args.get("action"), "payload": args.get("payload", {})}
			res = await registry.execute(name, payload)
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

	for step in range(MAX_TOOL_ITERS):
		msg = await loop.run_in_executor(
			None, lambda: provider.chat(messages, tools=TOOLS, tool_choice="auto")
		)
		messages.append(msg)
		tool_calls = msg.get("tool_calls") or []

		if not tool_calls:
			answer = (msg.get("content") or "").strip()
			if not answer:
				# Handler returned empty when done; recover the answer in plain chatml.
				answer = await loop.run_in_executor(None, lambda: _finalize(provider, task, messages))
			return {"ok": True, "answer": answer, "steps": step, "messages": messages}

		for tc in tool_calls:
			fn = tc.get("function", {})
			name = fn.get("name", "")
			try:
				args = json.loads(fn.get("arguments") or "{}")
			except (TypeError, ValueError):
				args = {}
			logger.info("[local-minion] step %d: %s(%s)", step, name, args)
			result = await _dispatch(name, args, cwd)
			consecutive_errors = consecutive_errors + 1 if result.startswith("ERROR") else 0
			messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result})

		if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
			return {"ok": False, "answer": "mala tarde: too many consecutive tool errors", "steps": step, "messages": messages}

	return {"ok": False, "answer": "mala tarde: hit the tool-call cap without finishing", "steps": MAX_TOOL_ITERS, "messages": messages}
