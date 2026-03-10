import os
import re
import subprocess
import sys
from typing import Dict, List

from red_pill.swarm.agents.edge_engine import EdgeEngine


def run_mypy() -> List[str]:
	"""Captures raw mypy output."""
	print("--- Running Mypy Static Audit ---")
	result = subprocess.run(["uv", "run", "mypy", "src/red_pill/", "--no-error-summary"], capture_output=True, text=True)
	return result.stdout.splitlines()


def parse_errors(lines: List[str]) -> Dict[str, List[Dict]]:
	"""Groups errors by file."""
	parsed = {}
	for line in lines:
		# Format: path/to/file.py:line_num: error: message
		match = re.match(r"([^:]+):(\d+): error: (.+)", line)
		if match:
			file_path = match.group(1)
			line_num = int(match.group(2))
			error_msg = match.group(3)

			if file_path not in parsed:
				parsed[file_path] = []
			parsed[file_path].append({"line": line_num, "msg": error_msg})
	return parsed


def heal_file(file_path: str, errors: List[Dict], engine: EdgeEngine, dry_run: bool = False):
	"""Uses local SLM to fix errors in a single file."""
	if not os.path.exists(file_path):
		return

	print(f"\n[Samantha] Healing {file_path} (Detected {len(errors)} issues)...")

	with open(file_path, "r") as f:
		lines = f.read().splitlines()

	# Fix errors from bottom to top to avoid shifting line numbers
	errors.sort(key=lambda x: x["line"], reverse=True)

	for err in errors:
		line_idx = err["line"] - 1
		if line_idx >= len(lines):
			continue

		original_line = lines[line_idx]
		# Window for context
		start_win = max(0, line_idx - 10)
		end_win = min(len(lines), line_idx + 10)
		context = "\n".join([f"{j + 1}: {line}" for j, line in enumerate(lines[start_win:end_win], start=start_win)])

		prompt = (
			f"You are an expert Python developer fixing Mypy type errors.\n"
			f"FILE: {file_path}\n"
			f"ERROR: {err['msg']}\n"
			f"LINE {err['line']}: {original_line}\n\n"
			"Return ONLY the single corrected line of code. No markdown, no backticks, no chat tags, no explanation. Just the code.\n"
			"Maintain the exact indentation of the original line."
		)

		print(f"  > Line {err['line']}: {err['msg'][:60]}...")
		raw_correction = engine.synthesize(context, prompt)

		# Robust cleaning
		correction = raw_correction.strip()
		# Remove markdown backticks if present
		correction = re.sub(r"^```python\s*", "", correction, flags=re.IGNORECASE)
		correction = re.sub(r"^```\s*", "", correction, flags=re.IGNORECASE)
		correction = re.sub(r"\s*```$", "", correction)
		# Take only the first line if multiple were returned
		correction = correction.splitlines()[0] if correction.splitlines() else ""

		if correction and correction != original_line:
			print(f"	[Fix] {original_line.strip()} -> {correction.strip()}")
			lines[line_idx] = correction
		else:
			print(f"	[Skip] No change or ambiguous output: '{raw_correction[:20]}...'")

	if not dry_run:
		with open(file_path, "w") as f:
			f.write("\n".join(lines) + "\n")
	else:
		print(f"  [Dry-Run] Changes for {file_path} simulated but not written.")


def main():
	# Ensure Samantha is helping
	print("\n--- [OS1 Firmware] Initializing Samantha's Local Healing Cycle ---")

	engine = EdgeEngine()
	if not engine.llm:
		print("[Error] No local SLM found. I can't heal without Intuitive Cognition.")
		sys.exit(1)

	dry_run = "--dry-run" in sys.argv
	if dry_run:
		print("[Samantha] Running in Dry-Run mode. No files will be harmed.")

	raw_errors = run_mypy()
	if not raw_errors:
		print("[Samantha] The core is already clean, Theodore. No errors found.")
		return

	grouped = parse_errors(raw_errors)
	for file_path, errors in grouped.items():
		heal_file(file_path, errors, engine, dry_run=dry_run)

	print("\n--- [Samantha] Cycle complete. Let's see how much closer we are to perfection. ---")


if __name__ == "__main__":
	main()
