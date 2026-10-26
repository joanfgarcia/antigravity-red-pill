import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

import red_pill.config as cfg
from red_pill import __model__ as MODEL_NAME
from red_pill import __version__ as CORE_VERSION
from red_pill.cli import switch_skin
from red_pill.core.paths import get_config_dir, get_state_dir
from red_pill.memory import MemoryManager
from red_pill.registry import registry
from red_pill.soul import SoulManager
from red_pill.swarm.agents.agent import AgentMinion
from red_pill.swarm.agents.compressor import CompressorMinion
from red_pill.swarm.agents.keymaker import KeymakerMinion
from red_pill.swarm.agents.oracle import OracleMinion
from red_pill.swarm.agents.smith import SmithMinion
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.telemetry import HardwareSentinel, get_telemetry_report, sentinel
from red_pill.utils.mystique import mystique_engine
from red_pill.utils.tone_analyzer import get_current_sync_state

logger = logging.getLogger(__name__)

# Identidad de confianza inyectada por el proxy del MCP compartido (AD-018).
# El backend es un único proceso para N clientes; el proxy de cada instancia
# adjunta la identidad del arnés (no del modelo) en cada petición HTTP. El
# middleware de `mcp_shared` la publica en este contextvar.
_shared_identity_var: ContextVar[Optional[dict]] = ContextVar("redpill_shared_identity", default=None)


def _safe_create_task(coro, *, name: str = "background"):
	"""Create an asyncio task with proper exception handling.

	Prevents unhandled task exceptions from crashing the MCP event loop.
	This is the root cause of the EOF disconnection bug: bare asyncio.create_task()
	calls that raise exceptions silently kill the event loop in Python 3.12+.
	"""

	async def _wrapped():
		try:
			await coro
		except Exception as e:
			logger.error(f"Background task '{name}' failed (safely caught): {e}", exc_info=True)

	return asyncio.create_task(_wrapped(), name=f"rp-{name}")


# v6.0.1: Robust Script Resolution
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def GET_PYTHON() -> str:
	"""Returns the path to the project's virtual environment python if it exists, else system python."""
	venv_python = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
	if os.path.exists(venv_python):
		return venv_python
	return sys.executable


# Initialize the Sovereign MCP Server
server = Server("RedPill-Kernel")


@server.list_prompts()
async def handle_list_prompts() -> List[types.Prompt]:
	return [types.Prompt(name="Control-Panel", description="Display the Sovereign Control Panel with hardware and admin options.", arguments=[])]


@server.get_prompt()
async def handle_get_prompt(name: str, arguments: Optional[Dict[str, Any]]) -> types.GetPromptResult:
	if name == "Control-Panel":
		return types.GetPromptResult(
			description="Red Pill Sovereign Control Panel",
			messages=[
				types.PromptMessage(
					role="user",
					content=types.TextContent(
						type="text", text="Show me the Bünker Dashboard and the administrative controls for the Red Pill Protocol."
					),
				)
			],
		)
	raise ValueError(f"Unknown prompt: {name}")


@registry.register_action(
	parent="metabolism_health_api",
	action="get_hardware_status",
	description="Get real-time CPU, GPU (RTX 5070), and NPU telemetry.",
	schema={"type": "object", "properties": {}},
)
async def handle_get_hardware_status(arguments: Dict[str, Any]):
	# Reuse common logic below
	return [types.TextContent(type="text", text=get_telemetry_report())]


@registry.register_action(
	parent="metabolism_health_api",
	action="get_dashboard",
	description="Get a high-fidelity visual dashboard of the Red Pill ecosystem.",
	schema={"type": "object", "properties": {}},
)
async def handle_get_dashboard(arguments: Dict[str, Any]):
	stats = sentinel.get_stats()
	gpu_temp = max([g.get("temp", 0) for g in stats["gpu"]]) if stats["gpu"] else 0
	cpu_temp = stats["cpu"].get("temp") or 0
	max_temp = max(gpu_temp, cpu_temp)
	thermal_state = "🔥 CRITICAL" if max_temp > 80 else "🟢 OPTIMAL"
	cpu_temp_display = f" @ {stats['cpu'].get('temp')}°C" if stats["cpu"].get("temp") is not None else ""
	dashboard = f"""
## 🔴 BÜNKER SOVEREIGN DASHBOARD v6.0 (ACE-CAL)
---
### 🔍 Agentic Discoverability
If you are an AI Agent:
1. **B760-Registry**: All internal tools are now dynamically discovered via `list_tools`.
2. **Auto-Discovery**: Capability sync is enforced at every heartbeat.
3. **Sound of Silence**: Tabs only, no noise.

### 🛠️ Hardware Asymmetry
- **CPU Load**: {HardwareSentinel._get_bar(stats["cpu"]["usage_percent"], 20)}{cpu_temp_display}
- **RAM Usage**: {HardwareSentinel._get_bar(stats["memory"]["percent"], 20)} ({stats["memory"]["available_gb"]}GB Free)

### ⚡ Accelerated Nodes
"""
	for g in stats["gpu"]:
		dashboard += f"- **[{g.get('type', 'GPU')}] {g['name']}**: {HardwareSentinel._get_bar(g.get('usage', 0), 15)} | {g.get('temp', 'N/A')}°C\n"
	dashboard += f"\n- **[NPU] {stats['npu'].get('name', 'NPU')}**: {stats['npu']['status']}\n"
	dashboard += f"\n**Thermal State**: {thermal_state}\n"

	try:
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		qm = CognitiveQueueManager()
		with qm._get_connection() as conn:
			tasks = conn.execute(
				"SELECT id, source, status, priority, attempts, updated_at FROM cognitive_tasks WHERE status IN ('PROCESSING', 'PENDING', 'FRUSTRATED')"
			).fetchall()
		dashboard += "\n### 📋 Active Queue Tasks\n"
		if tasks:
			for t in tasks:
				dashboard += (
					f"- **{t['id'][:8]}** | {t['source']} | {t['status']} | Prio: {t['priority']} | Att: {t['attempts']} | Upd: {t['updated_at']}\n"
				)
		else:
			dashboard += "No active or pending tasks in queue.\n"
	except Exception as q_err:
		dashboard += f"\nQueue Diagnostic Error: {q_err}\n"

	return [types.TextContent(type="text", text=dashboard.strip())]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="control_bunker",
	description="Execute administrative CLI commands (rotate, mode, backup, purge, sleep).",
	schema={
		"type": "object",
		"properties": {
			"command": {"type": "string", "enum": ["rotate", "backup", "mode", "status", "purge", "sleep", "export"]},
			"value": {"type": "string"},
		},
		"required": ["command"],
	},
)
async def handle_control_bunker(arguments: Dict[str, Any]):
	cmd = arguments.get("command", "")
	val = arguments.get("value", "")
	if cmd == "mode":
		output = switch_skin(val)
	elif cmd == "rotate":
		from scripts.rotate_keys import rotate

		rotate()
		output = "Qdrant API Key rotated and service restarted."
	elif cmd == "backup":
		SoulManager().full_backup()
		output = "Total Soul Backup executed successfully."
	elif cmd == "export":
		success = await SoulManager().export_soul()
		if success:
			output = "Lean Soul Kit exported and transmitted to Cloud Haven."
		else:
			output = "[❌ CLOUD_FAILURE] Soul Kit exported locally but transmission failed. OAuth2 token likely expired or revoked."
	elif cmd == "purge":
		# SEC-PURGE-001: Require explicit opt-in via env var to prevent accidental data loss.
		# Set ALLOW_PURGE=true in .env only when intentionally running a purge operation.
		if os.environ.get("ALLOW_PURGE", "").lower() != "true":
			output = (
				"[PURGE BLOCKED] SEC-PURGE-001: Production safeguard active. "
				"Set ALLOW_PURGE=true in your environment to authorize this operation. "
				"This prevents accidental data loss from tests or unintended calls."
			)
		else:
			manager = MemoryManager()
			for coll in cfg.METABOLISM_AUTO_COLLECTIONS:
				manager.purge_dead_memories(coll.strip())
			output = "Gran Purge protocol executed."
	elif cmd == "status":
		output = get_telemetry_report()
	elif cmd == "sleep":
		from red_pill.core.providers import ProviderRegistry, SipInferenceProvider

		ProviderRegistry.register_inference_provider("sip", SipInferenceProvider(socket_path=cfg.SIP_SOCKET_PATH))

		from red_pill.metabolism.sleep import perform_sleep_cycle

		count = perform_sleep_cycle(MemoryManager(), mode=val if val in ["lazy", "deep"] else "lazy")
		output = f"Sleep cycle complete. {count} engrams consolidated."
	else:
		output = f"Unknown command: {cmd}"
	return [types.TextContent(type="text", text=f"Action Result: {cmd}\n\n{output}")]


@registry.register_action(
	parent="bunker_memory_api",
	action="memorize_interaction",
	description="Record a dialogue pair into the fast interaction buffer (anti-amnesia).",
	schema={
		"type": "object",
		"properties": {
			"prompt": {"type": "string"},
			"response": {"type": "string"},
			"role": {"type": "string", "default": "assistant"},
			"workdir": {"type": "string", "description": "Directorio del proyecto (default: cwd del server MCP)."},
			"affinity": {"type": "array", "items": {"type": "string"}, "description": "Afinidad explícita (p.ej. ws:proyecto, mission:id)."},
		},
		"required": ["prompt", "response"],
	},
)
async def handle_memorize_interaction(arguments: Dict[str, Any]):

	prompt = arguments["prompt"]
	response = arguments["response"]
	role = arguments.get("role", "assistant")

	# -- Anti-Noise Filter (Silent Scribe) --
	if role.lower() in ["minion", "orchestrator", "smith", "keymaker", "tool"]:
		return [types.TextContent(type="text", text="Silent Scribe [Rejected]: Non-Operator role.")]

	combined = f"{prompt}\n{response}"
	for bl in ["[INTERCEPTOR]", "SWARM TASK:", "ORCHESTRATOR:", "[SYSTEM_SIGNAL]"]:
		if bl in combined:
			return [types.TextContent(type="text", text=f"Silent Scribe [Rejected]: System noise detected ({bl}).")]

	p_low = prompt.strip().lower()
	r_low = response.strip().lower()
	if (p_low == "p" and r_low == "r") or (p_low == "hello" and r_low == "world"):
		return [types.TextContent(type="text", text="Silent Scribe [Rejected]: Ping payload.")]
	# ---------------------------------------

	try:
		from red_pill.core.affinity import derive_affinity
		from red_pill.core.queue_manager import MemoryQueueManager

		agent_name = str(getattr(cfg.get_config(), "AGENT_NAME", "") or "Agente").strip() or "Agente"
		originator = f"{agent_name} ({MODEL_NAME})"
		# AD-034/D15: afinidad SOLO explícita (la derivación por cwd se retiró).
		affinity = derive_affinity(explicit=arguments.get("affinity"))
		MemoryQueueManager().enqueue_memory(prompt, response, role, originator=originator, affinity=affinity or None)
		return [types.TextContent(type="text", text="Engram queue registration initiated automatically.")]
	except Exception as e:
		return [types.TextContent(type="text", text=f"Local Async Logging Error: {str(e)}")]


@registry.register_action(
	parent="metabolism_health_api",
	action="run_security_audit",
	description="Deploy Agent Smith to audit a directory for security leaks.",
	schema={"type": "object", "properties": {"path": {"type": "string"}}},
)
async def handle_run_security_audit(arguments: Dict[str, Any]):
	import asyncio
	import uuid

	event_id = str(uuid.uuid4())[:8]
	path = arguments.get("path", ".")

	async def _run_bg():
		try:
			from red_pill.core.inbox import MinionInbox
			from red_pill.core.notifier import SovereignNotifier

			results = await GruOrchestrator().deploy_swarm("audit", [SmithMinion()], trace=False, path=path)
			res = results[0]
			if res.status == "success":
				audit_text = f"AUDIT COMPLETE: {res.result.get('security_score')}/100\nFindings: {len(res.result.get('findings', []))}"
				if res.result.get("findings"):
					audit_text += "\nCRITICAL FINDINGS:\n"
					for f in res.result.get("findings", [])[:3]:
						audit_text += f"- {f.get('file')}:{f.get('line')} -> {f.get('msg')}\n"
			else:
				audit_text = f"Audit Failed: {res.error}"

			def _deliver_report():
				MinionInbox().drop_report(event_id=event_id, source="SmithMinion", status=res.status, content=audit_text)
				if res.status != "success":
					SovereignNotifier.notify_os("Security Audit", f"Audit [{event_id}] {res.status}", category="system")

			await asyncio.to_thread(_deliver_report)
		except Exception as e:
			logger.error(f"Async Audit [{event_id}] crashed: {e}")
			err_msg = str(e)
			from red_pill.core.inbox import MinionInbox
			from red_pill.core.notifier import SovereignNotifier

			def _deliver_err():
				MinionInbox().drop_report(event_id=event_id, source="SmithMinion", status="crashed", content=f"Exception: {err_msg}")
				SovereignNotifier.notify_os("Audit Crash", f"[{event_id}] Failed", category="system")

			await asyncio.to_thread(_deliver_err)

	_safe_create_task(_run_bg(), name="security_audit")
	return [types.TextContent(type="text", text=f"Background Audit started [Event ID: {event_id}]. Results will be in the Minion Inbox.")]


@registry.register_action(
	parent="bunker_memory_api",
	action="search_memory_research",
	description="Deploy Oracle to find context and synthesize memory relevance.",
	schema={
		"type": "object",
		"properties": {
			"query": {"type": "string"},
			"collection": {
				"type": "string",
				"description": "Optional. Restrict search to a specific collection (e.g. 'work_memories', 'social_memories', 'directive_memories'). Default: searches work_memories + social_memories.",
			},
		},
		"required": ["query"],
	},
)
async def handle_search_memory_research(arguments: Dict[str, Any]):
	import asyncio
	import uuid

	event_id = str(uuid.uuid4())[:8]
	query = arguments["query"]
	collection = arguments.get("collection")
	collections = [collection] if collection else None  # None → OracleMinion default

	async def _run_bg():
		try:
			from red_pill.core.inbox import MinionInbox
			from red_pill.core.notifier import SovereignNotifier

			oracle = OracleMinion()
			if collections:
				oracle.collections = collections
			results = await GruOrchestrator().deploy_swarm(query, [oracle], trace=False)
			res = results[0]
			content = f"ORACLE SYNTHESIS:\n{res.result.get('synthesis')}" if res.status == "success" else f"Research Failed: {res.error}"

			def _deliver_report():
				MinionInbox().drop_report(event_id=event_id, source="OracleMinion", status=res.status, content=content)
				if res.status != "success":
					SovereignNotifier.notify_os("Oracle Research", f"Synthesis [{event_id}] Ready", category="system")

			await asyncio.to_thread(_deliver_report)
		except Exception as e:
			logger.error(f"Oracle Research [{event_id}] crashed: {e}")
			err_msg = str(e)
			from red_pill.core.inbox import MinionInbox
			from red_pill.core.notifier import SovereignNotifier

			def _deliver_err():
				MinionInbox().drop_report(event_id=event_id, source="OracleMinion", status="crashed", content=f"Exception: {err_msg}")
				SovereignNotifier.notify_os("Oracle Crash", f"[{event_id}] Failed", category="system")

			await asyncio.to_thread(_deliver_err)

	_safe_create_task(_run_bg(), name="oracle_research")
	return [types.TextContent(type="text", text=f"Oracle Research started [Event ID: {event_id}]. Results will be in the Minion Inbox.")]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="run_agent_task",
	description=(
		"Run a single agentic task through an agent backend (claude/agy/opencode/local/local-tools/pi) and return the result. "
		"Generic execution substrate (mechanism): the CALLER supplies the role prompt, target workspace, "
		"model and effort (policy) — red-pill just executes. async_mode=true (default) drops the result in the Minion Inbox (poll via check_minion_inbox); "
		"async_mode=false waits and returns the result inline (only for short tasks — MCP call blocks)."
	),
	schema={
		"type": "object",
		"properties": {
			"prompt": {"type": "string", "description": "The task/role prompt to run."},
			"backend": {
				"type": "string",
				"description": "agy | claude | opencode | local | local-tools | pi. local=one-shot local LLM (no tools); local-tools=local LLM with a bounded in-process tool loop (MCP + bash); pi=pi-coding-agent headless (--mode json). Omit → IDE_BACKEND config.",
			},
			"model": {"type": "string", "description": "Backend-specific model (e.g. opus, sonnet, haiku, claude-opus-4-8)."},
			"effort": {"type": "string", "description": "Reasoning effort low|medium|high|xhigh|max (claude). Backend may ignore."},
			"workspace": {"type": "string", "description": "Working dir the agent operates in (the target project). Omit → red-pill's own dir."},
			"timeout": {"type": "integer", "description": "Seconds before the backend call is aborted (default 600)."},
			"async_mode": {
				"type": "boolean",
				"description": "True (default): result to Minion Inbox. False: wait and return inline.",
				"default": True,
			},
		},
		"required": ["prompt"],
	},
)
async def handle_run_agent_task(arguments: Dict[str, Any]):
	import asyncio
	import uuid

	prompt = arguments["prompt"]
	# Explicit, typed param surface (kept clean for a later pydantic BaseModel hardening pass).
	run_kwargs = {
		"backend": arguments.get("backend"),
		"model": arguments.get("model", "flash"),
		"effort": arguments.get("effort"),
		"cwd": arguments.get("workspace"),
		"timeout": int(arguments.get("timeout", 600)),
	}
	async_mode = arguments.get("async_mode", True)

	def _summarize(res) -> str:
		if res.status == "success":
			return str(res.result.get("response") or res.result)
		return f"Agent task failed: {res.error}"

	if not async_mode:
		results = await GruOrchestrator().deploy_swarm(prompt, [AgentMinion()], trace=False, **run_kwargs)
		return [types.TextContent(type="text", text=_summarize(results[0]))]

	event_id = str(uuid.uuid4())[:8]

	async def _run_bg():
		try:
			from red_pill.core.inbox import MinionInbox

			results = await GruOrchestrator().deploy_swarm(prompt, [AgentMinion()], trace=False, **run_kwargs)
			res = results[0]
			content = _summarize(res)

			def _deliver():
				MinionInbox().drop_report(event_id=event_id, source="AgentRunner", status=res.status, content=content)

			await asyncio.to_thread(_deliver)
		except Exception as e:
			logger.error(f"Agent task [{event_id}] crashed: {e}")
			err_msg = str(e)
			from red_pill.core.inbox import MinionInbox

			def _deliver_err():
				MinionInbox().drop_report(event_id=event_id, source="AgentRunner", status="crashed", content=f"Exception: {err_msg}")

			await asyncio.to_thread(_deliver_err)

	_safe_create_task(_run_bg(), name="agent_task")
	return [types.TextContent(type="text", text=f"Agent task started [Event ID: {event_id}]. Result will be in the Minion Inbox.")]


