import asyncio

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from red_pill.swarm.agents.compressor import CompressorMinion
from red_pill.swarm.agents.keymaker import KeymakerMinion
from red_pill.swarm.agents.oracle import OracleMinion
from red_pill.swarm.agents.smith import SmithMinion
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.telemetry import HardwareSentinel

# Initialize the Sovereign MCP Server
server = Server("RedPill-Kernel")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
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
	]

@server.call_tool()
async def handle_call_tool(
	name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
	"""Handle Sovereign tool executions."""
	if name == "get_hardware_status":
		stats = HardwareSentinel.get_stats()
		# Critical Thermal Guard check
		gpu_temp = max([g.get("temp", 0) for g in stats["gpu"]]) if stats["gpu"] else 0
		thermal_msg = " [🔥 OVERHEAT RISK]" if gpu_temp > 80 else " [🟢 OPTIMAL]"

		report = f"RED PILL TELEMETRY{thermal_msg}\n"
		report += f"[CPU] {stats['cpu']['usage_percent']}% | RAM: {stats['memory']['percent']}%\n"
		for g in stats["gpu"]:
			lbl = g.get("type", "GPU")
			report += f"[{lbl}] {g['name']}: {g.get('usage', 'N/A')}% @ {g.get('temp', 'N/A')}°C\n"
		report += f"[NPU] {stats['npu'].get('name', 'NPU')}: {stats['npu']['status']}"

		return [types.TextContent(type="text", text=report)]

	elif name == "run_security_audit":
		path = (arguments or {}).get("path", ".")
		gru = GruOrchestrator()
		smith = SmithMinion()
		results = await gru.deploy_swarm("audit", [smith], path=path)
		res = results[0]
		if res.status == "success":
			audit_text = f"AUDIT COMPLETE: {res.result['security_score']}/100\n"
			audit_text += f"Files: {res.result['files_scanned']} | Findings: {len(res.result['findings'])}\n"
			if res.result['findings']:
				audit_text += "\nCRITICAL FINDINGS:\n"
				for f in res.result['findings'][:3]:
					audit_text += f"- {f['file']}:{f['line']} -> {f['msg']}\n"
			return [types.TextContent(type="text", text=audit_text)]
		else:
			return [types.TextContent(type="text", text=f"Audit Failed: {res.error}")]

	elif name == "search_memory_research":
		query = (arguments or {}).get("query")
		gru = GruOrchestrator()
		oracle = OracleMinion()
		results = await gru.deploy_swarm("research", [oracle], task=query)
		res = results[0]
		if res.status == "success":
			return [types.TextContent(type="text", text=f"ORACLE SYNTHESIS:\n{res.result['synthesis']}")]
		else:
			return [types.TextContent(type="text", text=f"Research Failed: {res.error}")]

	elif name == "check_system_health":
		gru = GruOrchestrator()
		keymaker = KeymakerMinion()
		results = await gru.deploy_swarm("health", [keymaker])
		res = results[0]
		if res.status == "success":
			health_text = f"SYSTEM HEALTH: {res.result['status'].upper()}\n"
			for check in res.result['checks']:
				health_text += f"- {check['component']}: {check['status']}\n"
			return [types.TextContent(type="text", text=health_text)]
		else:
			return [types.TextContent(type="text", text=f"Health Check Failed: {res.error}")]

	elif name == "read_core_directives":
		from red_pill.memory import MemoryManager
		try:
			manager = MemoryManager()
			points, _ = manager.client.scroll(
				collection_name="directive_memories",
				limit=100,
				with_payload=True
			)
			directives = []
			for p in points:
				if p.payload.get("immune"):
					directives.append(p.payload.get("content", ""))
			response = "--- BÜNKER CORE DIRECTIVES ---\n" + "\n\n".join(directives)
			return [types.TextContent(type="text", text=response)]
		except Exception as e:
			return [types.TextContent(type="text", text=f"Failed to read directives: {e}")]

	elif name == "compress_prompt":
		text_to_compress = (arguments or {}).get("text")
		gru = GruOrchestrator()
		compressor = CompressorMinion()
		results = await gru.deploy_swarm("compress", [compressor], text=text_to_compress)
		res = results[0]
		if res.status == "success":
			stats = f"[Original: {res.result['original_length']} chars -> Compressed: {res.result['compressed_length']} chars]"
			return [types.TextContent(type="text", text=f"{stats}\n\n{res.result['compressed_prompt']}")]
		else:
			return [types.TextContent(type="text", text=f"Compression Failed: {res.error}")]

	raise ValueError(f"Unknown tool: {name}")

async def main():
	# Run the server using stdin/stdout streams
	async with stdio_server() as (read_stream, write_stream):
		await server.run(
			read_stream,
			write_stream,
			InitializationOptions(
				server_name="RedPill-Kernel",
				server_version="5.0.0",
				capabilities=server.get_capabilities(
					notification_options=NotificationOptions(),
					experimental_capabilities={},
				),
			),
		)

if __name__ == "__main__":
	asyncio.run(main())
