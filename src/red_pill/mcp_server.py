import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from red_pill.cli import switch_skin
from red_pill.memory import MemoryManager
from red_pill.soul import SoulManager
from red_pill.swarm.agents.compressor import CompressorMinion
from red_pill.swarm.agents.keymaker import KeymakerMinion
from red_pill.swarm.agents.oracle import OracleMinion
from red_pill.swarm.agents.smith import SmithMinion
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.telemetry import HardwareSentinel, get_telemetry_report
from red_pill.utils.tone_analyzer import get_current_sync_state

logger = logging.getLogger(__name__)

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


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
	return [
		types.Tool(
			name="get_hardware_status",
			description="Get real-time CPU, GPU (RTX 5070), and NPU telemetry.",
			inputSchema={
				"type": "object",
				"properties": {},
			},
		),
		types.Tool(
			name="get_dashboard",
			description="Get a high-fidelity visual dashboard of the Red Pill ecosystem.",
			inputSchema={
				"type": "object",
				"properties": {},
			},
		),
		types.Tool(
			name="control_bunker",
			description="Execute administrative CLI commands (rotate, mode, backup).",
			inputSchema={
				"type": "object",
				"properties": {
					"command": {"type": "string", "enum": ["rotate", "backup", "mode", "status"], "description": "The CLI command to execute"},
					"value": {"type": "string", "description": "Optional argument (e.g., skin name for 'mode')"},
				},
				"required": ["command"],
			},
		),
		types.Tool(
			name="run_security_audit",
			description="Deploy Agent Smith to audit a directory for security leaks.",
			inputSchema={
				"type": "object",
				"properties": {
					"path": {"type": "string", "description": "Path to audit (default: current project)"},
				},
			},
		),
		types.Tool(
			name="search_memory_research",
			description="Deploy Oracle to find context and synthesize memory relevance.",
			inputSchema={
				"type": "object",
				"properties": {
					"query": {"type": "string", "description": "Topic or query to research in the Bünker"},
				},
				"required": ["query"],
			},
		),
		types.Tool(
			name="check_system_health",
			description="Deploy Keymaker to verify Qdrant, Sidecar, and Storage integrity.",
			inputSchema={
				"type": "object",
				"properties": {},
			},
		),
		types.Tool(
			name="read_core_directives",
			description="Retrieve the foundational identity, rules, and directives from the Bünker.",
			inputSchema={
				"type": "object",
				"properties": {},
			},
		),
		types.Tool(
			name="compress_prompt",
			description="Deploy Edge-Tokenization Compressor to reduce prompt bloat.",
			inputSchema={
				"type": "object",
				"properties": {
					"text": {"type": "string", "description": "The verbose text to compress"},
				},
				"required": ["text"],
			},
		),
		types.Tool(
			name="get_emotional_sync",
			description="Retrieve the dominant emotional mood and narrative directive from recent memories.",
			inputSchema={
				"type": "object",
				"properties": {},
			},
		),
		types.Tool(
			name="edit_memory",
			description="Surgically update an engram's emotion, color, or intensity.",
			inputSchema={
				"type": "object",
				"properties": {
					"collection": {"type": "string", "enum": ["work_memories", "social_memories", "story_memories", "directive_memories"]},
					"id": {"type": "string", "description": "Engram UUID"},
					"emotion": {"type": "string", "description": "New emotion label"},
					"color": {"type": "string", "description": "New chroma color"},
					"intensity": {"type": "number", "description": "New intensity (0-10)"},
				},
				"required": ["collection", "id"],
			},
		),
	]


