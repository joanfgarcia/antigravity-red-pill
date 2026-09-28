"""Render de bloques de mensaje de agentes (Claude Code / OpenCode) — módulo NEUTRO.

Estos helpers vivían en `metabolism/chronicle/claude_code_plugin.py` (la vía
legacy que escribe a `staging/`), pero **también** los consumen las fuentes de
Memento (`chronicle_sources/opencode.py`, `chronicle_sources/claude_code.py`).
Al ser código compartido, no pueden borrarse con la vía legacy (SHARD-01,
2026-09-28): viven aquí, fuera del paquete legacy, para que la demolición de
`metabolism/chronicle/*` no rompa la memoria curada.

Contenido: marcadores compactos de tool-use/tool-result (filtro de ruido del
Chronicle) y extracción de texto/bloques de user/assistant.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List


def _render_tool_use(name: str, inp: Dict[str, Any]) -> str:
	"""Compact tool-use marker for the Chronicle (noise pre-filter).

	Full input JSON (file contents, diffs, scripts) used to enter the Bünker
	verbatim as immune raw_parents — thousands of machine-noise engrams per
	agentic session (the retrospective's 87%-raw-material problem). The narrative
	only needs WHAT tool acted on WHAT target; the code itself lives in git.
	"""
	import red_pill.config as cfg

	if not getattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", True):
		return f"[TOOL USE: {name}({json.dumps(inp)})]"
	hint = ""
	if isinstance(inp, dict):
		for key in ("file_path", "path", "command", "query", "pattern", "url", "description", "subject"):
			value = inp.get(key)
			if isinstance(value, str) and value.strip():
				hint = f" {key}={value.strip()[:80]}"
				break
	return f"[TOOL: {name}{hint}]"


def _render_tool_result(tool_use_id: str, output: str) -> str:
	"""Compact tool-result marker: keep the head (where failures/verdicts live),
	drop the bulk."""
	import red_pill.config as cfg

	if not getattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", True):
		return f"[TOOL RESULT: id={tool_use_id} output={output}]"
	head = " ".join(str(output).split())[:160]
	omitted = len(output) - len(head)
	suffix = f" (+{omitted} chars omitted)" if omitted > 0 else ""
	return f"[TOOL RESULT: {head}{suffix}]"


def extract_user_content(message: Dict[str, Any]) -> str:
	content = message.get("content", "")
	if isinstance(content, str):
		return content
	elif isinstance(content, list):
		parts = []
		for block in content:
			if not isinstance(block, dict):
				continue
			b_type = block.get("type")
			if b_type == "text":
				parts.append(block.get("text", ""))
			elif b_type == "tool_result":
				tool_use_id = block.get("tool_use_id", "")
				sub_content = block.get("content", "")
				if isinstance(sub_content, str):
					parts.append(_render_tool_result(tool_use_id, sub_content))
				elif isinstance(sub_content, list):
					sub_parts = []
					for sub_block in sub_content:
						if not isinstance(sub_block, dict):
							continue
						if sub_block.get("type") == "text":
							sub_parts.append(sub_block.get("text", ""))
						elif sub_block.get("type") == "tool_reference":
							sub_parts.append(f"tool_ref:{sub_block.get('tool_name')}")
					parts.append(_render_tool_result(tool_use_id, ", ".join(sub_parts)))
		return "\n".join(parts)
	return ""


def extract_assistant_blocks(message: Dict[str, Any]) -> List[Dict[str, Any]]:
	blocks = []
	content = message.get("content", [])
	if isinstance(content, list):
		for block in content:
			if not isinstance(block, dict):
				continue
			b_type = block.get("type")
			if b_type == "text":
				blocks.append({"intent": "ASSISTANT", "message": {"text": block.get("text", "")}})
			elif b_type == "tool_use":
				name = block.get("name", "")
				inp = block.get("input", {})
				blocks.append({"intent": "ASSISTANT", "message": {"text": _render_tool_use(name, inp)}})
	elif isinstance(content, str):
		blocks.append({"intent": "ASSISTANT", "message": {"text": content}})
	return blocks