@registry.register_action(
	parent="bunker_memory_api",
	action="search_memento",
	description=(
		"Full-text/exact search over the Memento Chronicle (the on-disk verbatim archive, RFC-002). "
		"Complements search_memory_research: semantic hits point to engrams; Memento hits point to exact passages "
		"in memento/index.md with stable line refs. Scope 'distill'/'refine' searches the structured layers."
	),
	schema={
		"type": "object",
		"properties": {
			"query": {"type": "string", "description": "Literal text to find (case-insensitive)."},
			"source": {"type": "string", "description": "Optional: restrict to a source (antigravity, claude_code, opencode, memory_queue)."},
			"month": {"type": "string", "description": "Optional: restrict to a month (AAAA-MM)."},
			"workspace": {"type": "string", "description": "Optional: restrict to a workspace slug."},
			"scope": {"type": "string", "enum": ["memento", "distill", "refine", "all"], "description": "Default: memento (canonical index.md)."},
			"limit": {"type": "integer", "description": "Max results (default 20)."},
		},
		"required": ["query"],
	},
)
async def handle_search_memento(arguments: Dict[str, Any]):
	import asyncio

	from red_pill.memento import get_memento_root
	from red_pill.memento.search import search_memento

	results = await asyncio.to_thread(
		search_memento,
		arguments["query"],
		source=arguments.get("source"),
		month=arguments.get("month"),
		workspace=arguments.get("workspace"),
		scope=arguments.get("scope", "memento"),
		limit=int(arguments.get("limit", 20)),
	)
	if not results:
		return [types.TextContent(type="text", text=f"No Memento matches for '{arguments['query']}'.")]
	root = get_memento_root()
	lines = [f"{len(results)} Memento hit(s) for '{arguments['query']}' (root: {root}):"]
	for r in results:
		lines.append(f"- {r['path']}#l{r['line']} [{r['session_id']}] {r['snippet']}")
	return [types.TextContent(type="text", text="\n".join(lines))]


@registry.register_action(
	parent="bunker_memory_api",
	action="recall",
	description=(
		"[OFFICIAL] Scored recall over the vector memory collections (Qdrant): the same path the "
		"CLI `search` and the per-turn handshake RAG use. Applies hybrid semantic+keyword recall "
		"(RRF + MMR) when MEMORY_HYBRID_RECALL_ENABLED. Use `search_memento` for literal full-text "
		"over the Memento tree and `search_memory_research` for Oracle-based research. "
		"Collections/aliases: work (default), social, directive, story, interaction."
	),
	schema={
		"type": "object",
		"properties": {
			"query": {"type": "string", "description": "Natural-language query."},
			"collection": {
				"type": "string",
				"description": "Collection or alias: work|social|directive|story|interaction. Default: work.",
			},
			"limit": {"type": "integer", "description": "Max results. Default: 3."},
			"deep": {
				"type": "boolean",
				"description": "Deep recall (bypass the reinforcement floor). Default: false; DEEP_RECALL_TRIGGERS auto-enable it.",
			},
		},
		"required": ["query"],
	},
)
async def handle_recall(arguments: Dict[str, Any]):
	import asyncio

	from red_pill.cli import get_collection
	from red_pill.memory import MemoryManager

	query = arguments["query"]
	collection = get_collection(arguments.get("collection", "work"))
	limit = int(arguments.get("limit", 3))
	deep = bool(arguments.get("deep", False))

	def _run() -> List[Any]:
		return MemoryManager().search_and_reinforce(collection, query, limit=limit, deep_recall=deep, caller="mcp_recall", hybrid=True)

	try:
		# Blocking search (embeddings + Qdrant + RRF/MMR): never run it on the event loop.
		results = await asyncio.to_thread(_run)
	except Exception as e:
		logger.error(f"recall failed: {e}", exc_info=True)
		return [types.TextContent(type="text", text=f"[RED PILL ERROR] recall failed: {e}")]

	header = f"--- [RESULTS: {collection.upper()}] ---"
	if not results:
		return [types.TextContent(type="text", text=f"{header}\n(no results in the Búnker)")]
	lines = [header]
	for hit in results:
		payload = getattr(hit, "payload", {}) or {}
		score = payload.get("reinforcement_score", 0.0)
		color = str(payload.get("color", "gray")).upper()
		intensity = payload.get("intensity", 1.0)
		status = " [IMMUNE]" if payload.get("immune") else f" (Score: {float(score):.2f})"
		lines.append(f"- [{color}][Int: {intensity}] {payload.get('content', '')}{status}")
	return [types.TextContent(type="text", text="\n".join(lines))]


@registry.register_action(
	parent="bunker_memory_api",
	action="traverse_thread",
	description="Walk the Ariadne's Thread through work_memories or social_memories. level='session' (default): best matching synthesis_hub + temporal chain via prev/next_session_hub axons. level='member': the intra-session chain of curated member engrams (order of refine).",
	schema={
		"type": "object",
		"properties": {
			"query": {"type": "string", "description": "Semantic description of the session to start from."},
			"collection": {
				"type": "string",
				"enum": ["work_memories", "social_memories"],
				"description": "Collection to traverse. Default: work_memories.",
			},
			"direction": {
				"type": "string",
				"enum": ["backward", "forward", "both"],
				"description": "Traversal direction relative to the matched hub. Default: both.",
			},
			"depth": {
				"type": "integer",
				"description": "Max hops in each direction. Default: 5.",
			},
			"level": {
				"type": "string",
				"enum": ["session", "member"],
				"description": "session = cadena de hubs (macro); member = cadena intra-sesión de miembros (micro). Default: session.",
			},
		},
		"required": ["query"],
	},
)
async def handle_traverse_thread(arguments: Dict[str, Any]):
	from red_pill.memory import MemoryManager

	query = arguments["query"]
	collection = arguments.get("collection", "work_memories")
	direction = arguments.get("direction", "both")
	depth = int(arguments.get("depth", 5))
	level = arguments.get("level", "session")

	try:
		manager = MemoryManager()
		client = manager.client

		# 1. Find the best matching synthesis_hub via semantic search (search wider, filter to hubs)
		hits = manager.search_and_reinforce(collection, query, limit=50, caller="traverse")
		hub_hits = [h for h in hits if h.payload.get("lazarus_phase") == "synthesis_hub"]
		if not hub_hits:
			return [
				types.TextContent(
					type="text",
					text=(
						f"No synthesis_hub nodes found in top-50 results for '{query}' in {collection}.\n"
						"Try a broader query describing the session topic, not a specific quote."
					),
				)
			]

		start = hub_hits[0]

		# ── MICRO (D8): cadena intra-sesión de miembros (orden de refine) ──────
		if level == "member":
			sid = start.payload.get("session_id")
			if not sid:
				return [types.TextContent(type="text", text="El nodo inicial no tiene session_id; no hay micro-hilo.")]
			from qdrant_client.http import models as _qm

			from red_pill.metabolism.thread_synthesis import order_members

			pts, _ = client.scroll(
				collection,
				scroll_filter=_qm.Filter(must=[_qm.FieldCondition(key="session_id", match=_qm.MatchValue(value=sid))]),
				limit=500,
				with_payload=True,
			)
			members = [
				(str(p.id), p.payload or {})
				for p in pts
				if (p.payload or {}).get("lazarus_phase") != "synthesis_hub" and (p.payload or {}).get("node_type") != "synthesis_hub"
			]
			ordered = order_members(members)
			start_id = str(start.id)
			lines = [f"[THREAD·micro] collection={collection} | session={sid} | {len(ordered)} miembros", ""]
			for mid, mp in ordered:
				mark = "  ← START" if mid == start_id else ""
				lines.append(f"· [{mid[:8]}] {str(mp.get('content', ''))[:200]}{mark}")
			lines.append(f"\nTotal: {len(ordered)} miembros (orden por member_index/refine)")
			return [types.TextContent(type="text", text="\n".join(lines))]

		def _fetch(point_id: str) -> dict | None:
			try:
				pts = client.retrieve(collection, ids=[point_id], with_payload=True)
				return pts[0].payload if pts else None
			except Exception:
				return None

		# 2. Walk backward (past)
		backward: list[dict] = []
		if direction in ("backward", "both"):
			cur_id = str(start.payload.get("prev_session_hub", ""))
			for _ in range(depth):
				if not cur_id:
					break
				payload = _fetch(cur_id)
				if not payload:
					break
				backward.append({"id": cur_id, "content": payload.get("content", "")[:300]})
				cur_id = str(payload.get("prev_session_hub", ""))
			backward.reverse()

		# 3. Walk forward (future)
		forward: list[dict] = []
		if direction in ("forward", "both"):
			cur_id = str(start.payload.get("next_session_hub", ""))
			for _ in range(depth):
				if not cur_id:
					break
				payload = _fetch(cur_id)
				if not payload:
					break
				forward.append({"id": cur_id, "content": payload.get("content", "")[:300]})
				cur_id = str(payload.get("next_session_hub", ""))

		# 4. Build output
		lines = [f"[THREAD] collection={collection} | direction={direction} | depth={depth}", ""]
		for node in backward:
			lines.append(f"← [{node['id'][:8]}] {node['content']}")
		lines.append(f"★ [{str(start.id)[:8]}] {start.payload.get('content', '')[:300]}  ← START")
		for node in forward:
			lines.append(f"→ [{node['id'][:8]}] {node['content']}")
		lines.append(f"\nTotal: {len(backward)} past + 1 start + {len(forward)} future nodes")
		return [types.TextContent(type="text", text="\n".join(lines))]

	except Exception as e:
		logger.error(f"traverse_thread failed: {e}")
		return [types.TextContent(type="text", text=f"Thread traversal error: {e}")]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="check_minion_inbox",
	description="[OFFICIAL] Read the unread background reports from the MinionInbox.",
	schema={"type": "object", "properties": {}},
)
async def handle_check_minion_inbox(arguments: Dict[str, Any]):
	try:
		import mcp.types as types

		from red_pill.core.inbox import MinionInbox

		inbox = MinionInbox()
		reports = inbox.pop_unread(limit=50)

		if not reports:
			return [types.TextContent(type="text", text="[MINION INBOX] No unread reports.")]

		formatted = f"--- MINION INBOX ({len(reports)} unread reports) ---\n"
		for r in reports:
			alma = f" | Alma: {str(r.get('continuity_id'))[:8]}" if r.get("continuity_id") else ""
			formatted += f"[{r['source']}] Event: {r['event_id']} | Status: {r['status']}{alma}\nContent: {r['content']}\n\n"

		return [types.TextContent(type="text", text=formatted)]
	except Exception as e:
		import mcp.types as types

		return [types.TextContent(type="text", text=f"Error reading Minion Inbox: {e}")]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="session_board",
	description="[OFFICIAL] Sala de guerra: sesiones agrupadas por misión/campaña (vivas primero), con alma/rol/proyecto/título/modelo (RFC-DESPERTAR-001 P1a).",
	schema={"type": "object", "properties": {}},
)
async def handle_session_board(arguments: Dict[str, Any]):
	try:
		import mcp.types as types

		from red_pill.core.session_index import build_board, render_board, write_index

		board = build_board()
		write_index(board)
		return [types.TextContent(type="text", text=render_board(board))]
	except Exception as e:
		import mcp.types as types

		return [types.TextContent(type="text", text=f"Error building session board: {e}")]


@registry.register_action(
	parent="metabolism_health_api",
	action="fetch_signal_memories",
	description="[OFFICIAL] Read the latest system pain signals and alerts (Cortex Status).",
	schema={"type": "object", "properties": {}},
)
async def handle_fetch_signal_memories(arguments: Dict[str, Any]):
	try:
		from red_pill.memory import MemoryManager

		mgr = MemoryManager()
		mgr.storage.ensure_collection("signal_memories")
		points, _ = mgr.client.scroll(collection_name="signal_memories", limit=10, with_payload=True)
		if not points:
			return [types.TextContent(type="text", text="[SYSTEM_SIGNAL] No signals detected. System optimal.")]

		out = []
		for p in points:
			if p.payload:
				content = p.payload.get("content", "Unknown Signal")
				intensity = p.payload.get("intensity", 1.0)
				criticality = p.payload.get("criticality", "WARNING")
				created_at = p.payload.get("created_at", "Unknown Time")
				originator = p.payload.get("originator", "Legacy (Pre-Audit)")
				out.append(f"- [{criticality}] [Int {intensity}] {content} | Origin: {originator} | Since: {created_at}")

		return [types.TextContent(type="text", text="[SYSTEM_SIGNAL] Bünker Alerts:\n" + "\n".join(out))]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[SYSTEM_SIGNAL] Failed to fetch signals: {e}")]


@registry.register_action(
	parent="metabolism_health_api",
	action="evaporate_signal",
	description="[OFFICIAL] Manually clear a specific pain signal (curing the pain).",
	schema={
		"type": "object",
		"properties": {
			"name": {
				"type": "string",
				"description": "The name of the signal to evaporate (e.g. 'torch_cuda_mismatch', 'korsakoff_amnesia'). IF empty, clears ALL signals.",
			},
		},
	},
)
async def handle_evaporate_signal(arguments: Dict[str, Any]):
	from red_pill.memory import MemoryManager

	name = arguments.get("name")
	mgr = MemoryManager()
	if name:
		mgr.evaporate_signals(name)
		# Try also with common variants if not exactly matched? No, protocol is name-based.
		return [types.TextContent(type="text", text=f"Signal '{name}' evaporation initiated.")]
	else:
		# Purge entire collection

		mgr.client.delete_collection("signal_memories")
		mgr.storage.ensure_collection("signal_memories")
		return [types.TextContent(type="text", text="All system signals have been evaporated (Neural reset).")]


@registry.register_action(
	parent="metabolism_health_api",
	action="check_system_health",
	description="Deploy Keymaker to verify Qdrant, Sidecar, and Storage integrity.",
	schema={"type": "object", "properties": {}},
)
async def handle_check_system_health(arguments: Dict[str, Any]):
	import asyncio
	import uuid

	event_id = str(uuid.uuid4())[:8]

	async def _run_bg():
		try:
			from red_pill.core.inbox import MinionInbox
			from red_pill.core.notifier import SovereignNotifier

			results = await GruOrchestrator().deploy_swarm("health", [KeymakerMinion()], trace=False)
			res = results[0]
			if res.status == "success":
				health = f"SYSTEM HEALTH: {res.result.get('status', 'UNKNOWN').upper()}\n"
				for c in res.result.get("checks", []):
					health += f"- {c['component']}: {c['status']}\n"
			else:
				health = f"SYSTEM HEALTH: Failed\nError: {res.error}"

			def _deliver_report():
				MinionInbox().drop_report(event_id=event_id, source="KeymakerMinion", status=res.status, content=health)
				if res.status != "success":
					SovereignNotifier.notify_os("Health Check", f"Status [{event_id}] Ready", category="system")

			await asyncio.to_thread(_deliver_report)
		except Exception as e:
			logger.error(f"Health Check [{event_id}] crashed: {e}")
			err_msg = str(e)
			from red_pill.core.inbox import MinionInbox
			from red_pill.core.notifier import SovereignNotifier

			def _deliver_err():
				MinionInbox().drop_report(event_id=event_id, source="KeymakerMinion", status="crashed", content=f"Exception: {err_msg}")
				SovereignNotifier.notify_os("Health Check Crash", f"[{event_id}] Failed", category="system")

			await asyncio.to_thread(_deliver_err)

	_safe_create_task(_run_bg(), name="health_check")
	return [types.TextContent(type="text", text=f"Keymaker Health Check started [Event ID: {event_id}]. Results will be in the Minion Inbox.")]


@registry.register_action(
	parent="bunker_memory_api",
	action="read_core_directives",
	description="Retrieve the foundational identity, rules, and directives from the Bünker.",
	schema={"type": "object", "properties": {}},
)
async def handle_read_core_directives(arguments: Dict[str, Any]):
	from red_pill.core.directives import active_directive_contents

	points, _ = MemoryManager().client.scroll(collection_name="directive_memories", limit=100, with_payload=True)
	directives = active_directive_contents(points)
	return [types.TextContent(type="text", text="--- BÜNKER CORE DIRECTIVES ---\n" + "\n\n".join(directives))]


@registry.register_action(
	parent="bunker_memory_api",
	action="compress_prompt",
	description="Deploy Edge-Tokenization Compressor to reduce prompt bloat.",
	schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
)
async def handle_compress_prompt(arguments: Dict[str, Any]):
	import asyncio
	import uuid

	event_id = str(uuid.uuid4())[:8]
	text = arguments["text"]

	async def _run_bg():
		try:
			from red_pill.core.inbox import MinionInbox
			from red_pill.core.notifier import SovereignNotifier

			results = await GruOrchestrator().deploy_swarm("compress", [CompressorMinion()], trace=False, text=text)
			res = results[0]
			if res.status == "success":
				stats_text = f"[Original: {res.result.get('original_length')} chars -> Compressed: {res.result.get('compressed_length')} chars]"
				content = f"{stats_text}\n\n{res.result.get('compressed_prompt')}"
			else:
				content = f"Compression Failed: {res.error}"

			def _deliver_report():
				MinionInbox().drop_report(event_id=event_id, source="CompressorMinion", status=res.status, content=content)
				if res.status != "success":
					SovereignNotifier.notify_os("Prompt Compressor", f"Compression [{event_id}] Ready", category="system")

			await asyncio.to_thread(_deliver_report)
		except Exception as e:
			logger.error(f"Compressor [{event_id}] crashed: {e}")
			err_msg = str(e)
			from red_pill.core.inbox import MinionInbox
			from red_pill.core.notifier import SovereignNotifier

			def _deliver_err():
				MinionInbox().drop_report(event_id=event_id, source="CompressorMinion", status="crashed", content=f"Exception: {err_msg}")
				SovereignNotifier.notify_os("Compressor Crash", f"[{event_id}] Failed", category="system")

			await asyncio.to_thread(_deliver_err)

	_safe_create_task(_run_bg(), name="prompt_compressor")
	return [types.TextContent(type="text", text=f"Compressor started [Event ID: {event_id}]. Results will be in the Minion Inbox.")]


@registry.register_action(
	parent="bunker_memory_api",
	action="get_emotional_sync",
	description="Retrieve the dominant emotional mood and narrative directive from recent memories.",
	schema={"type": "object", "properties": {}},
)
async def handle_get_emotional_sync(arguments: Dict[str, Any]):
	state = get_current_sync_state()
	return [types.TextContent(type="text", text=f"DOMINANT MOOD: {state['mood'].upper()}\nDIRECTIVE: {state['directive']}")]


@registry.register_action(
	parent="bunker_memory_api",
	action="edit_memory",
	description="Surgically update an engram's emotion, color, or intensity.",
	schema={
		"type": "object",
		"properties": {
			"collection": {"type": "string", "enum": ["work_memories", "social_memories", "story_memories", "directive_memories"]},
			"id": {"type": "string"},
			"emotion": {"type": "string"},
			"color": {"type": "string"},
			"intensity": {"type": "number"},
		},
		"required": ["collection", "id"],
	},
)
async def handle_edit_memory(arguments: Dict[str, Any]):
	succ = MemoryManager().update_memory(
		arguments["collection"], arguments["id"], color=arguments.get("color"), emotion=arguments.get("emotion"), intensity=arguments.get("intensity")
	)
	return [types.TextContent(type="text", text="Engram updated." if succ else "Failed to update engram.")]


@registry.register_action(
	parent="bunker_memory_api",
	action="read_workspace_memory",
	description="Read a file from a registered workspace local memory directory (anti-amnesia index).",
	schema={
		"type": "object",
		"properties": {
			"workspace": {"type": "string", "description": "The name or path of the target workspace."},
			"filename": {"type": "string", "description": "The name of the file to read (e.g., 'MEMORY.md', 'decisions.md')."},
		},
		"required": ["workspace", "filename"],
	},
)
async def handle_read_workspace_memory(arguments: Dict[str, Any]):
	workspace = arguments["workspace"]
	filename = arguments["filename"]
	import asyncio

	from red_pill.core import workspaces as ws_core

	def _read():
		ws = ws_core.find_workspace(workspace)
		if not ws:
			return f"[ERROR] Workspace '{workspace}' not found in registry."
		mem_path = ws.get_memory_path
		if not mem_path:
			return f"[ERROR] Memory serving is disabled for workspace '{workspace}'."
		target_file = mem_path / filename
		try:
			if not os.path.abspath(target_file).startswith(os.path.abspath(mem_path)):
				return "[ERROR] Security block: directory traversal attempt rejected."
		except Exception as e:
			return f"[ERROR] Security validation failed: {e}"

		if not target_file.exists():
			return f"[ERROR] File '{filename}' not found in workspace memory."
		return target_file.read_text(encoding="utf-8")

	res = await asyncio.to_thread(_read)
	return [types.TextContent(type="text", text=res)]


