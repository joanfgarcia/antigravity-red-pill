import os
import sys


def create_digest(repo_path: str, output_file: str, ignore_dirs: list[str] = None):
	if ignore_dirs is None:
		ignore_dirs = [
			# Version control & tooling artifacts
			".git",
			"__pycache__",
			"venv",
			".venv",
			"node_modules",
			"dist",
			"build",
			".mypy_cache",
			".ruff_cache",
			# Test suite: reviewed separately via RED_PILL_DIGEST_TESTS
			"tests",
			# Documentation: excluded from CORE digest by design.
			# Key supply-chain and architecture info lives in root-level files
			# (pyproject.toml, CHANGELOG.md, NOTICE, README.md) which ARE included.
			# docs/ contains: LORE (narrative, CC BY-NC), CERTIFICATION/ (past audit
			# reports that are NOT the current codebase state), and GUIDES/TECHNICAL
			# that duplicate information already in inline docstrings and config.
			# If a future auditor needs docs/, pass them via a separate LORE digest.
			"docs",
			# Build scripts: reviewed separately if needed
			"scripts",
		]

	def is_ignored(path):
		for ignore in ignore_dirs:
			if ignore in path.split(os.sep):
				return True
		return False

	with open(output_file, "w", encoding="utf-8") as outfile:
		# 1. Write the source code
		outfile.write("=== SOURCE CODE ===\n\n")
		for root, _, files in os.walk(repo_path):
			if is_ignored(root):
				continue
			for file in files:
				if file.endswith(".py") or file.endswith(".toml") or file.endswith(".yaml") or file.endswith(".json") or file.endswith(".md"):
					filepath = os.path.join(root, file)
					relpath = os.path.relpath(filepath, repo_path)

					# Ignore this script itself or the output
					if relpath == "scripts/create_digest.py" or file == os.path.basename(output_file):
						continue

					outfile.write(f"--- BEGIN FILE: {relpath} ---\n")
					try:
						with open(filepath, "r", encoding="utf-8") as infile:
							outfile.write(infile.read())
					except Exception as e:
						outfile.write(f"Error reading file: {e}\n")
					outfile.write(f"\n--- END FILE: {relpath} ---\n\n")

		# 2. Write the directory tree map
		outfile.write("=== DIRECTORY MAP ===\n\n")
		for root, dirs, files in os.walk(repo_path):
			if is_ignored(root):
				dirs[:] = []  # stop traversing this directory
				continue

			level = root.replace(repo_path, "").count(os.sep)
			indent = " " * 4 * (level)
			outfile.write(f"{indent}{os.path.basename(root)}/\n")
			subindent = " " * 4 * (level + 1)
			for f in files:
				outfile.write(f"{subindent}{f}\n")


if __name__ == "__main__":
	target = sys.argv[1] if len(sys.argv) > 1 else "."
	out = sys.argv[2] if len(sys.argv) > 2 else "digest.txt"
	create_digest(target, out)
	print(f"Digest created at: {out}")
