import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramResponseExtractor:
	"""
	Extracts the latest agent response directly from the IDE's log file (transcript.jsonl or overview.txt).
	This bypasses gRPC trajectory truncation issues.
	"""

	def __init__(self, brain_dir: Optional[Path] = None):
		self.brain_dirs = [
			Path.home() / ".gemini" / "antigravity-cli" / "brain",
			Path.home() / ".gemini" / "antigravity" / "brain",
		]
		if brain_dir:
			self.brain_dirs.insert(0, brain_dir)

	def get_latest_response(self, cascade_id: str) -> Optional[str]:
		log_path = None
		for bdir in self.brain_dirs:
			for name in ["transcript.jsonl", "overview.txt"]:
				path = bdir / cascade_id / ".system_generated" / "logs" / name
				if path.exists():
					log_path = path
					break
			if log_path:
				break

		if not log_path:
			logger.warning(f"No log file found for cascade {cascade_id}.")
			return None

		try:
			with open(log_path, "r", encoding="utf-8") as f:
				lines = f.readlines()

			for line in reversed(lines):
				if not line.strip():
					continue
				try:
					data = json.loads(line)
					# If we hit a USER_INPUT before finding a PLANNER_RESPONSE with content,
					# it means the model is currently running and hasn't generated the final response yet.
					if data.get("type") == "USER_INPUT" or data.get("source") == "USER_EXPLICIT":
						logger.info(f"Encountered USER_INPUT step in {log_path.name} before PLANNER_RESPONSE. Response not ready.")
						return None

					if data.get("type") in ("PLANNER_RESPONSE", "CORTEX_STEP_TYPE_PLANNER_RESPONSE", "15") or data.get("source") == "MODEL":
						content = data.get("content")
						if isinstance(content, str) and content.strip():
							return content
				except json.JSONDecodeError:
					continue

		except Exception as e:
			logger.error(f"Failed to extract response from {log_path}: {e}")

		return None