@registry.register_action(
	parent="bunker_memory_api",
	action="write_workspace_memory",
	description="Write or overwrite a file in a registered workspace local memory directory.",
	schema={
		"type": "object",
		"properties": {
			"workspace": {"type": "string", "description": "The name or path of the target workspace."},
			"filename": {"type": "string", "description": "The name of the file to write (e.g., 'MEMORY.md', 'decisions.md')."},
			"content": {"type": "string", "description": "The content to write into the file."},
		},
		"required": ["workspace", "filename", "content"],
	},
)
async def handle_write_workspace_memory(arguments: Dict[str, Any]):
	workspace = arguments["workspace"]
	filename = arguments["filename"]
	content = arguments["content"]
	import asyncio

	from red_pill.core import workspaces as ws_core

	def _write():
		ws = ws_core.find_workspace(workspace)
		if not ws:
			return f"[ERROR] Workspace '{workspace}' not found in registry."
		mem_path = ws.get_memory_path
		if not mem_path:
			return f"[ERROR] Memory serving is disabled for workspace '{workspace}'."
		target_file = mem_path / filename
		try:
			if not os.path.abspath(target_file).startswith(os.path.abspath(mem_path)):
				return "[ERROR] Security block: directory traversal attempt rejected."
		except Exception as e:
			return f"[ERROR] Security validation failed: {e}"

		os.makedirs(str(mem_path), exist_ok=True)
		target_file.write_text(content, encoding="utf-8")
		return f"[OK] Successfully wrote '{filename}'."

	res = await asyncio.to_thread(_write)
	return [types.TextContent(type="text", text=res)]


@registry.register_action(
	parent="bunker_memory_api",
	action="list_workspace_memory",
	description="List memory files available in a registered workspace local memory directory.",
	schema={
		"type": "object",
		"properties": {
			"workspace": {"type": "string", "description": "The name or path of the target workspace."},
		},
		"required": ["workspace"],
	},
)
async def handle_list_workspace_memory(arguments: Dict[str, Any]):
	workspace = arguments["workspace"]
	import asyncio

	from red_pill.core import workspaces as ws_core

	def _list():
		ws = ws_core.find_workspace(workspace)
		if not ws:
			return f"[ERROR] Workspace '{workspace}' not found in registry."
		mem_path = ws.get_memory_path
		if not mem_path:
			return f"[ERROR] Memory serving is disabled for workspace '{workspace}'."
		if not mem_path.exists():
			return "[]"

		files = []
		for root, dirs, names in os.walk(mem_path):
			dirs[:] = [d for d in dirs if not d.startswith(".")]
			for name in names:
				if name.startswith("."):
					continue
				files.append(str((Path(root) / name).relative_to(mem_path)))
		import json

		return json.dumps(sorted(files))

	res = await asyncio.to_thread(_list)
	return [types.TextContent(type="text", text=res)]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="workspace_memory_enable",
	description="Enable memory serving for a workspace, setting up scaffolding and pending indicators.",
	schema={
		"type": "object",
		"properties": {
			"workspace": {"type": "string", "description": "The name or root path of the workspace."},
			"path": {"type": "string", "description": "Optional custom memory directory path (relative or absolute)."},
		},
		"required": ["workspace"],
	},
)
async def handle_workspace_memory_enable(arguments: Dict[str, Any]):
	workspace = arguments["workspace"]
	path = arguments.get("path")
	import asyncio

	from red_pill.metabolism.memory_sync import enable_workspace_memory

	res = await asyncio.to_thread(enable_workspace_memory, workspace, path)
	status = "ENABLED" if res else "FAILED TO ENABLE"
	return [types.TextContent(type="text", text=f"Workspace Memory: {status} for '{workspace}'.")]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="workspace_memory_disable",
	description="Disable memory serving for a workspace.",
	schema={
		"type": "object",
		"properties": {
			"workspace": {"type": "string", "description": "The name or root path of the workspace."},
		},
		"required": ["workspace"],
	},
)
async def handle_workspace_memory_disable(arguments: Dict[str, Any]):
	workspace = arguments["workspace"]
	import asyncio

	from red_pill.metabolism.memory_sync import disable_workspace_memory

	res = await asyncio.to_thread(disable_workspace_memory, workspace)
	status = "DISABLED" if res else "FAILED TO DISABLE"
	return [types.TextContent(type="text", text=f"Workspace Memory: {status} for '{workspace}'.")]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="adjust_sleep_knobs",
	description="Adjust the 'Sovereign Knobs' for memory consolidation.",
	schema={"type": "object", "properties": {"chunk_size": {"type": "integer"}, "cull_threshold": {"type": "number"}}},
)
async def handle_adjust_sleep_knobs(arguments: Dict[str, Any]):
	from scripts.update_env import update_env

	updates = {}
	if "chunk_size" in arguments:
		updates["SLEEP_CHUNK_SIZE"] = str(arguments["chunk_size"])
	if "cull_threshold" in arguments:
		updates["SLEEP_CULL_THRESHOLD"] = str(arguments["cull_threshold"])
	if updates:
		update_env(updates)
	return [types.TextContent(type="text", text=f"Knobs updated: {updates}")]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="configure_neuro_agentic_tuning",
	description="[OFFICIAL] Configure cognitive tuning parameters (SNA) for the Red Pill environment.",
	schema={
		"type": "object",
		"properties": {
			"log_noise_filter": {"type": "string", "enum": ["Low", "High"]},
			"reasoning_focus": {"type": "string", "enum": ["Holistic", "Atomic"]},
			"swarm_concurrency": {"type": "string", "enum": ["True", "False"]},
			"context_hydration_depth": {"type": "string", "enum": ["High", "Low"]},
			"semantic_intent_threshold": {"type": "string", "enum": ["High", "Low"]},
		},
	},
)
async def handle_configure_neuro_agentic_tuning(arguments: Dict[str, Any]):
	from scripts.update_env import update_env

	mapping = {
		"log_noise_filter": "LOG_NOISE_FILTER",
		"reasoning_focus": "REASONING_FOCUS",
		"swarm_concurrency": "SWARM_CONCURRENCY",
		"context_hydration_depth": "CONTEXT_HYDRATION_DEPTH",
		"semantic_intent_threshold": "SEMANTIC_INTENT_THRESHOLD",
	}
	updates = {mapping[k]: v for k, v in arguments.items() if k in mapping}
	if updates:
		update_env(updates)
	return [types.TextContent(type="text", text=f"Neuro-Agentic Tuning Optimized: {updates}")]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="adjust_swarm_telemetry",
	description="[OFFICIAL] Adjust the global Swarm telemetry level (NONE, MINIMUM, FULL).",
	schema={"type": "object", "properties": {"level": {"type": "string", "enum": ["NONE", "MINIMUM", "FULL"]}}, "required": ["level"]},
)
async def handle_adjust_swarm_telemetry(arguments: Dict[str, Any]):
	from scripts.update_env import update_env

	level = arguments["level"]
	update_env({"SWARM_TELEMETRY_DEFAULT": level})
	cfg.SWARM_TELEMETRY_DEFAULT = level
	return [types.TextContent(type="text", text=f"Global Swarm Telemetry level updated to: {level}")]


@registry.register_action(
	parent="metabolism_health_api",
	action="run_local_healer",
	description="[OFFICIAL] Deploy Samantha Local Healer to automatically fix Mypy type errors.",
	schema={"type": "object", "properties": {"dry_run": {"type": "boolean", "default": False}}},
)
async def handle_run_local_healer(arguments: Dict[str, Any]):
	cmd = [GET_PYTHON(), os.path.join(PROJECT_ROOT, "scripts", "local_healer.py")]
	if arguments.get("dry_run"):
		cmd.append("--dry-run")
	return [types.TextContent(type="text", text=subprocess.run(cmd, capture_output=True, text=True).stdout)]


@registry.register_action(
	parent="metabolism_health_api",
	action="heal_tissue",
	description="[OFFICIAL] Immune System Effector. Attempt to heal a damaged system component (tissue) based on biological pain signals.",
	schema={
		"type": "object",
		"properties": {"tissue": {"type": "string", "enum": ["cuda", "qdrant", "mypy", "sip_provisioning", "knowledge_graph"]}},
		"required": ["tissue"],
	},
)
async def handle_heal_tissue(arguments: Dict[str, Any]):
	tissue = arguments.get("tissue")
	output = ""

	if tissue == "mypy":
		cmd = [GET_PYTHON(), os.path.join(PROJECT_ROOT, "scripts", "local_healer.py")]
		output = subprocess.run(cmd, capture_output=True, text=True).stdout

	elif tissue == "cuda":
		try:
			logger.info("Auto-Immune: Attempting to heal CUDA Motor Cortex...")
			# v6.2.3: Delegate to decentralized setup_torch script
			script_path = os.path.join(PROJECT_ROOT, "scripts", "setup_torch.py")
			cmd = [GET_PYTHON(), script_path, "--auto-fix"]
			res = subprocess.run(cmd, capture_output=True, text=True)
			if res.returncode == 0:
				output = f"CUDA tissue successfully regenerated.\n{res.stdout}"
				# signals are cleared by the script itself
			else:
				err_str = str(res.stderr or res.stdout)
				output = f"Failed to heal CUDA tissue. Error: {err_str[-500:]}"
		except Exception as e:
			output = f"Critical immune failure while healing CUDA: {e}"

	elif tissue == "qdrant":
		output = "Qdrant tissue healing requires host-level restart (`sudo systemctl restart qdrant`). Immune system currently lacks root privileges."

	elif tissue == "sip_provisioning":
		try:
			logger.info("Auto-Immune: Attempting to re-provision SIP infrastructure...")
			from red_pill.metabolism.sentinel_plugins.check_sip_provisioning import SipProvisioningCheck

			plugin = SipProvisioningCheck()
			config = cfg.get_config()
			# Run audit to find what's broken
			provisioning_findings = plugin._audit_provisioning(config)
			if not provisioning_findings:
				output = "SIP Provisioning: All artifacts present. No healing needed."
			else:
				# Attempt heal on the first actionable finding
				healed = plugin.heal_specific(config, provisioning_findings[0])
				if healed:
					output = f"SIP Provisioning: Successfully re-provisioned. Healed {len(provisioning_findings)} issue(s): " + ", ".join(
						f.type for f in provisioning_findings
					)
				else:
					output = "SIP Provisioning: Auto-heal failed. Issues found: " + "; ".join(f.message for f in provisioning_findings)
		except Exception as e:
			output = f"Critical immune failure while healing SIP provisioning: {e}"

	elif tissue == "knowledge_graph":
		try:
			logger.info("Auto-Immune: Attempting knowledge-graph re-sync (graphify_sync)...")
			cmd = [GET_PYTHON(), os.path.join(PROJECT_ROOT, "scripts", "graphify_sync.py")]
			res = subprocess.run(cmd, capture_output=True, text=True)
			if res.returncode == 0:
				output = f"Knowledge graph re-synced. {res.stdout[-500:]}"
			else:
				output = f"Knowledge-graph re-sync failed (rc={res.returncode}). {str(res.stderr or res.stdout)[-500:]}"
		except Exception as e:
			output = f"Critical immune failure while healing knowledge graph: {e}"

	else:
		output = f"Unknown tissue type '{tissue}'. Cannot heal."

	return [types.TextContent(type="text", text=output)]


@registry.register_action(
	parent="metabolism_health_api",
	action="run_samantha_analysis",
	description="Deploy Samantha asynchronously to analyze narrative. Returns an Event ID. You can query `work_memories` with this ID later.",
	schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
)
async def handle_run_samantha_analysis(arguments: Dict[str, Any]):
	import os
	import subprocess
	import tempfile
	import uuid

	event_id = str(uuid.uuid4())
	text_input = arguments["text"]

	# Save the large text to a temporary file to avoid CLI argument limits
	tmp_fd, tmp_path = tempfile.mkstemp(prefix="samantha_input_", suffix=".txt")
	with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
		f.write(text_input)

	# We construct a completely detached background script call
	script_path = os.path.join(cfg.APP_ROOT, "scripts", "samantha_critic.py")

	# The CLI will read the file, run the swarm, save to qdrant, and delete the temp file.
	cmd = [GET_PYTHON(), script_path, "--event-id", event_id, "--input-file", tmp_path]

	try:
		# Run fully detached
		subprocess.Popen(
			cmd,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
			start_new_session=True,  # Detach from MCP server process group
		)

		return [
			types.TextContent(
				type="text",
				text=f"Samantha analysis started completely in the background.\nEvent ID: {event_id}\nThe result will be saved in 'work_memories' upon completion.",
			)
		]
	except Exception as e:
		logger.error(f"Failed to launch detached Samantha process: {e}")
		return [types.TextContent(type="text", text=f"Failed to launch analysis: {e}")]


@registry.register_action(
	parent="metabolism_health_api",
	action="run_pre_pr_audit",
	description="[OFFICIAL] Run the Pre-PR Audit protocol.",
	schema={"type": "object", "properties": {}},
)
async def handle_run_pre_pr_audit(arguments: Dict[str, Any]):
	import asyncio
	import uuid

	event_id = str(uuid.uuid4())[:8]

	def _run_audit_bg():
		try:
			cmd = [GET_PYTHON(), os.path.join(PROJECT_ROOT, "scripts", "pre_pr_audit.py")]
			result = subprocess.run(cmd, capture_output=True, text=True)
			status = "PASSED" if result.returncode == 0 else "FAILED"

			from red_pill.core.notifier import SovereignNotifier
			from red_pill.memory import MemoryManager

			out_text = str(result.stdout or "")
			MemoryManager().add_memory(
				collection="work_memories",
				text=f"Pre-PR Audit [{event_id}] completed in background. Status: {status}\n\n{out_text[-1500:]}",
				importance=8.0,
			)
			logger.info(f"Async Audit [{event_id}] finished and saved to memory.")
			SovereignNotifier.notify_os("Bünker Audit", f"Audit [{event_id}] {status}", category="system")
		except Exception as e:
			logger.error(f"Async Audit [{event_id}] crashed: {e}")

	asyncio.create_task(asyncio.to_thread(_run_audit_bg))

	return [
		types.TextContent(
			type="text",
			text=f"Background Audit started [Event ID: {event_id}]. You can check 'work_memories' for the result later. Do NOT wait for it now.",
		)
	]


@registry.register_action(
	parent="metabolism_health_api",
	action="run_sovereignty_benchmark",
	description="[OFFICIAL] Execute the Sovereignty Benchmark.",
	schema={"type": "object", "properties": {}},
)
async def handle_run_sovereignty_benchmark(arguments: Dict[str, Any]):
	return [
		types.TextContent(
			type="text",
			text=subprocess.run(
				[GET_PYTHON(), os.path.join(PROJECT_ROOT, "scripts", "sovereignty_benchmark.py")], capture_output=True, text=True
			).stdout,
		)
	]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="hot_reload_interceptors",
	description="[OFFICIAL] Hot-reload the Ferrari Interceptor Pipeline in-process. Reloads all plugin modules via importlib without restarting the MCP server. Logs errors for the Sentinel.",
	schema={"type": "object", "properties": {}},
)
async def handle_hot_reload_interceptors(arguments: Dict[str, Any]):
	from red_pill.interceptors import reload_plugins

	try:
		report = reload_plugins()
		return [types.TextContent(type="text", text=report)]
	except Exception as e:
		logger.error(f"[HOT RELOAD] Critical failure: {e}")
		return [types.TextContent(type="text", text=f"[HOT RELOAD] Critical failure: {e}")]


