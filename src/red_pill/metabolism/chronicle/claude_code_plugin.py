"""
Chronicle Extractor Plugin for Claude Code (JSONL).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from red_pill.core.paths import get_data_dir, get_staging_dir
from red_pill.metabolism.chronicle.base import ChronicleExtractorPlugin

logger = logging.getLogger(__name__)


def load_offsets() -> Dict[str, int]:
	path = get_data_dir() / "chronicle_processed.json"
	if path.exists():
		try:
			with open(path, "r", encoding="utf-8") as f:
				data = json.load(f)
				if isinstance(data, dict):
					return {k: int(v) for k, v in data.items()}
		except Exception as e:
			logger.warning(f"[Claude Code Plugin] Failed to load offsets: {e}")
	return {}


def save_offsets(offsets: Dict[str, int]) -> None:
	path = get_data_dir() / "chronicle_processed.json"
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		with open(path, "w", encoding="utf-8") as f:
			json.dump(offsets, f, indent=4)
	except Exception as e:
		logger.error(f"[Claude Code Plugin] Failed to save offsets: {e}")


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


class ClaudeCodeExtractorPlugin(ChronicleExtractorPlugin):
	"""Chronicle plugin to ingest conversation transcripts from Claude Code JSONL files."""

	def extract(self) -> int:
		logger.info("[Claude Code Plugin] Scanning for session transcripts...")
		base_dir = Path.home() / ".claude" / "projects"
		if not base_dir.exists() or not base_dir.is_dir():
			logger.info("[Claude Code Plugin] Claude Code projects directory not found.")
			return 0

		offsets = load_offsets()
		staged_count = 0
		staging_dir = get_staging_dir()
		staging_dir.mkdir(parents=True, exist_ok=True)

		# Iterate over all project subdirectories
		for proj_dir in base_dir.iterdir():
			if not proj_dir.is_dir():
				continue

			# Ingest each session JSONL file
			for session_file in proj_dir.glob("*.jsonl"):
				filepath = str(session_file.resolve())
				if not os.path.exists(filepath):
					continue

				file_size = os.path.getsize(filepath)
				last_offset = offsets.get(filepath, 0)
				if file_size < last_offset:
					logger.info(f"[Claude Code Plugin] File truncated: {filepath}. Resetting offset.")
					last_offset = 0

				# State machine for this file's chunk
				current_turn_steps: List[Dict[str, Any]] = []
				current_model: str | None = None
				assistant_uuid: str | None = None

				committed_offset = last_offset
				line_start_offset = last_offset
				try:
					with open(filepath, "rb") as f:
						f.seek(last_offset)
						for binary_line in f:
							# Concurrency safety: stop if the line isn't fully written
							if not binary_line.endswith(b"\n"):
								break

							try:
								line_str = binary_line.decode("utf-8")
								record = json.loads(line_str)
							except (UnicodeDecodeError, json.JSONDecodeError):
								# Stop at partial or malformed record (concurrency)
								break

							# Main chain only
							if record.get("isSidechain") is True:
								line_start_offset += len(binary_line)
								if not current_turn_steps:
									committed_offset = line_start_offset
								continue

							r_type = record.get("type")
							if r_type == "user":
								msg = record.get("message", {})
								user_text = extract_user_content(msg)
								if user_text.strip():
									# If we have tool result or ordinary prompt
									current_turn_steps.append({"intent": "USER", "message": {"text": user_text}})

							elif r_type == "assistant":
								msg = record.get("message", {})
								current_model = msg.get("model") or current_model
								assistant_uuid = record.get("uuid") or assistant_uuid

								assistant_blocks = extract_assistant_blocks(msg)
								current_turn_steps.extend(assistant_blocks)

								# End of turn check
								if msg.get("stop_reason") == "end_turn":
									if current_turn_steps and assistant_uuid:
										# We have a complete turn
										stage_id = f"claude_code_{assistant_uuid}"
										stage_file = staging_dir / f"{stage_id}.json"

										payload = {
											"id": stage_id,
											"model": current_model or "unknown",
											"workspace": proj_dir.name,
											"steps": list(current_turn_steps),
										}

										with open(stage_file, "w", encoding="utf-8") as sf:
											json.dump(payload, sf, indent=4)
										staged_count += 1

									# Clear state for next turn
									current_turn_steps = []
									assistant_uuid = None

							line_start_offset += len(binary_line)
							if not current_turn_steps:
								committed_offset = line_start_offset
				except Exception as e:
					logger.error(f"[Claude Code Plugin] Error parsing {filepath}: {e}")
					continue

				# Update offsets
				offsets[filepath] = committed_offset

		save_offsets(offsets)
		logger.info(f"[Claude Code Plugin] Snatching complete. Staged {staged_count} new turns.")
		return staged_count