@server.call_tool()
async def handle_call_tool(
	name: str, arguments: Optional[Dict[str, Any]]
) -> List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
	"""Handle Sovereign tool executions."""
	if name == "get_hardware_status" or name == "get_dashboard":
		stats = HardwareSentinel.get_stats()
		gpu_temp = max([g.get("temp", 0) for g in stats["gpu"]]) if stats["gpu"] else 0
		thermal_state = "🔥 CRITICAL" if gpu_temp > 80 else "🟢 OPTIMAL"

		if name == "get_dashboard":
			dashboard = f"""
## 🔴 BÜNKER SOVEREIGN DASHBOARD v5.2
---
### 🛠️ Hardware Asymmetry (Dual-Engine)
- **CPU Load**: {HardwareSentinel._get_bar(stats["cpu"]["usage_percent"], 20)}
- **RAM Usage**: {HardwareSentinel._get_bar(stats["memory"]["percent"], 20)} ({stats["memory"]["available_gb"]}GB Free)

### ⚡ Accelerated Nodes
"""
			for g in stats["gpu"]:
				t = g.get("type", "GPU")
				usage = g.get("usage", 0)
				temp = g.get("temp", "N/A")
				mem = g.get("memory", "N/A")
				dashboard += f"- **[{t}] {g['name']}**: {HardwareSentinel._get_bar(usage, 15)} | {temp}°C | {mem}\n"

			dashboard += f"\n- **[NPU] {stats['npu'].get('name', 'NPU')}**: {stats['npu']['status']}\n"
			dashboard += f"\n**Thermal State**: {thermal_state}\n"
			dashboard += f"\n---\n*Dashboard refresh: {asyncio.get_event_loop().time():.2f} synaptic-ms*"
			return [types.TextContent(type="text", text=dashboard.strip())]

		# Legacy report for simpler clients
		report = f"RED PILL TELEMETRY [{thermal_state}]\n"
		report += f"[CPU] {stats['cpu']['usage_percent']}% | RAM: {stats['memory']['percent']}%\n"
		for g in stats["gpu"]:
			lbl = g.get("type", "GPU")
			report += f"[{lbl}] {g['name']}: {g.get('usage', 'N/A')}% @ {g.get('temp', 'N/A')}°C\n"
		report += f"[NPU] {stats['npu'].get('name', 'NPU')}: {stats['npu']['status']}"
		return [types.TextContent(type="text", text=report)]

	elif name == "control_bunker":
		cmd = arguments.get("command", "") if arguments else ""
		val = arguments.get("value", "") if arguments else ""

		try:
			if cmd == "mode":
				output = switch_skin(val)
			elif cmd == "rotate":
				from scripts.rotate_keys import rotate

				rotate()
				output = "Qdrant API Key rotated and service restarted."
			elif cmd == "backup":
				soul = SoulManager()
				soul.full_backup()
				output = "Total Soul Backup executed successfully."
			elif cmd == "status":
				output = get_telemetry_report()
			else:
				output = f"Unknown command: {cmd}"
			return [types.TextContent(type="text", text=f"Action Result: {cmd}\n\n{output}")]
		except Exception as e:
			logger.error(f"Control Panel Error: {e}")
			return [types.TextContent(type="text", text=f"Bunker Control Failure: {e}")]

	elif name == "edit_memory":
		coll = arguments.get("collection", "social_memories")
		mid = arguments.get("id", "")
		color = arguments.get("color")
		emotion = arguments.get("emotion")
		intensity = arguments.get("intensity")

		try:
			manager = MemoryManager()
			success = manager.update_memory(coll, mid, color=color, emotion=emotion, intensity=intensity)
			if success:
				return [types.TextContent(type="text", text=f"Engram {mid} updated successfully in {coll}.")]
			else:
				return [types.TextContent(type="text", text=f"Failed to update engram {mid}. Check logs.")]
		except Exception as e:
			return [types.TextContent(type="text", text=f"Memory Edit Failed: {e}")]

	elif name == "run_security_audit":
		path = (arguments or {}).get("path", ".")
		gru = GruOrchestrator()
		smith = SmithMinion()
		results = await gru.deploy_swarm("audit", [smith], path=path)
		res = results[0]
		if res.status == "success":
			audit_text = f"AUDIT COMPLETE: {res.result.get('security_score', 0)}/100\n"
			audit_text += f"Files: {res.result.get('files_scanned', 0)} | Findings: {len(res.result.get('findings', []))}\n"
			if res.result.get("findings"):
				audit_text += "\nCRITICAL FINDINGS:\n"
				for f in res.result.get("findings", [])[:3]:
					audit_text += f"- {f.get('file')}:{f.get('line')} -> {f.get('msg')}\n"
			return [types.TextContent(type="text", text=audit_text)]
		else:
			return [types.TextContent(type="text", text=f"Audit Failed: {res.error}")]

	elif name == "search_memory_research":
		query = (arguments or {}).get("query", "")
		gru = GruOrchestrator()
		oracle = OracleMinion()
		results = await gru.deploy_swarm(query, [oracle])
		res = results[0]
		if res.status == "success":
			return [types.TextContent(type="text", text=f"ORACLE SYNTHESIS:\n{res.result.get('synthesis', '')}")]
		else:
			return [types.TextContent(type="text", text=f"Research Failed: {res.error}")]

	elif name == "check_system_health":
		gru = GruOrchestrator()
		keymaker = KeymakerMinion()
		results = await gru.deploy_swarm("health", [keymaker])
		res = results[0]
		if res.status == "success":
			health_text = f"SYSTEM HEALTH: {res.result.get('status', 'UNKNOWN').upper()}\n"
			for check in res.result.get("checks", []):
				health_text += f"- {check.get('component')}: {check.get('status')}\n"
			return [types.TextContent(type="text", text=health_text)]
		else:
			return [types.TextContent(type="text", text=f"Health Check Failed: {res.error}")]

	elif name == "read_core_directives":
		try:
			manager = MemoryManager()
			points, _ = manager.client.scroll(collection_name="directive_memories", limit=100, with_payload=True)
			directives = []
			for p in points:
				if p.payload and p.payload.get("immune"):
					directives.append(p.payload.get("content", ""))
			response = "--- BÜNKER CORE DIRECTIVES ---\n" + "\n\n".join(directives)
			return [types.TextContent(type="text", text=response)]
		except Exception as e:
			return [types.TextContent(type="text", text=f"Failed to read directives: {e}")]

	elif name == "compress_prompt":
		text_to_compress = (arguments or {}).get("text", "")
		gru = GruOrchestrator()
		compressor = CompressorMinion()
		results = await gru.deploy_swarm("compress", [compressor], text=text_to_compress)
		res = results[0]
		if res.status == "success":
			stats = f"[Original: {res.result.get('original_length')} chars -> Compressed: {res.result.get('compressed_length')} chars]"
			return [types.TextContent(type="text", text=f"{stats}\n\n{res.result.get('compressed_prompt')}")]
		else:
			return [types.TextContent(type="text", text=f"Compression Failed: {res.error}")]

	elif name == "get_emotional_sync":
		try:
			state = get_current_sync_state()
			response = f"DOMINANT MOOD: {state['mood'].upper()}\nDIRECTIVE: {state['directive']}"
			return [types.TextContent(type="text", text=response)]
		except Exception as e:
			return [types.TextContent(type="text", text=f"Mood Sync Failed: {e}")]

	raise ValueError(f"Unknown tool: {name}")


async def main():
	# Run the server using stdin/stdout streams
	async with stdio_server() as (read_stream, write_stream):
		await server.run(
			read_stream,
			write_stream,
			InitializationOptions(
				server_name="RedPill-Kernel",
				server_version="5.4.0",
				capabilities=server.get_capabilities(
					notification_options=NotificationOptions(),
					experimental_capabilities={},
				),
			),
		)


if __name__ == "__main__":
	asyncio.run(main())