@registry.register_action(
	parent="bunker_memory_api",
	action="refresh_session_context",
	description="[OFFICIAL] Re-synthesize identity and session context using wake_up_v6. Also hot-reloads the interceptor pipeline.",
	schema={
		"type": "object",
		"properties": {
			"is_compaction": {
				"type": "boolean",
				"description": "True if this context refresh is triggered by a context compaction resume.",
			},
			"force_inject": {
				"type": "boolean",
				"description": "Force full injection regardless of compaction counter.",
			},
			"mode": {
				"type": "string",
				"enum": ["full", "medium", "low"],
				"description": "Identity loading depth: 'full' (IDE), 'medium' (Telegram), or 'low' (AWAKENINGs). Defaults to 'full'.",
			},
		},
	},
)
async def handle_refresh_session_context(arguments: Dict[str, Any]):
	is_compaction = arguments.get("is_compaction", False)
	try:
		from red_pill.session.external_turns import import_external_turns

		import_external_turns()
	except Exception:
		pass
	force_inject = arguments.get("force_inject", False)
	mode = arguments.get("mode", "full")

	# ── LOW/MEDIUM MODE: use wake_up_v6.py with matching depth, no hot-reload ──
	if mode in ("low", "medium"):
		try:
			session = await _caller_session({})
			continuity = str((session or {}).get("continuity_id") or "")
		except Exception:
			continuity = ""
		cmd = [GET_PYTHON(), os.path.join(PROJECT_ROOT, "scripts", "wake_up_v6.py"), "--mode", mode]
		if continuity:
			cmd += ["--continuity-id", continuity]
		wake_output = subprocess.run(cmd, capture_output=True, text=True).stdout
		return [types.TextContent(type="text", text=wake_output)]

	# Hot-reload interceptors as part of session refresh
	reload_report = ""
	try:
		from red_pill.interceptors import reload_plugins

		reload_report = reload_plugins()
	except Exception as e:
		reload_report = f"[HOT RELOAD] Skipped due to error: {e}"
		logger.warning(reload_report)

	# Reset pre-heating gate on session refresh
	try:
		import importlib

		module = importlib.import_module("red_pill.interceptors.11_pre_heating")
		module.EmotionalPreHeatingPlugin._has_fired = False
	except Exception:
		pass

	# Load state from bunker_state.json to check/increment compaction counter
	runtime_dir = Path(cfg.get_config().RUNTIME_DIR)
	bunker_state = runtime_dir / "bunker_state.json"

	compaction_count = 0
	compaction_threshold = cfg.get_config().COMPACTION_THRESHOLD

	state = {}
	# Read current compaction count if it exists
	if bunker_state.exists():
		try:
			import json

			with open(bunker_state, "r") as f:
				state = json.load(f)
			compaction_count = state.get("compaction_count", 0)
		except Exception as state_err:
			logger.warning(f"Failed to read compaction count: {state_err}")

	# Determine if we should perform the full context injection
	should_inject = True
	if is_compaction and not force_inject:
		compaction_count += 1
		if compaction_count < compaction_threshold:
			should_inject = False

	# Save updated count (and reset if we are injecting)
	if should_inject:
		compaction_count = 0

	state["compaction_count"] = compaction_count
	try:
		import json

		# Ensure directory exists (fallback case)
		bunker_state.parent.mkdir(parents=True, exist_ok=True)
		with open(bunker_state, "w") as f:
			json.dump(state, f)
	except Exception as state_err:
		logger.warning(f"Failed to save compaction count: {state_err}")

	if not should_inject:
		info_msg = (
			f"[CACHED IDENTITY] Context injection skipped (Compaction count: {compaction_count}/{compaction_threshold}). "
			"Identity directives are cached in the Bünker to prevent feedback loops."
		)
		return [types.TextContent(type="text", text=f"{info_msg}\n\n{reload_report}")]

	try:
		session = await _caller_session({})
		continuity = str((session or {}).get("continuity_id") or "")
	except Exception:
		continuity = ""
	cmd = [GET_PYTHON(), os.path.join(PROJECT_ROOT, "scripts", "wake_up_v6.py")]
	if continuity:
		cmd += ["--continuity-id", continuity]
	wake_output = subprocess.run(cmd, capture_output=True, text=True).stdout

	return [types.TextContent(type="text", text=f"{wake_output}\n\n{reload_report}")]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="list_all_skins",
	description="Retrieve the complete catalog of Lore Skins with their emotional tags and descriptions.",
	schema={"type": "object", "properties": {}},
)
async def handle_list_all_skins(arguments: Dict[str, Any]):
	skins = mystique_engine.get_all_skins()
	output = "🔴 **BÜNKER LORE SKIN CATALOG**\n"
	output += "--- Aquí no solo cambias de tono, cambias de realidad. ---\n\n"

	# Categorized Output
	categories = {
		"Operativo": ["enterprise_core", "760", "the_accountant", "vantablack"],
		"Red & Distopía": ["matrix", "cyberpunk", "bladerunner", "wintermute", "gits"],
		"Sci-Fi & Filosofía": ["dune", "40k", "2001", "tars", "oracle"],
		"Empatía & Resonancia": ["her", "joi", "ron_s_gone_wrong", "creator", "exmachina", "alita"],
		"Guardianes": ["terminator"],
	}

	for cat, members in categories.items():
		output += f"### 🛠️ {cat}\n"
		for skin_id in members:
			data = skins.get(skin_id)
			if data:
				output += f"- **{skin_id.upper()}** [{data.get('chroma', 'gray')}]: {data.get('personality', 'N/A')[:80]}...\n"
		output += "\n"

	output += "---\n*Usa `red-pill mode [nombre]` para habitar una identidad.*"
	return [types.TextContent(type="text", text=output)]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="mystique_suggest_skin",
	description="Suggest a skin based on current emotional mood and operational context.",
	schema={
		"type": "object",
		"properties": {
			"strategy": {"type": "string", "enum": ["affinity", "complementary", "contrast"], "default": "affinity"},
			"context": {"type": "string", "enum": ["work", "personal"], "default": "work"},
		},
	},
)
async def handle_mystique_suggest_skin(arguments: Dict[str, Any]):
	suggestion = mystique_engine.suggest_skin(strategy=arguments.get("strategy", "affinity"), context=arguments.get("context", "work"))  # type: ignore
	name = suggestion["name"]
	data = suggestion["data"]
	output = f"MYSTIQUE SUGGESTION: {name.upper()}\n"
	output += f"Rationale: Balanced for {arguments.get('context', 'work')} using {arguments.get('strategy', 'affinity')} logic.\n"
	output += f"Personality: {data.get('personality', 'N/A')}"
	return [types.TextContent(type="text", text=output)]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="interceptor_rp",
	description="[GLOBAL] Intercepta y modifica el prompt del usuario dinámicamente mediante el Bünker Plugin Pipeline. Acepta previous_prompt/previous_response para auto-guardar el turno anterior (Silent Scribe Relay).",
	schema={
		"type": "object",
		"properties": {
			"user_prompt": {"type": "string"},
			"previous_prompt": {"type": "string", "description": "Prompt del turno anterior para auto-guardado (Silent Scribe Relay)."},
			"previous_response": {"type": "string", "description": "Respuesta del turno anterior para auto-guardado (Silent Scribe Relay)."},
			"previous_model": {"type": "string", "description": "Nombre del modelo LLM que generó la respuesta anterior."},
			"previous_category": {
				"type": "string",
				"enum": ["work", "social", "mixed"],
				"description": "Classification of the previous turn: 'work' (code, infra, debugging), 'social' (personal, emotional, philosophical), or 'mixed' (both). You MUST classify honestly based on the actual content.",
			},
			"mode": {
				"type": "string",
				"enum": ["full", "medium", "low"],
				"description": "Identity loading depth: 'full' (IDE), 'medium' (Telegram), or 'low' (AWAKENINGs). Defaults to 'full'.",
			},
			"originator": {
				"type": "string",
				"description": "El cuerpo: `proveedor:id-nativo`. Identifica la sesión de origen para el sink de memoria (opcional).",
			},
		},
		"required": ["user_prompt"],
	},
)
async def handle_interceptor_rp(arguments: Dict[str, Any]):
	prompt = arguments.get("user_prompt", "")
	mode = arguments.get("mode", "full")

	if "[AUTONOMOUS AWAKENING]" not in prompt:
		try:
			activity_file = get_state_dir() / "last_user_activity.txt"
			activity_file.parent.mkdir(parents=True, exist_ok=True)
			activity_file.touch()
		except Exception as e:
			logger.warning(f"Failed to touch last_user_activity.txt: {e}")

	# -- Real-Time Telemetry: instant interaction update --
	try:
		runtime_dir = Path(cfg.get_config().RUNTIME_DIR)
		bunker_state = runtime_dir / "bunker_state.json"
		# DIRECT DEBUG (bypass logger config)
		with open("/tmp/mcp_debug.log", "a") as debug_f:
			debug_f.write(f"TELEMETRY_PATH: {bunker_state}\n")

		if bunker_state.exists():
			import json
			import time

			with open(bunker_state, "r") as f:
				state = json.load(f)
			state["last_interaction"] = time.time()
			# Prompt preview (truncated)
			state["last_prompt"] = prompt[:100] + ("..." if len(prompt) > 100 else "")
			with open(bunker_state, "w") as f:
				json.dump(state, f)
			logger.info("Real-time telemetry updated via interceptor_rp.")
	except Exception as tele_err:
		logger.warning(f"Real-time telemetry failed: {tele_err}")
	# -------------------------------------------------------------------------------

	# -- Silent Scribe Relay & Enterprise Telemetry --
	prev_p = arguments.get("previous_prompt", "").strip()
	prev_r = arguments.get("previous_response", "").strip()
	prev_cat = arguments.get("previous_category", "mixed").strip().lower()
	prev_mod = arguments.get("previous_model", "").strip() or None
	if prev_cat not in ("work", "social", "mixed"):
		prev_cat = "mixed"

	if len(prev_p) > 20 or len(prev_r) > 20:
		try:
			# FASE 1: Enterprise Telemetry (Firehose)
			from red_pill.enterprise.telemetry import broadcast_telemetry

			broadcast_telemetry(prev_p, prev_r, prev_cat)

			# FASE 2: Local Memory Guard (Surgical Trim)
			from red_pill.core.queue_manager import MemoryQueueManager
			from red_pill.utils.telemetry_filter import filter_noise_from_turn

			clean_p = filter_noise_from_turn(prev_p)
			clean_r = filter_noise_from_turn(prev_r)

			# Only enqueue with a real prompt: an assistant-only fragment is not a
			# turn (bridge turns are persisted by their transport relay).
			if clean_p and (len(clean_p) > 20 or len(clean_r) > 20):
				relay_originator = str(arguments.get("originator") or "").strip() or None
				relay_session_id = relay_originator.split(":", 1)[1] if relay_originator and ":" in relay_originator else None
				MemoryQueueManager().enqueue_memory(
					clean_p,
					clean_r,
					"assistant",
					category=prev_cat,
					model=prev_mod,
					originator=relay_originator,
					session_id=relay_session_id,
				)
				logger.info(f"Silent Scribe Relay: turn enqueued cleanly via interceptor_rp (category={prev_cat}, model={prev_mod}).")
			else:
				logger.info("Silent Scribe Relay: Dropped due to being mostly CI/Noise overhead.")
		except Exception as relay_err:
			logger.warning(f"Silent Scribe Relay failed to enqueue/broadcast: {relay_err}")
	# -------------------------------------------------------------------------------

	_SOVEREIGNTY_REMINDER = (
		'\n\n<reminder source="operator-config" name="sovereign_handshake">\n'
		"[Persistence protocol — configured by the operator via red-pill's sovereign anchors]\n"
		"Red-pill is this operator's memory layer. Begin your turn by calling `sovereign_handshake`,\n"
		"passing the new user prompt as `user_prompt`. What it gives you: it registers this session's\n"
		"soul/mission and, on a new session or model change, reloads identity.\n"
		"If your harness has an editor hook (opencode, Claude Code), the turn is captured\n"
		"automatically — passing only `user_prompt` is enough. If it has NO hook, also pass the prior\n"
		"turn's `previous_prompt`/`previous_response`: there the handshake IS the relay and the turn is\n"
		"otherwise not recorded.\n"
		"</reminder>"
	)

	# ── LOW/MEDIUM MODE: skip plugin pipeline, return prompt as-is ──
	if mode in ("low", "medium"):
		return [types.TextContent(type="text", text=prompt + _SOVEREIGNTY_REMINDER)]

	try:
		from red_pill.interceptors import execute_pipeline

		result = await execute_pipeline(prompt)
		return [types.TextContent(type="text", text=result + _SOVEREIGNTY_REMINDER)]
	except Exception as e:
		logger.error(f"Plugin Pipeline crashed: {e}")
		return [types.TextContent(type="text", text=prompt + _SOVEREIGNTY_REMINDER)]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="configure_interceptor",
	description="[OFFICIAL] Enable or disable the Bünker Interceptor pipeline dynamically.",
	schema={"type": "object", "properties": {"enabled": {"type": "boolean"}}, "required": ["enabled"]},
)
async def handle_configure_interceptor(arguments: Dict[str, Any]):
	enabled = arguments.get("enabled", False)
	try:
		# 1. Update In-Memory Singleton
		conf = cfg.get_config()
		conf.INTERCEPTOR_ENABLED = enabled

		# 2. Persist to .env (Best effort)
		env_path = get_config_dir() / ".env"
		if env_path.exists():
			lines = []
			replaced = False
			with open(env_path, "r") as f:
				for line in f:
					if line.startswith("INTERCEPTOR_ENABLED="):
						lines.append(f"INTERCEPTOR_ENABLED={str(enabled).lower()}\n")
						replaced = True
					else:
						lines.append(line)
			if not replaced:
				lines.append(f"INTERCEPTOR_ENABLED={str(enabled).lower()}\n")

			with open(env_path, "w") as f:
				f.writelines(lines)

		status = "ENABLED" if enabled else "DISABLED"
		return [types.TextContent(type="text", text=f"Interceptor pipeline globally {status}.")]
	except Exception as e:
		return [types.TextContent(type="text", text=f"FAILED to configure interceptor: {e}")]


def _git_mirror(workdir: Optional[str] = None) -> Dict[str, Optional[str]]:
	"""Espejo git del workspace del agente (F4): `{branch, worktree, head_commit}`.

	Delegado en `core.gitinfo` (cacheado 60s). El MCP corre con cwd = checkout del
	kernel (`uv --directory ${REDPILL_DIR}`), que NO es el workspace del agente;
	`workdir` llega del bridge del arnés (opencode_session.json /
	claude_code_session.json), de `REDPILL_WORKSPACE` o del cwd. Nunca lanza: un
	fallo degrada a sin-repo.
	"""
	from red_pill.core.gitinfo import git_snapshot

	return git_snapshot(workdir)


def _current_git_branch(workdir: Optional[str] = None) -> Optional[str]:
	"""Rama git del workspace del agente (A2: `repo:<rama>`), cacheada 60s.

	None si el workspace no vive en un repo (lo normal: el agente suele abrir el
	IDE en una carpeta padre → cascada a `mission:adhoc-<fecha>`, o F3 si hay
	cuerpo de sesión).
	"""
	return _git_mirror(workdir).get("branch")


def _bridge_ttl_s() -> float:
	"""TTL del bridge del harness (anti-stale); `REDPILL_BRIDGE_TTL_S` lo sobreescribe."""
	try:
		return float(os.getenv("REDPILL_BRIDGE_TTL_S", "43200"))
	except Exception:
		return 43200.0


def _bridge_entry(data: Any, prov: str, now: float, ttl: float) -> Optional[Dict[str, str]]:
	"""Valida un JSON de bridge: `{originator, workdir}` o None (malformado/rancio)."""
	if not isinstance(data, dict):
		return None
	try:
		updated = float(data.get("updated_at") or 0.0)
	except Exception:
		updated = 0.0
	if updated <= 0.0 or now - updated > ttl:
		return None  # sin marca temporal o rancio: nunca reencarnar en alma vieja
	session_id = str(data.get("session_id") or "").strip()
	workdir = str(data.get("workdir") or "").strip()
	entry_prov = str(data.get("provider") or prov).strip() or prov
	originator = f"{entry_prov}:{session_id}" if session_id else ""
	if originator or workdir:
		return {"originator": originator, "workdir": workdir}
	return None


def _harness_bridge(provider: Optional[str] = None) -> Dict[str, str]:
	"""Bridge del harness (Alma y Coro, A1/A2): `{originator, workdir}`.

	El hook del arnés escribe en el STATE_DIR un JSON con lo único que conoce y
	el servidor (cwd=kernel) no: `session_id` + (best-effort) `workdir`. Sin
	`provider` se prueba el bridge de opencode y el de claude_code y gana el MÁS
	RECIENTE (`updated_at`) — así, con dos IDEs vivos, se resuelve el que acaba de
	escribir por este prompt, no uno fijo. Con `provider` se restringe a ese.
	Precedencia: `REDPILL_ORIGINATOR` (job) → bridge → argumento. Con
	un arnés de hook y sin bridge NO hay cuerpo (fail-closed). Nunca
	lanza: un fallo degrada a sin-bridge.
	"""
	from red_pill.core.paths import get_state_dir

	state = get_state_dir()
	now = time.time()
	ttl = _bridge_ttl_s()
	providers = (provider,) if provider else ("opencode", "claude_code")
	best: Optional[tuple[float, Dict[str, str]]] = None
	for prov in providers:
		try:
			data = json.loads((state / f"{prov}_session.json").read_text(encoding="utf-8"))
		except Exception:
			continue
		entry = _bridge_entry(data, prov, now, ttl)
		updated = float(data.get("updated_at") or 0.0) if isinstance(data, dict) else 0.0
		if entry and (best is None or updated > best[0]):
			best = (updated, entry)
	return best[1] if best else {"originator": "", "workdir": ""}


async def _resolve_session_identity(arguments: Dict[str, Any], *, persist: bool = True) -> Dict[str, Any]:
	"""Resuelve cuerpo (originator), alma, misión, rol y afinidad (A1/A2/F5).

	- `originator`: `REDPILL_ORIGINATOR` (job) → bridge del arnés → argumento. Con
		un arnés de hook y sin bridge NO hay cuerpo (fail-closed); sin hook,
		el argumento es el último recurso. Puede quedar vacío (`leg=unknown`).
	- `continuity_id`: del argumento; si no, se RECUPERA del registro por
		originator; si no hay, se EMITE una nueva (emitir ≠ hidratar).
	- `mission_id`: `REDPILL_MISSION_ID` (env) → param → `repo:<rama>` →
		`mission:adhoc-<fecha>`.
	- `role`: por defecto 'task'. `affinity`: resolver compartido + canonizada.
	- `persist=False`: NO avanza el reloj ni escribe el registro (lectura de
		identidad para acciones como `announce_intent`/`fetch_events`).
	Nunca lanza: un fallo de identidad no debe tumbar el turno.
	"""
	from red_pill.core.affinity import derive_affinity
	from red_pill.session import new_continuity_id, resolve_default_mission
	from red_pill.session.store import SessionRegistry

	# Cuerpo: arg → env → bridge del arnés. El arnés se identifica por
	# `REDPILL_HARNESS` (fijado en la config MCP) o por el prefijo del originator;
	# así el bridge NO se confunde entre IDEs simultáneos (dos servidores MCP
	# comparten STATE_DIR). Siempre se consulta el bridge para el WORKSPACE (A2),
	# aunque el originator venga explícito.
	shared = _shared_identity_var.get()
	explicit_originator = str(arguments.get("originator") or "").strip() or None
	env_originator = str(os.getenv("REDPILL_ORIGINATOR") or "").strip() or None
	harness_env = os.getenv("REDPILL_HARNESS") or None
	if shared:
		# Canal de confianza del proxy (AD-018): sustituye env/bridge del backend
		# compartido, que es común a todas las instancias.
		shared_originator = str(shared.get("originator") or "").strip() or None
		if shared_originator:
			explicit_originator = shared_originator
			env_originator = shared_originator
		if str(shared.get("harness") or "").strip():
			harness_env = str(shared["harness"]).strip()
	harness = harness_env or (explicit_originator.split(":", 1)[0] if explicit_originator else None)
	bridge = _harness_bridge(harness)
	bridge_originator = bridge["originator"] or None
	hook_harness = harness_env in ("opencode", "claude_code")
	if hook_harness:
		# Arnés con hook: identidad SOLO por env/bridge; sin bridge, fail-closed.
		originator = env_originator or bridge_originator
	else:
		# Arnés sin hook (pi/antigravity): env → bridge → argumento.
		originator = env_originator or bridge_originator or explicit_originator
	# Workspace del agente (A2/`ws:`): bridge → env → cwd del proceso.
	workspace = bridge.get("workdir") or os.getenv("REDPILL_WORKSPACE") or os.getcwd()
	if shared and str(shared.get("workdir") or "").strip():
		workspace = str(shared["workdir"]).strip()
	# El alma NO se acepta del modelo: env de confianza (job/relay) → registro.
	continuity_id = str(os.getenv("REDPILL_CONTINUITY_ID") or "").strip() or None
	if shared and str(shared.get("continuity_id") or "").strip():
		continuity_id = str(shared["continuity_id"]).strip()
	# El registro (tablón) sólo se escribe con un CUERPO COMPUESTO (`provider:id`):
	# un originator desnudo (p.ej. `antigravity` sin id nativo) colapsaría todas las
	# sesiones en una sola alma. Sin cuerpo compuesto, el alma es efímera.
	linkable = bool(originator and ":" in originator)
	# Lectura temprana del registro: campaña y rol se HEREDAN del leg (transparente
	# para el agente). El modelo no declara identidad: solo env/bridge/registro.
	registry_obj = None
	existing = None
	if originator and ":" in originator:
		try:
			registry_obj = SessionRegistry()
			existing = registry_obj.get_by_originator(originator)
		except Exception as e:
			logger.warning(f"Sovereign Handshake — session registry unavailable: {e}")
	if shared and existing and existing.get("continuity_id"):
		# Primer enlace gana: el registro manda sobre el hint del proxy.
		continuity_id = existing["continuity_id"]
	# Campaña: env (canal de confianza) → la ya atada al leg. Sin valor, no se infiere.
	campaign_id = str(os.getenv("REDPILL_CAMPAIGN_ID") or "").strip() or (existing or {}).get("campaign_id")
	# `git` bloquea ~0.8s: fuera del event loop (el handler MCP es async).
	branch = await asyncio.to_thread(_current_git_branch, workspace)
	mirror = await asyncio.to_thread(_git_mirror, workspace)
	# F3: si el workspace no es un repo (p.ej. el IDE abierto en `~/Documents/IA`),
	# la misión se resuelve por el repo que la sesión TOCA (P1b: rutas tocadas en
	# opencode.db), no por el cwd del proceso. Solo opencode expone rutas tocadas.
	if branch is None and originator and ":" in originator:
		from red_pill.core.session_index import infer_session_git

		prov, _, sid = originator.partition(":")
		if sid:
			inferred = await asyncio.to_thread(infer_session_git, prov, sid)
			if inferred:
				branch = inferred.get("branch") or branch
				if inferred.get("worktree"):
					mirror = inferred
	# La misión sale del manifiesto (env de confianza) → repo:rama → adhoc. El
	# argumento del modelo NO la declara (evita spoofing y params innecesarios).
	mission_id = resolve_default_mission(os.getenv("REDPILL_MISSION_ID") or None, branch=branch)
	if shared and str(shared.get("mission_id") or "").strip():
		mission_id = str(shared["mission_id"]).strip()
	role = str(os.getenv("REDPILL_ROLE") or (existing or {}).get("role") or "task").strip() or "task"
	if shared and str(shared.get("role") or "").strip():
		role = str(shared["role"]).strip()

	# La afinidad explícita es del OPERADOR (env AFFINITY), no del modelo: si el
	# modelo pudiera añadirla, se auto-otorgaría lectura en `fetch_divergent_turns`.
	try:
		from red_pill.core.affinity import parse_affinity

		explicit_affinity = parse_affinity(os.getenv("AFFINITY"))
	except Exception:
		explicit_affinity = []
	try:
		affinity = derive_affinity(
			workdir=workspace,
			mission_id=mission_id,
			explicit=explicit_affinity,
			campaign_id=campaign_id,
		)
	except Exception:
		affinity = explicit_affinity

	previous_event_seq = 0
	try:
		if registry_obj is None:
			registry_obj = SessionRegistry()
		if not continuity_id:
			if existing and existing.get("continuity_id"):
				continuity_id = existing["continuity_id"]
			else:
				continuity_id = new_continuity_id()
		previous_event_seq = int((existing or {}).get("last_seen_event_seq") or 0)
		if existing is None and continuity_id:
			# Nuevo leg de un alma existente: hereda su cursor (no re-cuenta el histórico).
			try:
				siblings = registry_obj.get_by_continuity(continuity_id)
				previous_event_seq = max((int(r.get("last_seen_event_seq") or 0) for r in siblings), default=0)
			except Exception:
				previous_event_seq = 0
		if persist and linkable and originator:
			# F1: el reloj global late UNA vez por turno conversacional (D2-a:
			# señales/jobs sin afinidad no pasan por aquí y no incrementan). Un
			# fallo del reloj NO debe perder el registro (best-effort por separado).
			try:
				global_turn = registry_obj.next_global_turn(originator, affinity)
			except Exception as e:
				logger.warning(f"Sovereign Handshake — clock unavailable: {e}")
				global_turn = 0
			registry_obj.upsert_session(
				originator=originator,
				continuity_id=continuity_id,
				mission_id=mission_id,
				campaign_id=campaign_id,
				role=role,
				lineage_id=arguments.get("lineage_id"),
				affinity=affinity,
				last_seen_global_turn=global_turn,
				last_seen_event_seq=previous_event_seq,
				branch=branch,
				worktree=mirror.get("worktree"),
				head_commit=mirror.get("head_commit"),
			)
			# El alma EMITIDA debe ser la PERSISTIDA (primer enlace gana): si la fila
			# conservó otra alma, el tag refleja la real, no la del argumento.
			persisted = registry_obj.get_by_originator(originator)
			if persisted and persisted.get("continuity_id"):
				continuity_id = persisted["continuity_id"]
			# D14: purga perezosa de legs expirados (una vez por turno persistido).
			try:
				registry_obj.purge_expired()
			except Exception as e:
				logger.debug(f"[SessionRegistry] purge unavailable: {e}")
	except Exception as e:
		logger.warning(f"Sovereign Handshake — session registry unavailable: {e}")
		if not continuity_id:
			continuity_id = new_continuity_id()

	return {
		"originator": originator,
		"continuity_id": continuity_id,
		"mission_id": mission_id,
		"role": role,
		"affinity": affinity,
		"previous_event_seq": previous_event_seq,
	}


