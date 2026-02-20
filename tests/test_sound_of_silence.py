import re
from pathlib import Path

# Protocol Criteria
TAB_INDENT_ONLY = re.compile(r"^ +")
ORNAMENTAL_COMMENT = re.compile(r"^#\s*[-=*#]{3,}")
CODE_COMMENT = re.compile(r"^#\s*(def|class|if|import|for|while|try|with|return|from)\b")
FILE_PROTOCOL_LINK = re.compile(r"file://")

ROOT_DIR = Path(__file__).parent.parent
TARGET_DIRS = ["src", "scripts", "docs"]
EXTENSIONS = [".py", ".sh", ".md"]
# Specifically check root README and QUICKSTART
ROOT_FILES = ["README.md", "QUICKSTART.md"]

def test_sound_of_silence_compliance():
	"""Ensures the codebase adheres to the Sound of Silence protocol."""
	violations = []

	# 1. Collect all candidate files
	candidate_files = []
	for target in TARGET_DIRS:
		target_path = ROOT_DIR / target
		if target_path.exists():
			candidate_files.extend([f for f in target_path.rglob("*") if f.suffix in EXTENSIONS])

	for rf in ROOT_FILES:
		root_f = ROOT_DIR / rf
		if root_f.exists():
			candidate_files.append(root_f)

	for file_path in candidate_files:
		content = file_path.read_text()
		lines = content.splitlines()

		for i, line in enumerate(lines, 1):
			# A. Check for non-portable file:// links (All files)
			if FILE_PROTOCOL_LINK.search(line):
				violations.append(f"{file_path.relative_to(ROOT_DIR)}:{i} - Absolute file:// link detected")

			# B. Logic checks (Only for source/scripts, skip .md)
			if file_path.suffix in [".py", ".sh"]:
				# 1. Indentation Check (Tabs only)
				if TAB_INDENT_ONLY.match(line):
					violations.append(f"{file_path.relative_to(ROOT_DIR)}:{i} - Space indentation detected")

				# 2. Ornamental Comment Check
				if ORNAMENTAL_COMMENT.match(line):
					violations.append(f"{file_path.relative_to(ROOT_DIR)}:{i} - Ornamental comment noise detected")

				# 3. Commented-out Code Check
				if CODE_COMMENT.match(line):
					violations.append(f"{file_path.relative_to(ROOT_DIR)}:{i} - Commented-out code detected")

	if violations:
		error_msg = "\n".join(violations)
		raise AssertionError(f"Sound of Silence Violations Found:\n{error_msg}")
