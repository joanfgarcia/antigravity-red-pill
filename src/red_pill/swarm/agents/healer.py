import logging
import os
import re
import subprocess
from typing import Any, Dict, List

from red_pill.swarm.agents.edge_engine import EdgeEngine
from red_pill.swarm.base import Minion

logger = logging.getLogger(__name__)


class HealerMinion(Minion):
	"""
	Specialized Minion for automated code repair.
	Integrates with Mypy and EdgeEngine for autonomous healing.
	"""

	name: str = "Healer"
	specialization: str = "Automated Code Repair"

	async def execute(self, task: str, **kwargs) -> Dict[str, Any]:
		"""
		Executes a healing cycle.
		Target: defaults to 'src/red_pill/' unless 'path' is provided.
		"""
		engine = EdgeEngine()
		dry_run = kwargs.get("dry_run", False)
		path = kwargs.get("path", "src/red_pill/")
		self.log(f"--- [Healer] Initializing Healing Cycle for: {path} ---")

		if not engine.model_path:
			return {"status": "error", "error": "No GGUF model found for healing cognition."}

		# 1. Run Mypy to find targets
		raw_errors = self._run_mypy(path)
		if not raw_errors:
			return {"status": "success", "message": "No errors found. System tissue is healthy.", "fixes": 0}

		grouped_errors = self._parse_errors(raw_errors)
		total_fixes = 0

		# 2. Heal each file
		for file_path, errors in grouped_errors.items():
			fixes = self._heal_file(file_path, errors, engine, dry_run)
			total_fixes += fixes

		return {
			"status": "success",
			"message": f"Healing cycle complete. {total_fixes} lines repaired.",
			"fixes": total_fixes,
			"errors_addressed": len(raw_errors),
		}

	def _run_mypy(self, path: str) -> List[str]:
		"""Captures raw mypy output."""
		try:
			result = subprocess.run(["uv", "run", "mypy", path, "--no-error-summary"], capture_output=True, text=True)
			return result.stdout.splitlines()
		except Exception as e:
			logger.error(f"Healer failed to run mypy: {e}")
			return []

	def _parse_errors(self, lines: List[str]) -> Dict[str, List[Dict]]:
		"""Groups errors by file."""
		parsed = {}
		for line in lines:
			match = re.match(r"([^:]+):(\d+): error: (.+)", line)
			if match:
				file_path = match.group(1)
				line_num = int(match.group(2))
				error_msg = match.group(3)

				if file_path not in parsed:
					parsed[file_path] = []
				parsed[file_path].append({"line": line_num, "msg": error_msg})
		return parsed

	def _heal_file(self, file_path: str, errors: List[Dict], engine: EdgeEngine, dry_run: bool) -> int:
		"""Applies fixes to a single file using EdgeEngine."""
		if not os.path.exists(file_path):
			return 0

		self.log(f"Processing {file_path} ({len(errors)} issues)...")

		with open(file_path, "r") as f:
			lines = f.read().splitlines()

		# Fix from bottom to top to preserve line numbers
		errors.sort(key=lambda x: x["line"], reverse=True)
		fixes_applied = 0

		for err in errors:
			line_idx = err["line"] - 1
			if line_idx >= len(lines):
				continue

			original_line = lines[line_idx]
			# Context window
			start_win = max(0, line_idx - 5)
			end_win = min(len(lines), line_idx + 5)
			context = "\n".join([f"{j + 1}: {line}" for j, line in enumerate(lines[start_win:end_win], start=start_win)])

			prompt = (
				f"You are an expert Python developer fixing Mypy type errors.\n"
				f"FILE: {file_path}\n"
				f"ERROR: {err['msg']}\n"
				f"LINE {err['line']}: {original_line}\n\n"
				"Return ONLY the single corrected line of code. No markdown, no triple backticks. Just the code.\n"
				"Maintain the exact indentation of the original line."
			)

			raw_correction = engine.synthesize(context, prompt)
			correction = self._clean_correction(raw_correction)

			if correction and correction != original_line:
				self.log(f"  [Fix] L{err['line']}: {original_line.strip()} -> {correction.strip()}")
				lines[line_idx] = correction
				fixes_applied += 1

		if not dry_run and fixes_applied > 0:
			with open(file_path, "w") as f:
				f.write("\n".join(lines) + "\n")

		return fixes_applied

	def _clean_correction(self, raw: str) -> str:
		"""Cleans LLM output to extract a single code line."""
		clean = raw.strip()
		clean = re.sub(r"^```python\s*", "", clean, flags=re.IGNORECASE)
		clean = re.sub(r"^```\s*", "", clean, flags=re.IGNORECASE)
		clean = re.sub(r"\s*```$", "", clean)
		return clean.splitlines()[0] if clean.splitlines() else ""