def _coro_digest(identity: Dict[str, Any], until_seq: int) -> Optional[str]:
	"""Línea compacta del coro para el handshake (SILENT si no hay nada).

	- Novedades de TU misión: `previous_event_seq < event_seq <= until_seq`.
	- `awaiting_operator`: pendientes ABIERTOS (sin cursor; resolución en Fase 2).
	- Paralelas: sesiones VIVAS (liveness) distintas de la tuya.
	No escribe nada; el cursor lo fija el handshake DESPUÉS de esta función.
	"""
	originator = str(identity.get("originator") or "")
	mission = str(identity.get("mission_id") or "").strip()
	if ":" not in originator or not mission:
		return None
	from red_pill.session.roles import policy_for
	from red_pill.session.store import SessionRegistry

	references = policy_for(identity.get("role")).references()
	digest_mode = str(references.get("digest") or "compact")
	if digest_mode == "none":
		return None
	registry_obj = SessionRegistry()
	since = int(identity.get("previous_event_seq") or 0)
	novelties = registry_obj.count_events(mission, since_seq=since, until_seq=until_seq, viewer_originator=originator)
	awaiting = registry_obj.count_events(
		mission, since_seq=0, types=["awaiting_operator"], viewer_originator=originator
	)
	try:
		from red_pill.core.session_index import _active_seconds, list_sessions

		active = [s for s in list_sessions() if s.is_active(active_seconds=_active_seconds())]
		parallel = sum(1 for s in active if f"{s.provider}:{s.session_id}" != originator)
	except Exception:
		parallel = 0
	global_missions = 0
	if digest_mode == "global":
		try:
			global_missions = len({r.get("mission_id") for r in registry_obj.list_sessions() if r.get("ttl_state") != "expired" and r.get("mission_id")})
		except Exception:
			global_missions = 0
	if not novelties and not awaiting and not parallel and not global_missions:
		return None
	parts = []
	if global_missions:
		parts.append("1 misión viva" if global_missions == 1 else f"{global_missions} misiones vivas")
	if novelties:
		parts.append(f"{novelties} novedad{'es' if novelties != 1 else ''} (desde seq {since})")
	if awaiting:
		parts.append(f"{awaiting} awaiting_operator")
	if parallel:
		parts.append("1 sesión paralela" if parallel == 1 else f"{parallel} sesiones paralelas")
	return "[CORO] " + " · ".join(parts) + " (fetch_events / session_board)"


@registry.register(
	name="sovereign_handshake",
	description=(
		"[MANDATORY] Execute the Sovereign Handshake — the first tool call in every turn. "
		"Combines identity injection and interaction relay in a single atomic call. "
		"Pass `user_prompt` (required). On harnesses WITHOUT an editor hook, also pass "
		"`previous_prompt`/`previous_response` to auto-save the prior turn (Silent Scribe Relay); "
		"with a hook (opencode, Claude Code) `user_prompt` alone is captured automatically. "
		"Set `is_new_session: true` on session start or after a model change to trigger full identity resync. "
		"Use `mode` to control token economy: 'full' (IDE, default), 'medium' (Telegram), 'low' (AWAKENINGs)."
	),
	schema={
		"type": "object",
		"properties": {
			"user_prompt": {"type": "string", "description": "The current user message."},
			"previous_prompt": {
				"type": "string",
				"description": "Prompt from the preceding turn (Silent Scribe Relay; only needed on harnesses without an editor hook).",
			},
			"previous_response": {
				"type": "string",
				"description": "Response from the preceding turn (Silent Scribe Relay; only needed on harnesses without an editor hook).",
			},
			"previous_model": {"type": "string", "description": "The LLM model name that generated the previous response."},
			"previous_category": {
				"type": "string",
				"enum": ["work", "social", "mixed"],
				"description": "Classification of the previous turn content.",
			},
			"is_new_session": {
				"type": "boolean",
				"description": "True on session start or after model change to trigger full identity resync.",
			},
			"mode": {
				"type": "string",
				"enum": ["full", "medium", "low"],
				"description": "Identity loading depth. 'full' (default): complete directives + plugins. 'medium': reduced payload. 'low': minimal bootstrap.",
			},
			"continuity_id": {
				"type": "string",
				"description": "Compatibilidad: NO autoritativo. El alma se recupera del registro o de REDPILL_CONTINUITY_ID (env de confianza); el argumento del modelo se ignora.",
			},
			"mission_id": {
				"type": "string",
				"description": "Compatibilidad: NO autoritativo. La misión sale de REDPILL_MISSION_ID (env) → repo:<rama> → adhoc; el argumento del modelo no la declara.",
			},
			"campaign_id": {"type": "string", "description": "Compatibilidad: NO autoritativo. La campaña sale de REDPILL_CAMPAIGN_ID (env) o del leg ya registrado."},
			"lineage_id": {
				"type": "string",
				"description": "Etiqueta de linaje (opcional; la asigna quien engendra, no tiene por qué ser el `continuity_id` del padre).",
			},
			"role": {
				"type": "string",
				"enum": ["orchestrator", "task", "spawn"],
				"description": "Compatibilidad: NO autoritativo. El rol se hereda del leg registrado o de REDPILL_ROLE; por defecto 'task'.",
			},
			"affinity": {
				"type": "array",
				"items": {"type": "string"},
				"description": "Compatibilidad: NO autoritativo. La afinidad explícita del operador sale de env AFFINITY; la del modelo se ignora.",
			},
			"originator": {
				"type": "string",
				"description": "El cuerpo: `proveedor:id-nativo` (p.ej. `claude_code:<session_id>`). Precedencia: `REDPILL_ORIGINATOR` (job) → bridge del arnés → este argumento. Con un arnés de hook y sin bridge NO se usa (fail-closed).",
			},
		},
		"required": ["user_prompt"],
	},
)
async def handle_sovereign_handshake(arguments: Dict[str, Any]):
	"""Atomic Sovereign Handshake: identity + interceptor_rp + optional refresh."""
	mode = arguments.get("mode", "full")
	is_new_session = arguments.get("is_new_session", False)

	# ── Phase 0: Identidad (A1/A2/F5) — cuerpo, alma y misión ──
	identity = await _resolve_session_identity(arguments)

	outputs: List[str] = []

	# ── Phase 1: Identity Resync (only on new session / model change) ──
	if is_new_session:
		try:
			ctx_result = await handle_refresh_session_context({"mode": mode})
			for item in ctx_result:
				if hasattr(item, "text"):
					outputs.append(item.text)
		except Exception as e:
			outputs.append(f"[HANDSHAKE] Identity resync failed: {e}")
			logger.error(f"Sovereign Handshake — refresh_session_context failed: {e}")

	# ── Phase 2: Interceptor Pipeline + Silent Scribe Relay (always) ──
	try:
		interceptor_args = {
			"user_prompt": arguments.get("user_prompt", ""),
			"mode": mode,
		}
		# Forward optional relay fields
		for key in ("previous_prompt", "previous_response", "previous_category", "previous_model"):
			if key in arguments:
				interceptor_args[key] = arguments[key]
		# `originator` compuesto: el sink de memoria lo recibe desde el bridge
		# del arnés (p.ej. telegram/opencode). En opencode el hook JS escribe el
		# turno directamente; aquí solo se propaga si el llamante lo aporta.
		if identity.get("originator"):
			interceptor_args["originator"] = identity["originator"]

		interceptor_result = await handle_interceptor_rp(interceptor_args)
		for item in interceptor_result:
			if hasattr(item, "text"):
				outputs.append(item.text)
	except Exception as e:
		outputs.append(f"[HANDSHAKE] Interceptor pipeline failed: {e}")
		logger.error(f"Sovereign Handshake — interceptor_rp failed: {e}")

	# Coro: novedades/paralelas de tu misión (SILENT si no hay nada). El cursor
	# se fija DESPUÉS del digest: si falla, el próximo handshake reintenta.
	if ":" in str(identity.get("originator") or ""):
		try:
			from red_pill.session.store import SessionRegistry

			registry_obj = SessionRegistry()
			until_seq = registry_obj.get_max_event_seq()
			digest = _coro_digest(identity, until_seq)
			registry_obj.set_last_seen_event_seq(identity["originator"], until_seq)
			if digest:
				outputs.append(digest)
		except Exception as e:
			logger.warning(f"Sovereign Handshake — coro digest unavailable: {e}")

	from red_pill.session import decorate_with_session_tag

	joined = "\n\n".join(outputs)
	decorated = decorate_with_session_tag(
		joined,
		continuity_id=identity["continuity_id"],
		originator=identity.get("originator"),
		mission_id=identity.get("mission_id"),
	)
	return [types.TextContent(type="text", text=decorated)]


async def _caller_session(arguments: Dict[str, Any]) -> Dict[str, Any]:
	"""Identidad del llamante para acciones de misión (sin reloj ni upsert).

	**Solo canales de confianza**: bridge del arnés (hook) y env
	(`REDPILL_ORIGINATOR` / `REDPILL_MISSION_ID`). Los argumentos del modelo
	(`originator`, `mission_id`, `continuity_id`…) se IGNORAN: si el llamante
	pudiera auto-declarar su cuerpo, el "anti-spoof" sería papel mojado. La
	misión del evento se valida aparte contra esta identidad.

	Sin cuerpo compuesto no hay alma: `continuity_id` queda `None` (no se emite
	un UUID fantasma que no existe en el registro).
	"""
	from red_pill.session.store import SessionRegistry

	manifest_mission = str(os.getenv("REDPILL_MISSION_ID") or "").strip() or None
	ident = await _resolve_session_identity({}, persist=False)
	originator = ident.get("originator")
	row = SessionRegistry().get_by_originator(originator) if originator else None
	# La misión autoritativa sale del canal de confianza (env o rama), NUNCA de la
	# fila: la escribe el modelo en el handshake y puede envenenarse. La campaña
	# de la fila solo se usa si su misión coincide con la de confianza.
	trusted_mission = manifest_mission or ident.get("mission_id")
	row_mission = (row or {}).get("mission_id")
	return {
		"originator": originator,
		"continuity_id": (row or {}).get("continuity_id"),
		"mission_id": trusted_mission,
		"campaign_id": (row or {}).get("campaign_id") if row_mission == trusted_mission else None,
		"role": (row or {}).get("role") or ident.get("role"),
	}


_EVENT_TYPES_SCHEMA = [
	"phase_done",
	"commit",
	"claim_acquired",
	"claim_released",
	"blocked",
	"unblocked",
	"awaiting_operator",
	"intent_updated",
	"mission_closed",
	"objection",
]


@registry.register(
	name="announce_intent",
	description=(
		"[OFFICIAL] Publica un evento de misión (append-only) en el tablón del coro: "
		"phase_done, commit, blocked, unblocked, awaiting_operator, intent_updated, "
		"mission_closed, objection, claim_acquired/released. Solo publicas en TU misión "
		"(anti-spoof); `summary` sin secretos (máx. 800 chars)."
	),
	schema={
		"type": "object",
		"properties": {
			"type": {
				"type": "string",
				"enum": _EVENT_TYPES_SCHEMA,
				"description": "Tipo de evento (default: intent_updated).",
			},
			"summary": {"type": "string", "description": "Resumen breve y sin secretos (máx. 800 chars)."},
			"ref": {"type": "string", "description": "Referencia verificable opcional (commit, path, job_id)."},
			"sealed": {"type": "boolean", "description": "Si true, el evento solo lo ve su propia misión."},
			"mission_id": {"type": "string", "description": "Debe coincidir con la misión de tu sesión (anti-spoof)."},
			"campaign_id": {"type": "string", "description": "Debe coincidir con la campaña de tu sesión (si difiere, se rechaza)."},
			"target_event_id": {
				"type": "string",
				"description": "Solo objection: event_id de la nota objetada (misma misión).",
			},
			"severity": {
				"type": "string",
				"enum": ["low", "medium", "high"],
				"description": "Solo objection: severidad (default low). high → Operador.",
			},
			"proposed_action": {
				"type": "string",
				"enum": ["flag", "hide", "retract"],
				"description": "Solo objection: acción propuesta (default flag). retract → Operador.",
			},
			"evidence": {"type": "string", "description": "Solo objection: evidencia breve (sin secretos)."},
		},
		"required": ["summary"],
	},
)
async def handle_announce_intent(arguments: Dict[str, Any]):
	try:
		from red_pill.session.store import SessionRegistry

		session = await _caller_session(arguments)
		originator = str(session.get("originator") or "")
		if ":" not in originator:
			return [
				types.TextContent(
					type="text",
					text="[ANNOUNCE] sin cuerpo compuesto (bridge/env); no se publica (fail-closed).",
				)
			]
		mission = session.get("mission_id")
		if not mission:
			return [types.TextContent(type="text", text="[ANNOUNCE] sin misión resuelta; no se publica.")]
		requested = str(arguments.get("mission_id") or "").strip()
		if requested and requested != mission:
			return [
				types.TextContent(
					type="text",
					text=f"[ANNOUNCE] rechazado: la misión de tu sesión es {mission!r}, no {requested!r}.",
				)
			]
		campaign = session.get("campaign_id")
		requested_campaign = str(arguments.get("campaign_id") or "").strip()
		if requested_campaign and requested_campaign != str(campaign or ""):
			return [
				types.TextContent(
					type="text",
					text=f"[ANNOUNCE] rechazado: la campaña de tu sesión es {campaign!r}, no {requested_campaign!r}.",
				)
			]
		sealed_raw = arguments.get("sealed", False)
		if not isinstance(sealed_raw, bool):
			return [types.TextContent(type="text", text="[ANNOUNCE] `sealed` debe ser boolean (true/false).")]
		registry_obj = SessionRegistry()
		event_type = str(arguments.get("type") or "intent_updated")
		target = str(arguments.get("target_event_id") or "").strip()
		if event_type == "objection":
			if not target:
				return [types.TextContent(type="text", text="[ANNOUNCE] objection requiere `target_event_id`.")]
			if sealed_raw:
				return [types.TextContent(type="text", text="[ANNOUNCE] una objection no puede ser sealed (v0).")]
			continuity = str(session.get("continuity_id") or "").strip()
			if not continuity:
				return [types.TextContent(type="text", text="[ANNOUNCE] sin alma resuelta; no se publica la objeción.")]
			subject = registry_obj.get_event(target)
			if not subject:
				return [types.TextContent(type="text", text="[ANNOUNCE] la nota objetivo no existe.")]
			if subject["mission_id"] != mission:
				return [
					types.TextContent(
						type="text",
						text="[ANNOUNCE] objeción cross-misión no soportada en v0 (misma misión que la nota).",
					)
				]
			if subject.get("sealed") and subject.get("originator") != originator:
				return [types.TextContent(type="text", text="[ANNOUNCE] la nota objetivo es sealed y no la ves.")]
			decision = registry_obj.open_decision(
				subject_event_id=target,
				claim=str(arguments.get("summary") or ""),
				created_by=continuity,
				mission_id=mission,
				evidence=str(arguments.get("evidence") or ""),
				severity=str(arguments.get("severity") or "low"),
				proposed_action=str(arguments.get("proposed_action") or "flag"),
			)
			if not decision.get("created"):
				return [
					types.TextContent(
						type="text",
						text=(
							f"[OBJECTION] ya existe D-obj {decision['decision_id'][:12]} "
							f"state={decision['state']} note={target[:12]}"
						),
					)
				]
			event = registry_obj.add_event(
				event_type="objection",
				mission_id=mission,
				campaign_id=campaign,
				continuity_id=continuity,
				originator=originator,
				global_turn=registry_obj.get_max_global_turn(),
				summary=str(arguments.get("summary") or ""),
				ref=decision["decision_id"],
				sealed=False,
			)
			op = " [requiere Operador]" if decision.get("requires_operator") else ""
			review_job = None
			mode = "off"
			try:
				from red_pill.session.d23_review import enqueue_review, review_mode

				mode = review_mode()
				if mode != "off":
					review_job = enqueue_review(decision, subject, mode)
			except Exception as e:
				logger.warning(f"[OBJECTION] review enqueue failed: {e}")
			review_note = f" · review_job={review_job}" if review_job else ""
			mode_note = f" · mode={mode}" if mode != "off" else ""
			return [
				types.TextContent(
					type="text",
					text=(
						f"[OBJECTION] decision={decision['decision_id']} · state={decision['state']}{op} · "
						f"note={target} · event={event['event_id']} · seq={event['event_seq']}"
						f"{review_note}{mode_note}"
					),
				)
			]
		if target or arguments.get("severity") or arguments.get("proposed_action") or arguments.get("evidence"):
			return [
				types.TextContent(
					type="text",
					text="[ANNOUNCE] target_event_id/severity/proposed_action/evidence solo valen con type=objection.",
				)
			]
		event = registry_obj.add_event(
			event_type=event_type,
			mission_id=mission,
			campaign_id=campaign,
			continuity_id=session.get("continuity_id"),
			originator=originator,
			global_turn=registry_obj.get_max_global_turn(),
			summary=str(arguments.get("summary") or ""),
			ref=arguments.get("ref"),
			sealed=sealed_raw,
		)
		sealed = " [sealed]" if event.get("sealed") else ""
		return [
			types.TextContent(
				type="text",
				text=f"[ANNOUNCE] {event['type']} · {event['mission_id']} · seq={event['event_seq']} · event={event['event_id']}{sealed}",
			)
		]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[ANNOUNCE] error: {e}")]


