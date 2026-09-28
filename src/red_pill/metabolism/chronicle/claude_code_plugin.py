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

# SHARD-01 (2026-09-28): helpers COMPARTIDOS con las fuentes de Memento
# (chronicle_sources/*) movidos a un módulo neutral; se re-exportan aquí
# para no romper imports existentes. NO borrar hasta demoler la vía legacy.
from red_pill.utils.chronicle_render import (
	_render_tool_result,
	_render_tool_use,
	extract_assistant_blocks,
	extract_user_content,
)

# Re-export para compatibilidad (quien importaba los helpers desde este módulo).
__all__ = [
	"ClaudeCodeExtractorPlugin",
	"extract_assistant_blocks",
	"extract_user_content",
	"_render_tool_use",
	"_render_tool_result",
]

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


class ClaudeCodeExtractorPlugin(ChronicleExtractorPlugin):
	"""Chronicle plugin to ingest conversation transcripts from Claude Code JSONL files."""

	def extract(self) -> int:
		# Single-writer: con la ingesta retirada, el staging ya no se consume.
		import red_pill.config as _cfg

		if getattr(_cfg, "SW_INGEST_RETIRED", False):
			logger.info("[Claude Code Plugin] Ingesta retirada (SW_INGEST_RETIRED); no se extrae.")
			return 0
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
