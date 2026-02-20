import os
import re
from pathlib import Path

# Protocol Criteria
TAB_INDENT_ONLY = re.compile(r"^ +")
ORNAMENTAL_COMMENT = re.compile(r"^#\s*[-=*#]{3,}")
CODE_COMMENT = re.compile(r"^#\s*(def|class|if|import|for|while|try|with|return|from)\b")

ROOT_DIR = Path(__file__).parent.parent
TARGET_DIRS = ["src", "scripts"]
EXTENSIONS = [".py", ".sh"]

def test_sound_of_silence_compliance():
	"""Ensures the codebase adheres to the Sound of Silence protocol."""
	violations = []
	
	for target in TARGET_DIRS:
		target_path = ROOT_DIR / target
		if not target_path.exists():
			continue
			
		for file_path in target_path.rglob("*"):
			if file_path.suffix not in EXTENSIONS:
				continue
				
			content = file_path.read_text()
			lines = content.splitlines()
			
			for i, line in enumerate(lines, 1):
				# 1. Indentation Check (Tabs only)
				if TAB_INDENT_ONLY.match(line):
					violations.append(f"{file_path.name}:{i} - Space indentation detected")
				
				# 2. Ornamental Comment Check
				if ORNAMENTAL_COMMENT.match(line):
					violations.append(f"{file_path.name}:{i} - Ornamental comment noise detected")
				
				# 3. Commented-out Code Check
				if CODE_COMMENT.match(line):
					violations.append(f"{file_path.name}:{i} - Commented-out code detected")

	if violations:
		error_msg = "\n".join(violations)
		raise AssertionError(f"Sound of Silence Violations Found:\n{error_msg}")