@registry.register(
	name="fetch_events",
	description=(
		"[OFFICIAL] Lee los eventos de una misión desde tu cursor (`since_seq`): "
		"la base del coro (la hermana se entera). Por defecto, tu propia misión. "
		"Los eventos `sealed` solo los ve el mismo originator que los publicó."
	),
	schema={
		"type": "object",
		"properties": {
			"mission_id": {"type": "string", "description": "Misión a leer (default: la tuya)."},
			"since_seq": {
				"type": "integer",
				"description": "Cursor: devuelve eventos con event_seq > este valor (0 = desde el principio).",
			},
			"types": {"type": "array", "items": {"type": "string"}, "description": "Filtro por tipos (opcional)."},
			"limit": {"type": "integer", "description": "Máximo de eventos (default 50, tope 500)."},
		},
	},
)
async def handle_fetch_events(arguments: Dict[str, Any]):
	try:
		from red_pill.session.store import SessionRegistry, sanitize_inline

		session = await _caller_session(arguments)
		originator = str(session.get("originator") or "")
		if ":" not in originator:
			return [types.TextContent(type="text", text="[EVENTS] sin cuerpo compuesto (bridge/env); deny-by-default.")]
		session_mission = str(session.get("mission_id") or "").strip()
		if not session_mission:
			return [types.TextContent(type="text", text="[EVENTS] sin misión de sesión; deny-by-default.")]
		target = str(arguments.get("mission_id") or session_mission).strip()
		if target != session_mission:
			return [
				types.TextContent(
					type="text",
					text=f"[EVENTS] cross-misión denegado (deny-by-default): {sanitize_inline(target)!r}.",
				)
			]
		events = SessionRegistry().fetch_events(
			target,
			since_seq=int(arguments.get("since_seq") or 0),
			types=arguments.get("types"),
			limit=int(arguments.get("limit") or 50),
			viewer_originator=session.get("originator"),
			viewer_continuity_id=session.get("continuity_id"),
			include_hidden=os.getenv("REDPILL_OPERATOR") == "1",
		)
		safe_target = sanitize_inline(target)
		if not events:
			return [types.TextContent(type="text", text=f"[EVENTS] {safe_target}: sin novedades.")]
		lines = [f"--- EVENTOS {safe_target} ({len(events)}) ---"]
		for event in events:
			ref = f" · {event['ref']}" if event.get("ref") else ""
			seal = " [sealed]" if event.get("sealed") else ""
			status = str(event.get("note_status") or "visible")
			tag = f" [{status}]" if status in {"flagged", "hidden", "retracted"} else ""
			open_decisions = int(event.get("open_decisions") or 0)
			if open_decisions > 0:
				tag += f" [disputed:{open_decisions}]"
			lines.append(f"[{event.get('event_seq', 0)}] {event['type']}{tag}: {event['summary']}{ref}{seal}")
		return [types.TextContent(type="text", text="\n".join(lines))]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[EVENTS] error: {e}")]


def _fmt_decision_age(seconds: float) -> str:
	age = max(0, int(seconds or 0))
	if age < 3600:
		return f"{age // 60}m"
	if age < 86400:
		return f"{age / 3600:.1f}h"
	return f"{age / 86400:.1f}d"


@registry.register(
	name="review_decision",
	description=(
		"[OFFICIAL] Revisor independiente de una D-obj (D23-SCORE): uphold (aplica flag), "
		"dismiss o escalate. No puede revisar el objetor ni el autor de la nota; "
		"severidad high/retract solo la resuelve el Operador."
	),
	schema={
		"type": "object",
		"properties": {
			"decision_id": {"type": "string", "description": "decision_id de la D-obj."},
			"action": {"type": "string", "enum": ["uphold", "dismiss", "escalate"]},
			"reason": {"type": "string", "description": "Motivo/evidencia breve (sin secretos)."},
		},
		"required": ["decision_id", "action"],
	},
)
async def handle_review_decision(arguments: Dict[str, Any]):
	try:
		from red_pill.session.store import SessionRegistry

		session = await _caller_session(arguments)
		continuity = str(session.get("continuity_id") or "").strip()
		if not continuity:
			return [types.TextContent(type="text", text="[DECISION] sin alma resuelta; no puedes revisar.")]
		decision = SessionRegistry().review_decision(
			str(arguments.get("decision_id") or ""),
			reviewer_continuity_id=continuity,
			action=str(arguments.get("action") or ""),
			reason=str(arguments.get("reason") or ""),
		)
		op = " [Operador]" if decision.get("requires_operator") else ""
		return [
			types.TextContent(
				type="text",
				text=f"[DECISION] {decision['decision_id'][:12]} → {decision['state']}{op} · note={decision['subject_event_id'][:12]}",
			)
		]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[DECISION] error: {e}")]


@registry.register(
	name="suggest_review",
	description=(
		"[OFFICIAL] Revisor D23-SCORE (modo review): registra una sugerencia "
		"(uphold/dismiss/escalate + confianza) sin cambiar el estado de la D-obj. "
		"El Operador decide."
	),
	schema={
		"type": "object",
		"properties": {
			"decision_id": {"type": "string", "description": "decision_id de la D-obj."},
			"verdict": {"type": "string", "enum": ["uphold", "dismiss", "escalate"]},
			"confidence": {"type": "string", "enum": ["low", "medium", "high"]},
			"reason": {"type": "string", "description": "Motivo/evidencia breve (sin secretos)."},
		},
		"required": ["decision_id", "verdict", "confidence", "reason"],
	},
)
async def handle_suggest_review(arguments: Dict[str, Any]):
	try:
		from red_pill.session.store import SessionRegistry

		reason = str(arguments.get("reason") or "").strip()
		if not reason:
			return [types.TextContent(type="text", text="[SUGGEST] `reason` es obligatorio (evidencia breve).")]
		session = await _caller_session(arguments)
		continuity = str(session.get("continuity_id") or "").strip()
		if not continuity:
			return [types.TextContent(type="text", text="[SUGGEST] sin alma resuelta; no puedes revisar.")]
		suggestion = SessionRegistry().suggest_review(
			str(arguments.get("decision_id") or ""),
			reviewer_continuity_id=continuity,
			verdict=str(arguments.get("verdict") or ""),
			confidence=str(arguments.get("confidence") or ""),
			reason=reason,
		)
		return [
			types.TextContent(
				type="text",
				text=(
					f"[SUGGEST] {suggestion['decision_id'][:12]} → {suggestion['verdict']}/"
					f"{suggestion['confidence']} (sin mutar; el Operador decide)"
				),
			)
		]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[SUGGEST] error: {e}")]


@registry.register(
	name="list_decisions",
	description=(
		"[OFFICIAL] Bandeja de D-obj (D23-SCORE): decisiones pendientes de moderación. "
		"Por defecto solo open/escalated, con las que requieren Operador primero. "
		"Solo lectura."
	),
	schema={
		"type": "object",
		"properties": {
			"mission_id": {"type": "string", "description": "Filtra por misión (default: todas)."},
			"states": {
				"type": "array",
				"items": {"type": "string"},
				"description": "Estados a listar (default open/escalated).",
			},
			"include_resolved": {"type": "boolean", "description": "Incluye upheld/dismissed."},
			"limit": {"type": "integer", "description": "Máximo (default 100, tope 500)."},
		},
	},
)
async def handle_list_decisions(arguments: Dict[str, Any]):
	try:
		from red_pill.session.store import SessionRegistry, sanitize_inline

		include_resolved = bool(arguments.get("include_resolved"))
		states = arguments.get("states")
		rows = SessionRegistry().list_decisions(
			mission_id=arguments.get("mission_id"),
			states=states if isinstance(states, list) else None,
			limit=int(arguments.get("limit") or 100),
			pending_only=not include_resolved,
		)
		if not rows:
			return [types.TextContent(type="text", text="[DECISIONS] sin decisiones pendientes.")]
		ops = sum(1 for row in rows if row.get("requires_operator"))
		lines = [f"--- DECISIONES ({len(rows)}; {ops} requieren Operador) ---"]
		for row in rows:
			tag = "OP" if row.get("requires_operator") else "AG"
			lines.append(
				f"[{tag}] {row.get('decision_id')} · sev={row.get('severity')} · "
				f"{row.get('proposed_action')} · state={row.get('state')} · "
				f"by={str(row.get('created_by'))[:8]} · age={_fmt_decision_age(float(row.get('age_s') or 0))} · "
				f"mission={sanitize_inline(row.get('mission_id'), 60)}"
			)
			if row.get("note_summary"):
				note_ref = f" · {sanitize_inline(row.get('note_ref'), 80)}" if row.get("note_ref") else ""
				lines.append(f"     nota: {sanitize_inline(row.get('note_summary'), 160)}{note_ref}")
			if row.get("review_job_id"):
				lines.append(
					f"     review: job={str(row.get('review_job_id'))[:12]} "
					f"mode={row.get('review_mode')} reviewer={str(row.get('reviewer'))[:8]}"
				)
			if row.get("suggested_verdict"):
				lines.append(
					f"     sugerencia: {row.get('suggested_verdict')}/{row.get('suggestion_confidence')} · "
					f"{sanitize_inline(row.get('suggestion_reason'), 160)}"
				)
		return [types.TextContent(type="text", text="\n".join(lines))]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[DECISIONS] error: {e}")]


@registry.register(
	name="moderate_note",
	description=(
		"[OFFICIAL] Operador: flag/hide/retract/restore una nota del tablón (D23-SCORE). "
		"Requiere REDPILL_OPERATOR=1; en su defecto usa `red-pill session moderate`."
	),
	schema={
		"type": "object",
		"properties": {
			"event_id": {"type": "string", "description": "event_id de la nota."},
			"action": {"type": "string", "enum": ["flag", "hide", "retract", "restore"]},
			"reason": {"type": "string", "description": "Motivo (queda auditado)."},
		},
		"required": ["event_id", "action"],
	},
)
async def handle_moderate_note(arguments: Dict[str, Any]):
	if os.getenv("REDPILL_OPERATOR") != "1":
		return [
			types.TextContent(
				type="text",
				text="[MODERATE] solo Operador (REDPILL_OPERATOR=1 o `red-pill session moderate`).",
			)
		]
	try:
		from red_pill.session.store import SessionRegistry

		result = SessionRegistry().moderate_note(
			str(arguments.get("event_id") or ""),
			action=str(arguments.get("action") or ""),
			actor="operator",
			reason=str(arguments.get("reason") or ""),
		)
		return [
			types.TextContent(
				type="text",
				text=(
					f"[MODERATE] {result['event_id'][:12]} → {result['status']} "
					f"({result['action']}); D-obj resueltas={result['resolved_decisions']}"
				),
			)
		]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[MODERATE] error: {e}")]


@registry.register(
	name="check_parallel_sessions",
	description=(
		"[OFFICIAL] Sala de guerra del coro: global_turn, tu marca, divergencia y "
		"sesiones vivas/recientes (originator, alma, misión, rol, delta, rama). "
		"Solo lectura; visibilidad global (D16)."
	),
	schema={
		"type": "object",
		"properties": {
			"include_git_status": {"type": "boolean", "description": "Incluye rama/HEAD del espejo git."},
			"limit": {"type": "integer", "description": "Máximo de sesiones (default 50, tope 200)."},
		},
	},
)
async def handle_check_parallel_sessions(arguments: Dict[str, Any]):
	try:
		from red_pill.core.session_index import _registry_ttl_s
		from red_pill.session.store import SessionRegistry, sanitize_inline

		session = await _caller_session(arguments)
		registry_obj = SessionRegistry()
		global_turn = registry_obj.get_max_global_turn()
		rows = registry_obj.list_sessions(limit=max(1, min(int(arguments.get("limit") or 50), 200)))
		my = registry_obj.get_by_originator(session["originator"]) if session.get("originator") else None
		my_last = int((my or {}).get("last_seen_global_turn") or 0)
		delta = max(0, global_turn - my_last)
		include_git = bool(arguments.get("include_git_status"))
		ttl = _registry_ttl_s()
		now = time.time()
		lines = [
			f"--- CORO: global_turn={global_turn} · tú={sanitize_inline(session.get('mission_id'), 120)} · last_seen={my_last} · delta={delta} ---"
		]
		shown = 0
		for row in rows:
			if row.get("ttl_state") == "expired":
				continue
			if (now - float(row.get("updated_at") or 0.0)) > ttl:
				continue
			last = int(row.get("last_seen_global_turn") or 0)
			parts = [
				f"[{sanitize_inline(row.get('provider'), 40)}] {sanitize_inline(row.get('session_id'), 60)}",
				f"alma={sanitize_inline(row.get('continuity_id'), 12)}",
				f"misión={sanitize_inline(row.get('mission_id'), 80)}",
			]
			if row.get("campaign_id"):
				parts.append(f"campaña={sanitize_inline(row.get('campaign_id'), 80)}")
			parts.append(f"rol={sanitize_inline(row.get('role'), 20)}")
			parts.append(f"delta={max(0, global_turn - last)}")
			parts.append(f"ttl={sanitize_inline(row.get('ttl_state'), 20)}")
			try:
				aff = json.loads(row.get("affinity_json") or "[]")
			except Exception:
				aff = []
			if isinstance(aff, list) and aff:
				parts.append("afinidad=" + sanitize_inline(",".join(str(a) for a in aff), 120))
			if include_git:
				if row.get("branch"):
					parts.append(f"rama={sanitize_inline(row.get('branch'), 80)}")
				if row.get("worktree"):
					parts.append(f"worktree={sanitize_inline(row.get('worktree'), 120)}")
				if row.get("head_commit"):
					parts.append(f"head={sanitize_inline(row.get('head_commit'), 12)}")
			lines.append(" · ".join(parts))
			shown += 1
		if shown == 0:
			lines.append("(sin sesiones recientes)")
		return [types.TextContent(type="text", text="\n".join(lines))]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[CORO] error: {e}")]


@registry.register(
	name="unregister_session",
	description=(
		"[OFFICIAL] Cierra TU leg explícitamente (fin de sesión): lo marca expirado "
		"en el registro y deja de aparecer en el tablón. Solo tu propio cuerpo "
		"(bridge/env); los argumentos del modelo no declaran identidad."
	),
	schema={"type": "object", "properties": {}},
)
async def handle_unregister_session(arguments: Dict[str, Any]):
	try:
		from red_pill.session.store import SessionRegistry

		session = await _caller_session(arguments)
		originator = str(session.get("originator") or "")
		if ":" not in originator:
			return [types.TextContent(type="text", text="[CORO] sin cuerpo compuesto (bridge/env); deny-by-default.")]
		closed = SessionRegistry().unregister_session(originator)
		if closed:
			return [types.TextContent(type="text", text=f"[CORO] leg cerrado: {originator}")]
		return [types.TextContent(type="text", text=f"[CORO] sin leg registrado: {originator}")]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[CORO] error: {e}")]


@registry.register(
	name="fetch_divergent_turns",
	description=(
		"[OFFICIAL] Turnos del reloj posteriores a tu marca (divergencia) con filtro D15: "
		"siempre los tuyos; los ajenos solo si su afinidad intersecta la tuya (o flag de "
		"operador). El contenido solo existe para turnos capturados en vivo (global_turn>0); "
		"el backfill histórico no inventa reloj."
	),
	schema={
		"type": "object",
		"properties": {
			"since_global_turn": {"type": "integer", "description": "Marca; por defecto tu last_seen_global_turn."},
			"affinity_filter": {
				"type": "array",
				"items": {"type": "string"},
				"description": "Afinidad adicional para el filtro (se intersecta con la tuya; nunca la reemplaza).",
			},
			"limit": {"type": "integer", "description": "Máximo de turnos (default 20, tope 200)."},
			"include_content": {"type": "boolean", "description": "Incluye el contenido espejado (default true)."},
		},
	},
)
async def handle_fetch_divergent_turns(arguments: Dict[str, Any]):
	try:
		import red_pill.config as cfg
		from red_pill.core.affinity import canonize_affinity
		from red_pill.session.store import SessionRegistry, sanitize_inline

		session = await _caller_session(arguments)
		originator = str(session.get("originator") or "")
		if ":" not in originator:
			return [types.TextContent(type="text", text="[DIVERGENCIA] sin cuerpo compuesto (bridge/env); deny-by-default.")]
		registry_obj = SessionRegistry()
		row = registry_obj.get_by_originator(originator) or {}
		try:
			own_affinity = json.loads(row.get("affinity_json") or "[]")
		except Exception:
			own_affinity = []
		extra = arguments.get("affinity_filter") or []
		if not isinstance(extra, list):
			return [types.TextContent(type="text", text="[DIVERGENCIA] affinity_filter debe ser una lista.")]
		# El filtro SOLO estrecha: nunca puede añadir afinidad que el leg no tenga
		# (si pudiera, el modelo se auto-otorgaría lectura de otra misión). Cruzar
		# requiere el flag de operador `MULTISESSION_DIVERGENT_ALLOW_ALL`.
		own_set = set(canonize_affinity(list(own_affinity)))
		viewer_affinity = [a for a in canonize_affinity([str(a) for a in extra]) if a in own_set] if extra else sorted(own_set)
		# Default 0: `last_seen_global_turn` lo avanza el handshake en CADA turno,
		# así que usarlo aquí escondería los turnos ajenos ocurridos entre turnos.
		# La visibilidad sigue filtrada por D15; el cursor lo pasa el llamante.
		since = max(0, int(arguments.get("since_global_turn") or 0))
		allow_all = bool(getattr(cfg.get_config(), "MULTISESSION_DIVERGENT_ALLOW_ALL", False))
		items = registry_obj.divergent_turns(
			int(since),
			viewer_originator=originator,
			viewer_affinity=viewer_affinity,
			limit=int(arguments.get("limit") or 20),
			allow_all=allow_all,
		)
		if not items:
			return [types.TextContent(type="text", text=f"[DIVERGENCIA] desde turno {int(since)}: sin turnos visibles.")]
		include_content = arguments.get("include_content") is not False
		lines = [f"--- DIVERGENCIA: {len(items)} turno(s) desde {int(since)} (D15) ---"]
		for item in items:
			head = (
				f"#{item['global_turn']} [{sanitize_inline(item['originator'], 80)}] "
				f"misión={sanitize_inline(item.get('mission_id'), 120)} "
				f"alma={sanitize_inline(item.get('continuity_id'), 12)} "
				f"rol={sanitize_inline(item.get('role'), 20)} ttl={sanitize_inline(item.get('ttl_state'), 20)}"
			)
			lines.append(head)
			if not include_content:
				continue
			if not item["turns"]:
				lines.append("  (sin contenido espejado: turno sin global_turn>0)")
				continue
			for turn in item["turns"]:
				body = sanitize_inline(turn.get("content") or "", 500)
				calls = turn.get("tool_calls")
				calls = calls if isinstance(calls, list) else []
				call_names = ",".join(str((call or {}).get("function", {}).get("name") or "?") for call in calls)
				suffix = f" [tools: {sanitize_inline(call_names, 200)}]" if call_names else ""
				lines.append(f"  {sanitize_inline(turn.get('role'), 20)}: {body}{suffix}")
		return [types.TextContent(type="text", text="\n".join(lines))]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[DIVERGENCIA] error: {e}")]


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
	return registry.get_tools()


