import re
from pathlib import Path

TAB_INDENT_ONLY = re.compile("^ +")
ORNAMENTAL_COMMENT = re.compile("^#\\s*[-=*#]{3,}")
CODE_COMMENT = re.compile("^#\\s*(def|class|if|import|for|while|try|with|return|from)\\b")
FILE_PROTOCOL_LINK = re.compile("file://")
HOME_DIR_PATH = re.compile("/(home|Users)/[a-zA-Z0-9_-]+/")
ROOT_DIR = Path(__file__).parent.parent
TARGET_DIRS = ["src", "scripts", "docs"]
EXTENSIONS = [".py", ".sh", ".md"]
ROOT_FILES = ["README.md", "QUICKSTART.md"]
# Files excluded from space-indent and ornamental checks due to legitimate exceptions
# (e.g. embedded Python heredoc in shell scripts requires space indentation)
EXCLUDED_FROM_STYLE_CHECKS = {"scripts/install_neo.sh"}


def test_sound_of_silence_compliance():
	"""Ensures the codebase adheres to the Sound of Silence protocol."""
	violations = []
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
		if file_path.suffix == ".md":
			stem = file_path.stem
			stem_no_version = re.sub("v\\d+(\\.\\d+)*", "", stem)
			if stem_no_version != stem_no_version.upper():
				violations.append(f"{file_path.relative_to(ROOT_DIR)} - Markdown file name must be UPPER_SNAKE_CASE")
		content = file_path.read_text()
		lines = content.splitlines()
		for i, line in enumerate(lines, 1):
			if "certification" not in [p.lower() for p in file_path.parts] and FILE_PROTOCOL_LINK.search(line):
				violations.append(f"{file_path.relative_to(ROOT_DIR)}:{i} - Absolute file:// link detected")
			if HOME_DIR_PATH.search(line) and "SOVEREIGNTY_PROOF.json" not in file_path.name:
				violations.append(f"{file_path.relative_to(ROOT_DIR)}:{i} - Hardcoded home directory path detected")
			if file_path.suffix in [".py", ".sh"]:
				rel = str(file_path.relative_to(ROOT_DIR))
				if rel in EXCLUDED_FROM_STYLE_CHECKS:
					continue
				if TAB_INDENT_ONLY.match(line):
					violations.append(f"{file_path.relative_to(ROOT_DIR)}:{i} - Space indentation detected")
				if ORNAMENTAL_COMMENT.match(line):
					violations.append(f"{file_path.relative_to(ROOT_DIR)}:{i} - Ornamental comment noise detected")
				if CODE_COMMENT.match(line):
					violations.append(f"{file_path.relative_to(ROOT_DIR)}:{i} - Commented-out code detected")
	if violations:
		error_msg = "\n".join(violations)
		raise AssertionError(f"Sound of Silence Violations Found:\n{error_msg}")


def test_markdown_links_compliance():
	"""Ensure all internal markdown links resolve to existing files."""
	violations = []
	candidate_files = []
	for target in TARGET_DIRS:
		target_path = ROOT_DIR / target
		if target_path.exists():
			candidate_files.extend(list(target_path.rglob("*.md")))
	for rf in ROOT_FILES:
		root_f = ROOT_DIR / rf
		if root_f.exists():
			candidate_files.append(root_f)
	for file_path in candidate_files:
		content = file_path.read_text(encoding="utf-8")
		links = re.findall("\\[.+?\\]\\((?!http|mailto|file|/|~)([^)#\\s]+)(?:#[^\\)]*)?\\)", content)
		for link in links:
			target_path = (file_path.parent / link).resolve()
			if not target_path.exists():
				violations.append(f"{file_path.relative_to(ROOT_DIR)}: '{link}' -> missing target")
	if violations:
		error_msg = "\n".join(violations)
		raise AssertionError(f"Broken Markdown Links Found:\n{error_msg}")