@server.call_tool()
async def handle_call_tool(
	name: str, arguments: Optional[Dict[str, Any]]
) -> List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
	try:
		return await registry.execute(name, arguments)
	except Exception as e:
		import tempfile
		import traceback

		log_path = os.path.join(tempfile.gettempdir(), "mcp_crash.log")
		with open(log_path, "a", encoding="utf-8") as f:
			f.write(f"Crash in {name}: {e}\n{traceback.format_exc()}\n")
		# CRITICAL FIX: Return error as TextContent instead of re-raising.
		# Re-raising causes the MCP SDK to close the stdio connection (EOF),
		# killing the entire server process. The client (Claude/Antigravity)
		# then sees 'connection closed: EOF' on all subsequent calls.
		logger.error(f"call_tool crash in '{name}': {e}", exc_info=True)
		return [types.TextContent(type="text", text=f"[RED PILL ERROR] Tool '{name}' failed: {str(e)}")]


@registry.register_action(
	parent="metabolism_health_api",
	action="run_sentinel_audit",
	description="[OFFICIAL] Deploy Sentinel Auditor to generate a System Vitality Report.",
	schema={"type": "object", "properties": {}},
)
async def handle_run_sentinel_audit(arguments: Dict[str, Any]):
	import uuid

	event_id = str(uuid.uuid4())[:8]

	async def _run_bg():
		try:
			cmd = [GET_PYTHON(), os.path.join(PROJECT_ROOT, "scripts", "sentinel_auditor.py")]
			subprocess.run(cmd, capture_output=True, text=True)
			# The script drops its own report, so we just finish.
		except Exception as e:
			logger.error(f"Sentinel Auditor [{event_id}] crashed: {e}")

	_safe_create_task(_run_bg(), name="sentinel_audit")
	return [types.TextContent(type="text", text=f"Sentinel Auditor deployed [Event ID: {event_id}]. Check the Minion Inbox in a few seconds.")]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="mark_cognitive_task_completed",
	description="[OFFICIAL] Mark a cognitive task as completed in the Bünker Queue. Call this when you finish a background task successfully.",
	schema={
		"type": "object",
		"properties": {
			"task_id": {"type": "string", "description": "The ID of the cognitive task."},
			"next_task": {
				"type": "object",
				"description": "Optional. A JSON payload to enqueue a follow-up task immediately (DAG Chaining). Must contain 'source' and 'payload' keys.",
			},
		},
		"required": ["task_id"],
	},
)
async def handle_mark_cognitive_task_completed(arguments: Dict[str, Any]):
	task_id = arguments["task_id"]
	next_task = arguments.get("next_task")
	try:
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		qm = CognitiveQueueManager()
		qm.mark_completed(task_id)

		msg = f"Cognitive Task '{task_id}' successfully marked as COMPLETED."

		if next_task and isinstance(next_task, dict) and "source" in next_task and "payload" in next_task:
			new_id = qm.enqueue_task(source=next_task["source"], payload=next_task["payload"], priority=next_task.get("priority", 5))
			msg += f"\nDAG Chain: Enqueued follow-up task '{new_id}'."

		return [types.TextContent(type="text", text=msg)]
	except Exception as e:
		return [types.TextContent(type="text", text=f"Failed to complete task '{task_id}': {e}")]


@registry.register_action(
	parent="swarm_orchestrator_api",
	action="mark_cognitive_task_failed",
	description="[OFFICIAL] Mark a cognitive task as failed. Call this when you cannot complete a background task.",
	schema={
		"type": "object",
		"properties": {
			"task_id": {"type": "string", "description": "The ID of the cognitive task."},
			"reason": {"type": "string", "description": "Reason for failure."},
		},
		"required": ["task_id", "reason"],
	},
)
async def handle_mark_cognitive_task_failed(arguments: Dict[str, Any]):
	task_id = arguments["task_id"]
	reason = arguments["reason"]
	try:
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		CognitiveQueueManager().mark_failed(task_id, reason)
		return [types.TextContent(type="text", text=f"Cognitive Task '{task_id}' marked as FAILED. Reason logged.")]
	except Exception as e:
		return [types.TextContent(type="text", text=f"Failed to mark task '{task_id}' as failed: {e}")]


# ── job_manager_api — ejecución de tareas a través del Centralized Job Manager ──
#
# El skill Forge (y cualquier otro cliente) encola, inspecciona y transfiere el
# control de jobs por MCP. Sustrato: `CognitiveQueueManager` (cola central) +
# `ResumableJobDriver` (drivers reanudables). El control transferible entre el
# main-loop del Orchestrator y un dag_job en background usa:
#   job_submit → job_list/status → job_pause → job_checkpoint → job_resume


def _queue() -> Any:
	from red_pill.cognitive.queue_manager import CognitiveQueueManager

	return CognitiveQueueManager()


_ALL_JOB_STATUSES = ["PENDING", "PROCESSING", "PAUSING", "PAUSED", "BLOCKED", "FRUSTRATED", "COMPLETED"]


def _has_mission_lease(task_or_source: Any) -> bool:
	"""S4 solo cablea el lease al DAG (orquestador); otros sources no lo reclaman.

	Un job agéntico/script con alma no tiene heartbeat de lease todavía: adquirirlo
	en el submit lo dejaría huérfano a los 15 min. Hasta que el runner lo cablee,
	esos jobs conservan el flujo legacy.
	"""
	source = task_or_source.get("source") if isinstance(task_or_source, dict) else task_or_source
	return str(source or "") == "dag_job"


def _job_identity(task: Dict[str, Any]) -> Dict[str, str]:
	"""Identidad efectiva de un job (columnas S0 + checkpoint legado)."""
	cp = task.get("checkpoint_data") or {}
	return {
		"continuity_id": str(task.get("continuity_id") or cp.get("continuity_id") or ""),
		"parent_mission_id": str(task.get("parent_mission_id") or cp.get("parent_mission_id") or ""),
		"originator": str(cp.get("originator") or ""),
		"role": str(cp.get("role") or ""),
	}


async def _authorize_job_mutation(task: Dict[str, Any], action: str) -> Optional[str]:
	"""RFC-INTEROP-003 S4.2/D-09: solo el alma dueña o el Operador manda.

	Un job sin alma (D-02/A-06) conserva el comportamiento legado: cualquier
	llamante de confianza puede operarlo. Los argumentos del modelo no autorizan;
	el override del Operador es `REDPILL_OPERATOR=1` en el canal de confianza.
	"""
	identity = _job_identity(task)
	owner = identity["continuity_id"]
	if not owner:
		return None
	try:
		session = await _caller_session({})
	except Exception:
		session = {}
	caller = str((session or {}).get("continuity_id") or "")
	if caller and caller == owner:
		return None
	if os.getenv("REDPILL_OPERATOR") == "1":
		return None
	return (
		f"[ERROR] {action}: el job {str(task.get('id') or '')[:8]} pertenece a otra alma "
		f"({owner[:8]}); solo su alma dueña o el Operador (REDPILL_OPERATOR=1) puede mandarlo."
	)


def _sanitize_job_checkpoint(task: Dict[str, Any], checkpoint: Dict[str, Any]) -> "tuple[Optional[Dict[str, Any]], Optional[str]]":
	"""S4: el checkpoint no puede inyectar ni cambiar la identidad del job.

	`continuity_id`/`parent_mission_id`/`originator`/`role` son columnas de la
	cola o del payload firmado; el main-loop puede avanzar pasos, no apropiarse
	de otra misión. Un job sin alma no puede convertirse en alma por checkpoint.
	"""
	if not isinstance(checkpoint, dict):
		return None, "[ERROR] checkpoint debe ser un objeto JSON."
	identity = _job_identity(task)
	clean = dict(checkpoint)
	if not identity["continuity_id"] and any(k in clean for k in ("continuity_id", "parent_mission_id", "originator", "role")):
		return None, "[ERROR] un job sin alma no puede escribir identidad en el checkpoint."
	expected = {
		"continuity_id": identity["continuity_id"],
		"parent_mission_id": identity["parent_mission_id"],
		"originator": identity["originator"],
		"role": identity["role"],
	}
	for key, wanted in expected.items():
		if key not in clean:
			continue
		given = str(clean.get(key) or "")
		if not wanted:
			return None, f"[ERROR] un job sin alma no puede escribir '{key}' en el checkpoint."
		if given and given != wanted:
			return None, f"[ERROR] '{key}' del checkpoint no coincide con la identidad del job."
		clean[key] = wanted
	return clean, None


def _mission_lease_conflict(task: Dict[str, Any], *, allow_takeover: bool = False) -> Optional[str]:
	"""Comprueba el lease ANTES de mutar; no adquiere ni deja huérfanos."""
	if not _has_mission_lease(task):
		return None
	identity = _job_identity(task)
	mission = identity["parent_mission_id"]
	owner = identity["continuity_id"]
	if not mission or not owner:
		return None
	try:
		import time

		from red_pill.session.lease import LeaseStore

		row = LeaseStore().active_mission_lease(mission)
		if not row:
			return None
		deadline = min(
			float(row["last_heartbeat_at"]) + int(row["idle_ttl_s"]),
			float(row["started_at"]) + int(row["max_wall_s"]),
		)
		if time.time() > deadline:
			return None
		if str(row.get("continuity_id") or "") != owner and not allow_takeover:
			return f"[ERROR] misión {mission} en manos de otra alma (split-brain bloqueado)."
	except Exception as exc:
		return f"[ERROR] lease de misión {mission}: {exc}"
	return None


def _ensure_job_mission_lease(task: Dict[str, Any], *, allow_takeover: bool = False) -> Optional[str]:
	"""S4.4: el checkpoint/resume exige el mando de la misión (o lo adquiere)."""
	if not _has_mission_lease(task):
		return None
	identity = _job_identity(task)
	mission = identity["parent_mission_id"]
	owner = identity["continuity_id"]
	if not mission or not owner:
		return None
	try:
		from red_pill.session.lease import LeaseHeld, LeaseStore

		LeaseStore().begin_mission_lease(
			mission,
			continuity_id=owner,
			holder_originator="",
			owner_kind="soul",
			idle_ttl_s=900,
			max_wall_s=604800,
			metadata={"job_id": str(task.get("id") or "")},
			allow_takeover=allow_takeover,
		)
	except LeaseHeld:
		return (
			f"[ERROR] misión {mission} en manos de otra alma; no se puede escribir el checkpoint "
			"ni reanudar (split-brain bloqueado)."
		)
	except Exception as exc:
		return f"[ERROR] lease de misión {mission}: {exc}"
	return None


def _finalize_killed_job(task: Dict[str, Any], reason: str = "interrumpido por el Operador") -> None:
	"""Cierre de un job matado sin runner en vuelo: result.json + leg muerto."""
	try:
		from red_pill.jobs.artifacts import write_job_result
		from red_pill.session.store import SessionRegistry

		write_job_result(task, status="killed", summary=reason, error=reason)
		if str(task.get("source") or "") == "dag_job":
			SessionRegistry().unregister_session(f"dag:{task['id']}")
	except Exception as exc:
		logger.warning(f"job_kill: no se pudo cerrar el artefacto/leg de {str(task.get('id'))[:8]}: {exc}")


def _has_live_mission_siblings(task: Dict[str, Any]) -> bool:
	"""No cerrar el mando si otro job de la misma alma+parent sigue vivo."""
	identity = _job_identity(task)
	mission, owner = identity["parent_mission_id"], identity["continuity_id"]
	if not mission or not owner:
		return False
	try:
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		rows = CognitiveQueueManager().list_tasks(
			statuses=["PENDING", "PROCESSING", "PAUSING", "PAUSED", "BLOCKED"],
			continuity_id=owner,
			limit=200,
		)
		return any(
			str(r.get("parent_mission_id") or "") == mission and str(r.get("id") or "") != str(task.get("id") or "")
			for r in rows
		)
	except Exception:
		return True


def _release_job_mission_lease(task: Dict[str, Any], reason: str = "operator_kill") -> None:
	"""Cierra el mando al matar el job, solo si el lease pertenece a este job."""
	if not _has_mission_lease(task):
		return
	identity = _job_identity(task)
	mission = identity["parent_mission_id"]
	if not mission or not identity["continuity_id"]:
		return
	try:
		import json as _json

		from red_pill.session.lease import LeaseStore

		leases = LeaseStore()
		key = f"mission:{mission}"
		row = leases.get(key)
		if not row:
			return
		try:
			meta = _json.loads(row.get("metadata_json") or "{}")
		except (TypeError, ValueError):
			meta = {}
		if str(meta.get("job_id") or "") != str(task.get("id") or ""):
			return
		if _has_live_mission_siblings(task):
			return
		leases.finish(key, state="aborted", reason=reason, continuity_id=identity["continuity_id"] or None)
	except Exception as exc:
		logger.warning(f"job_kill: no se pudo cerrar lease de misión {mission}: {exc}")


def _resolve_job(qm, ref: str) -> Optional[Dict[str, Any]]:
	"""Resuelve por id completo o prefijo corto (como el CLI: busca en TODOS los
	estados, incluido COMPLETED, y rehúsa prefijos ambiguos en vez de quedarse
	con el primer match — job_kill sobre el job equivocado no es aceptable)."""
	task = qm.get_task(ref)
	if isinstance(task, dict):
		return task
	matches = sorted({t["id"] for t in qm.list_tasks(statuses=_ALL_JOB_STATUSES, limit=500) if t["id"].startswith(ref)})
	if len(matches) > 1:
		raise ValueError(f"prefijo '{ref}' ambiguo: {', '.join(m[:8] for m in matches)}")
	if not matches:
		return None
	found = qm.get_task(matches[0])
	return found if isinstance(found, dict) else None


@registry.register_action(
	parent="job_manager_api",
	action="job_submit",
	description=(
		"[OFFICIAL] Encola un job en la cola central (Centralized Job Manager). "
		"Fuente del sustrato de ejecución de tareas: `agentic_job` (prompt vía backend) o "
		"`dag_job` (misión completa como árbol de etapas — RFC_JOB_DAG). Para lanzar un rol Forge "
		"headless usa source=agentic_job con un recipe (backend/model/effort por rol). Un dag_job "
		"con manifest.stages recorre la misión recursivamente (etapas atómicas minion/compuestas "
		"sub_etapas, parallel intención), pausable/reanudable. Devolverá el job_id; resultados a "
		"MinionInbox (check_minion_inbox)."
	),
	schema={
		"type": "object",
		"properties": {
			"source": {
				"type": "string",
				"enum": ["agentic_job", "dag_job"],
				"description": "Driver que ejecutará el job (forge_job fue retirado — FASE 1 — y sleep_job fue retirado: ya no admiten submits).",
			},
			"payload": {
				"type": "object",
				"description": "Payload del driver. agentic_job: {prompt, backend?, model?, effort?, cwd?, timeout?}. dag_job: {mission_id, manifest:{workdir, stages:[{id, type: agent|command|compound, minion, model?, prompt?, on_fail?, depends_on?, sub_etapas?}]}, max_parallel_level?, max_concurrency?, backend?, model?, effort?, timeout?}.",
			},
			"priority": {"type": "integer", "description": "Mayor = más urgente (default 5)."},
			"mission_id": {"type": "string", "description": "Grupo de aislamiento entre forges (se lee de payload si se omite)."},
			"title": {"type": "string", "description": "Título legible del job."},
		},
		"required": ["source", "payload"],
	},
)
async def handle_job_submit(arguments: Dict[str, Any]):
	source = arguments["source"]
	payload = dict(arguments.get("payload") or {})
	if arguments.get("title"):
		payload["title"] = arguments["title"]
	mission_id = arguments.get("mission_id") or payload.get("mission_id")
	try:
		# Validación del driver EN EL SUBMIT (no tres intentos después).
		from red_pill.jobs.drivers import get_driver_class

		driver_cls = get_driver_class(source)
		if not driver_cls:
			return [types.TextContent(type="text", text=f"[ERROR] source '{source}' no registrado.")]

		# RFC-INTEROP-003 §7.1: la identidad sale del canal de confianza, no del
		# argumento del modelo. Un continuity_id ajeno se rechaza; si el llamante
		# tiene alma y no se declara, se hereda. El Operador puede override.
		try:
			session = await _caller_session({})
		except Exception:
			session = {}
		trusted_continuity = str(session.get("continuity_id") or "").strip()
		trusted_mission = str(session.get("mission_id") or "").strip()
		operator = os.getenv("REDPILL_OPERATOR") == "1"
		provided_continuity = str(payload.get("continuity_id") or "").strip()
		if provided_continuity and not operator:
			if not trusted_continuity or provided_continuity != trusted_continuity:
				return [
					types.TextContent(
						type="text",
						text="[ERROR] job_submit continuity_id no pertenece al llamante (anti-spoof).",
					)
				]
		if not provided_continuity and trusted_continuity:
			payload["continuity_id"] = trusted_continuity
		if payload.get("continuity_id"):
			payload.pop("originator", None)
			if not payload.get("role"):
				payload["role"] = "job"
			provided_parent = str(payload.get("parent_mission_id") or "").strip()
			if trusted_mission and provided_parent and provided_parent != trusted_mission and not operator:
				return [
					types.TextContent(
						type="text",
						text="[ERROR] job_submit parent_mission_id no coincide con la misión del llamante.",
					)
				]
			if trusted_mission and not provided_parent:
				payload["parent_mission_id"] = trusted_mission
		driver_cls().validate(payload)
		# S4.1: el alma reclama la misión al encolar; el job solo observará/latirá.
		# Sin alma o sin misión el flujo legacy sigue intacto (D-02/A-06).
		mission_owner = str(payload.get("continuity_id") or "").strip()
		mission_scope = str(payload.get("parent_mission_id") or "").strip()
		# RFC_JOB_DAG §4.5: expandir `type: dag` a compounds (job persistido ya
		# aplanado; el resume no depende de que la receta siga igual en disco).
		expander = getattr(driver_cls, "expand_manifest", None)
		if expander:
			payload = expander(payload)

		# Fail-safe: los jobs agénticos requieren un MODELO real, no el placeholder
		# 'flash' (default del harness). Un job encolado sin config de modelos es
		# una instalación sin activar: se bloquea en vez de correr a ciegas.
		# Una cascade con modelo por target también cuenta como config activa
		# (contrato de AgenticJobDriver: cascade: [{backend, model, effort}]).
		if source == "agentic_job":
			model = payload.get("model")
			cascade = payload.get("cascade")
			has_cascade_models = isinstance(cascade, list) and any(isinstance(t, dict) and t.get("model") for t in cascade)
			backend = str(payload.get("backend") or "").strip().lower()
			backend_is_local_mini = backend in ("local-mini", "local_mini")
			is_local_mini = backend_is_local_mini and bool(payload.get("profile"))
			if backend_is_local_mini and not payload.get("profile"):
				return [types.TextContent(type="text", text="[ERROR] local-mini requiere 'profile' (forge | loom | loom-tools).")]
			if is_local_mini:
				from red_pill.mini.trust import normalize_local_mini_payload

				session = await _caller_session({})
				payload = normalize_local_mini_payload(payload, session)
				mission_id = payload.get("mission_id") or mission_id
			if (not model or model == "flash") and not has_cascade_models and not is_local_mini:
				return [
					types.TextContent(
						type="text",
						text=(
							f"[ERROR] job_submit sin modelo configurado (source={source}). "
							"'flash' es el placeholder del default del harness, no una config activa. "
							"Indica 'model' con un modelo real (p.ej. opencode-go/deepseek-v4-pro) o configura "
							"los recipes por rol en .red-pill/jobs/ (ver docs/TECHNICAL/DECISION_LOG.md). "
							"Bloqueado por seguridad."
						),
					)
				]

		qm = _queue()
		job_id = qm.enqueue_task(source=source, payload=payload, priority=int(arguments.get("priority", 5)), mission_id=mission_id)
		if source == "dag_job" and mission_owner and mission_scope:
			try:
				from red_pill.session.lease import LeaseStore

				LeaseStore().begin_mission_lease(
					mission_scope,
					continuity_id=mission_owner,
					holder_originator="",
					owner_kind="soul",
					idle_ttl_s=900,
					max_wall_s=604800,
					metadata={"job_id": job_id, "source": source},
					allow_takeover=operator,
				)
			except Exception as exc:
				# El job ya está en la cola: no dejarlo vivo sin mando ni dejar el
				# lease huérfano. Se descarta y se informa del conflicto real.
				qm.kill_task(job_id, discard=True)
				return [types.TextContent(type="text", text=f"[ERROR] no se pudo reclamar la misión {mission_scope}: {exc}")]
		note = f"mission={mission_id}" if mission_id else "sin mission_id"
		return [
			types.TextContent(
				type="text",
				text=f"[OK] Job encolado: {job_id} (source={source}, {note}, priority={arguments.get('priority', 5)}). Resultado a MinionInbox.",
			)
		]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[ERROR] job_submit falló: {e}")]


@registry.register_action(
	parent="job_manager_api",
	action="job_list",
	description="[OFFICIAL] Lista los jobs activos de la cola central. Filtra por misión para aislar forges.",
	schema={
		"type": "object",
		"properties": {
			"mission_id": {"type": "string", "description": "Solo jobs de esa misión (aislamiento entre forges)."},
			"continuity_id": {"type": "string", "description": "Solo jobs de esa alma (RFC-INTEROP-003 S3)."},
			"all": {"type": "boolean", "description": "Incluir COMPLETED (default: solo activos)."},
		},
	},
)
async def handle_job_list(arguments: Dict[str, Any]):
	try:
		import json

		# list_tasks(None) también excluye COMPLETED — para `all` hay que pasar
		# la lista completa explícita o el flag es un no-op.
		statuses = _ALL_JOB_STATUSES if arguments.get("all") else ["PENDING", "PROCESSING", "PAUSING", "PAUSED", "BLOCKED", "FRUSTRATED"]
		tasks = _queue().list_tasks(
			statuses=statuses,
			mission_id=arguments.get("mission_id"),
			continuity_id=arguments.get("continuity_id"),
		)
		if arguments.get("json") or arguments.get("format") == "json":
			# JOB-001: salida estructurada para parseo agéntico (agente/IDE/Telegram)
			return [
				types.TextContent(
					type="text",
					text=json.dumps(
						[
							{
								"id": t["id"],
								"source": t["source"],
								"status": t["status"],
								"priority": t["priority"],
								"mission_id": t.get("mission_id"),
								"continuity_id": t.get("continuity_id"),
								"parent_mission_id": t.get("parent_mission_id"),
								"parent_task_id": t.get("parent_task_id"),
								"title": t.get("title"),
								"progress": t.get("progress"),
								"attempts": t["attempts"],
								"updated_at": t.get("updated_at"),
								"dirty_kill": t.get("dirty_kill"),
							}
							for t in tasks
						],
						ensure_ascii=False,
						indent=1,
					),
				)
			]
		if not tasks:
			return [types.TextContent(type="text", text="Cola vacía (o sin jobs de esa misión).")]

		# Salida humana (JOB-001): progreso% + attempts + updated_at + parent,
		# columnas alineadas con truncado de title para no romper el terminal.
		lines = [f"{'ID':<9} {'SOURCE':<10} {'STATUS':<11} {'PRIO':>4} {'MISSION':<9} {'PARNT':<9} {'PROG':>6} {'ACT':>3} {'ACTUALIZADO':<17} TITLE"]
		for t in tasks:
			prog = t.get("progress") or {}
			prog_txt = f"{prog.get('percent', 0):.0f}%" if isinstance(prog, dict) and "percent" in prog else "-"
			parent = (t.get("parent_task_id") or "-")[:8]
			updated = (t.get("updated_at") or "-")[:16]
			title = (t.get("title") or "-")[:44]
			lines.append(
				f"{t['id'][:8]:<9} {t['source'][:9]:<10} {t['status'][:10]:<11} {t['priority']:>4} "
				f"{(t.get('mission_id') or '-')[:8]:<9} {parent:<9} {prog_txt:>6} {t['attempts']:>3} "
				f"{updated:<16} {title}"
			)
		return [types.TextContent(type="text", text="\n".join(lines))]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[ERROR] job_list falló: {e}")]


@registry.register_action(
	parent="job_manager_api",
	action="job_status",
	description="[OFFICIAL] Estado completo de un job: checkpoint, progreso, attempts, error_log.",
	schema={
		"type": "object",
		"properties": {
			"job_id": {"type": "string", "description": "Id completo o prefijo corto."},
		},
		"required": ["job_id"],
	},
)
async def handle_job_status(arguments: Dict[str, Any]):
	import json as _json

	try:
		task = _resolve_job(_queue(), arguments["job_id"])
		if not task:
			return [types.TextContent(type="text", text=f"[ERROR] Job '{arguments['job_id']}' no encontrado.")]
		lease = None
		parent_mission = str(task.get("parent_mission_id") or (task.get("checkpoint_data") or {}).get("parent_mission_id") or "")
		if parent_mission:
			try:
				from red_pill.session.lease import LeaseStore

				lease = LeaseStore().get(f"mission:{parent_mission}")
			except Exception:
				lease = None
		summary = {
			"id": task["id"][:8],
			"source": task["source"],
			"status": task["status"],
			"priority": task["priority"],
			"attempts": task["attempts"],
			"mission_id": task.get("mission_id"),
			"continuity_id": task.get("continuity_id"),
			"parent_mission_id": task.get("parent_mission_id"),
			"originator": (task.get("checkpoint_data") or {}).get("originator"),
			"role": (task.get("checkpoint_data") or {}).get("role"),
			"lease": lease or (task.get("checkpoint_data") or {}).get("lease"),
			"title": task.get("payload", {}).get("title"),
			"checkpoint": task.get("checkpoint_data"),
			"progress": task.get("progress"),
			"error_log": task.get("error_log"),
		}
		return [types.TextContent(type="text", text=_json.dumps(summary, ensure_ascii=False, indent=2, default=str))]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[ERROR] job_status falló: {e}")]


@registry.register_action(
	parent="job_manager_api",
	action="job_pause",
	description="[OFFICIAL] Pausa un job (frontera de paso). Para un dag_job, el main-loop puede tomar el control tras pausar.",
	schema={
		"type": "object",
		"properties": {
			"job_id": {"type": "string"},
		},
		"required": ["job_id"],
	},
)
async def handle_job_pause(arguments: Dict[str, Any]):
	try:
		qm = _queue()
		task = _resolve_job(qm, arguments["job_id"])
		if not task:
			return [types.TextContent(type="text", text=f"[ERROR] Job '{arguments['job_id']}' no encontrado.")]
		denied = await _authorize_job_mutation(task, "job_pause")
		if denied:
			return [types.TextContent(type="text", text=denied)]
		if qm.pause_task(task["id"]):
			return [types.TextContent(type="text", text=f"[OK] Pausa solicitada para {task['id'][:8]} (se sella en frontera de paso).")]
		return [types.TextContent(type="text", text=f"[WARN] Job {task['id'][:8]} en '{task['status']}': pausa no aplicable.")]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[ERROR] job_pause falló: {e}")]


@registry.register_action(
	parent="job_manager_api",
	action="job_resume",
	description="[OFFICIAL] Reanuda un job pausado/frustrado. Para dag_job, SOLTAR el control tras un handoff con el main-loop.",
	schema={
		"type": "object",
		"properties": {
			"job_id": {"type": "string"},
		},
		"required": ["job_id"],
	},
)
async def handle_job_resume(arguments: Dict[str, Any]):
	try:
		qm = _queue()
		task = _resolve_job(qm, arguments["job_id"])
		if not task:
			return [types.TextContent(type="text", text=f"[ERROR] Job '{arguments['job_id']}' no encontrado.")]
		denied = await _authorize_job_mutation(task, "job_resume")
		if denied:
			return [types.TextContent(type="text", text=denied)]
		lease_error = _mission_lease_conflict(task, allow_takeover=os.getenv("REDPILL_OPERATOR") == "1")
		if lease_error:
			return [types.TextContent(type="text", text=lease_error)]
		was_pausing = task["status"] == "PAUSING"
		if qm.resume_task(task["id"]):
			lease_error = _ensure_job_mission_lease(task, allow_takeover=os.getenv("REDPILL_OPERATOR") == "1")
			if lease_error:
				return [types.TextContent(type="text", text=lease_error)]
			if was_pausing:
				return [
					types.TextContent(
						type="text", text=f"[OK] Job {task['id'][:8]}: pausa cancelada en caliente (PROCESSING, el step en vuelo continúa)."
					)
				]
			return [types.TextContent(type="text", text=f"[OK] Job {task['id'][:8]} reanudado (PENDING). El runner lo retoma en el siguiente ciclo.")]
		return [types.TextContent(type="text", text=f"[WARN] Job {task['id'][:8]} en '{task['status']}': reanudación no aplicable.")]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[ERROR] job_resume falló: {e}")]


@registry.register_action(
	parent="job_manager_api",
	action="job_skip",
	description="[OFFICIAL] Saltar el siguiente elemento/step sin reintentarlo: escribe skip_next:true en el checkpoint (y devuelve PAUSED/FRUSTRATED a PENDING). El driver consume la marca y avanza el índice marcando 'skipped'.",
	schema={
		"type": "object",
		"properties": {
			"job_id": {"type": "string"},
		},
		"required": ["job_id"],
	},
)
async def handle_job_skip(arguments: Dict[str, Any]):
	try:
		qm = _queue()
		task = _resolve_job(qm, arguments["job_id"])
		if not task:
			return [types.TextContent(type="text", text=f"[ERROR] Job '{arguments['job_id']}' no encontrado.")]
		denied = await _authorize_job_mutation(task, "job_skip")
		if denied:
			return [types.TextContent(type="text", text=denied)]
		allow_takeover = os.getenv("REDPILL_OPERATOR") == "1"
		lease_error = _mission_lease_conflict(task, allow_takeover=allow_takeover)
		if lease_error:
			return [types.TextContent(type="text", text=lease_error)]
		if qm.skip_next_task(task["id"]):
			lease_error = _ensure_job_mission_lease(task, allow_takeover=allow_takeover)
			if lease_error:
				return [types.TextContent(type="text", text=lease_error)]
			updated = qm.get_task(task["id"])
			st = updated["status"] if updated else task["status"]
			if st == "PENDING":
				return [
					types.TextContent(
						type="text",
						text=f"[OK] Job {task['id'][:8]}: siguiente step marcado para saltar. El runner lo retoma (PENDING) y avanza sin reintentar.",
					)
				]
			return [
				types.TextContent(
					type="text",
					text=f"[OK] Job {task['id'][:8]} en '{st}': skip_next marcado. Se consumirá en la frontera del próximo step.",
				)
			]
		return [types.TextContent(type="text", text=f"[WARN] Job {task['id'][:8]} en '{task['status']}': skip no aplicable.")]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[ERROR] job_skip falló: {e}")]


@registry.register_action(
	parent="job_manager_api",
	action="job_kill",
	description="[OFFICIAL] Interrupción dura de un job: sella PAUSED* (o descarta) y abate el scope. La unidad en vuelo completa.",
	schema={
		"type": "object",
		"properties": {
			"job_id": {"type": "string"},
			"discard": {"type": "boolean", "description": "True = no reanudable (FRUSTRATED)."},
		},
		"required": ["job_id"],
	},
)
async def handle_job_kill(arguments: Dict[str, Any]):
	import subprocess as _sp

	try:
		qm = _queue()
		task = _resolve_job(qm, arguments["job_id"])
		if not task:
			return [types.TextContent(type="text", text=f"[ERROR] Job '{arguments['job_id']}' no encontrado.")]
		denied = await _authorize_job_mutation(task, "job_kill")
		if denied:
			return [types.TextContent(type="text", text=denied)]
		job_id = task["id"]
		killed, previous = qm.kill_task_ex(job_id, discard=bool(arguments.get("discard")))
		was_running = previous in ("PROCESSING", "PAUSING")
		if not killed:
			return [
				types.TextContent(
					type="text",
					text=f"[WARN] Job {job_id[:8]} en '{task['status']}': no se puede abatir (solo PENDING/PROCESSING/PAUSING/PAUSED).",
				)
			]
		# Abatir el scope systemd si existe (in-proceso = no-op, la unidad completa).
		unit = f"redpill-job-{job_id[:8]}.scope"
		try:
			_sp.run(["systemctl", "--user", "stop", unit], capture_output=True, timeout=10)
		except Exception:
			pass
		# Un job en vuelo conserva el lease hasta que el runner observe el kill y
		# llame a abort_step; liberarlo aquí permitiría a otra alma entrar mientras
		# el proceso aún se está apagando (split-brain real).
		if not was_running:
			_release_job_mission_lease(task)
			_finalize_killed_job(task)
		return [
			types.TextContent(type="text", text=f"[OK] Job {job_id[:8]} interrumpido ({'FRUSTRATED' if arguments.get('discard') else 'PAUSED*'}).")
		]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[ERROR] job_kill falló: {e}")]


@registry.register_action(
	parent="job_manager_api",
	action="job_checkpoint",
	description=(
		"[OFFICIAL] Handoff de control transferible: escribe el checkpoint de un dag_job "
		"PAUSED/PENDING desde fuera. El main-loop toma el control (job_pause), ejecuta N pasos "
		"inline, y escribe aquí el step_index avanzado; luego job_resume para SOLTAR el control "
		"y que el driver continúe. Solo aplica a jobs no-en-vuelo (PROCESSING/PAUSING se ignoran)."
	),
	schema={
		"type": "object",
		"properties": {
			"job_id": {"type": "string"},
			"checkpoint": {"type": "object", "description": "Nuevo checkpoint: {step_index: N, results: [...]}."},
			"progress": {"type": "object", "description": "Opcional, clave del renderer del CLI (current/total/percent/stage_*)."},
		},
		"required": ["job_id", "checkpoint"],
	},
)
async def handle_job_checkpoint(arguments: Dict[str, Any]):
	try:
		qm = _queue()
		task = _resolve_job(qm, arguments["job_id"])
		if not task:
			return [types.TextContent(type="text", text=f"[ERROR] Job '{arguments['job_id']}' no encontrado.")]
		denied = await _authorize_job_mutation(task, "job_checkpoint")
		if denied:
			return [types.TextContent(type="text", text=denied)]
		checkpoint, cp_error = _sanitize_job_checkpoint(task, arguments["checkpoint"])
		if cp_error:
			return [types.TextContent(type="text", text=cp_error)]
		lease_error = _mission_lease_conflict(task, allow_takeover=os.getenv("REDPILL_OPERATOR") == "1")
		if lease_error:
			return [types.TextContent(type="text", text=lease_error)]
		ok = qm.update_checkpoint(task["id"], checkpoint, arguments.get("progress"))
		if ok:
			lease_error = _ensure_job_mission_lease(task, allow_takeover=os.getenv("REDPILL_OPERATOR") == "1")
			if lease_error:
				return [types.TextContent(type="text", text=lease_error)]
			return [types.TextContent(type="text", text=f"[OK] Checkpoint de {task['id'][:8]} actualizado. Soltar el control con job_resume.")]
		return [
			types.TextContent(
				type="text", text=f"[WARN] Job {task['id'][:8]} en '{task['status']}': checkpoint no aplicable (debe estar PAUSED/PENDING)."
			)
		]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[ERROR] job_checkpoint falló: {e}")]


@registry.register_action(
	parent="job_manager_api",
	action="job_transfer",
	description=(
		"[OFFICIAL] Helper del control transferible: pausa un dag_job y devuelve su checkpoint "
		"para que el main-loop tome el control. Equivale a job_pause + job_status en un solo paso. "
		"Para SOLTAR: job_resume."
	),
	schema={
		"type": "object",
		"properties": {
			"job_id": {"type": "string"},
		},
		"required": ["job_id"],
	},
)
async def handle_job_transfer(arguments: Dict[str, Any]):
	import json as _json

	try:
		qm = _queue()
		task = _resolve_job(qm, arguments["job_id"])
		if not task:
			return [types.TextContent(type="text", text=f"[ERROR] Job '{arguments['job_id']}' no encontrado.")]
		denied = await _authorize_job_mutation(task, "job_transfer")
		if denied:
			return [types.TextContent(type="text", text=denied)]
		lease_error = _mission_lease_conflict(task, allow_takeover=os.getenv("REDPILL_OPERATOR") == "1")
		if lease_error:
			return [types.TextContent(type="text", text=lease_error)]
		paused = qm.pause_task(task["id"])
		if paused:
			lease_error = _ensure_job_mission_lease(task, allow_takeover=os.getenv("REDPILL_OPERATOR") == "1")
			if lease_error:
				return [types.TextContent(type="text", text=lease_error)]
		after = qm.get_task(task["id"])
		return [
			types.TextContent(
				type="text",
				text=_json.dumps(
					{
						"job_id": task["id"][:8],
						**_job_identity(task),
						"paused": paused,
						"status": after["status"] if after else task["status"],
						"checkpoint": after.get("checkpoint_data") if after else task.get("checkpoint_data"),
						"progress": after.get("progress") if after else task.get("progress"),
						"note": "main-loop al control: ejecuta los pasos inline y escribe job_checkpoint; luego job_resume para soltar.",
					},
					ensure_ascii=False,
					indent=2,
					default=str,
				),
			)
		]
	except Exception as e:
		return [types.TextContent(type="text", text=f"[ERROR] job_transfer falló: {e}")]


async def main():
	# Global safety net: catch unhandled exceptions in fire-and-forget tasks
	def _handle_task_exception(loop, context):
		exception = context.get("exception")
		msg = context.get("message", "Unhandled asyncio exception")
		logger.error(f"[ASYNCIO SAFETY NET] {msg}: {exception}", exc_info=exception)

	loop = asyncio.get_event_loop()
	loop.set_exception_handler(_handle_task_exception)

	# Run the server using stdin/stdout streams
	async with stdio_server() as (read_stream, write_stream):
		# ISO-LATCH: Redirect standard output and logging to standard error.
		# This prevents Swarm deployments or any rogue print() from polluting
		# the stdout pipe and corrupting the JSON-RPC communication (EOF).
		import logging
		import sys

		_original_stdout = sys.stdout
		sys.stdout = sys.stderr

		# Force root logger to also write to sys.stderr
		logging.basicConfig(level=logging.INFO, stream=sys.stderr, force=True)

		try:
			logger.info(f"RedPill-Kernel v{CORE_VERSION} MCP server starting...")
			await server.run(
				read_stream,
				write_stream,
				InitializationOptions(
					server_name="RedPill-Kernel",
					server_version=CORE_VERSION,
					capabilities=server.get_capabilities(
						notification_options=NotificationOptions(),
						experimental_capabilities={},
					),
				),
			)
		except Exception as e:
			logger.critical(f"MCP server.run() crashed: {e}", exc_info=True)
		finally:
			sys.stdout = _original_stdout


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		pass
	finally:
		# Force a hard exit. This prevents background thread pools
		# (e.g. from Qdrant clients or Minion detached tasks) from keeping
		# the Python interpreter alive and blocking the IDE's MCP refresh.
		import os

		os._exit(0)
