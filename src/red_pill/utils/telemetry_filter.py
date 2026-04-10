import math
import re
from collections import Counter

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
MD_CODE_BLOCK = re.compile(r"```(?:[a-zA-Z0-9#\-\+]+)?\n(.*?)\n```", re.DOTALL)


def calculate_entropy(text: str) -> float:
	"""
	Calculates the Shannon Entropy of the text based on character frequency.
	Used as a proxy for 'informational density'.
	"""
	if not text:
		return 0.0
	prob = [n_c / len(text) for n_c in Counter(text).values()]
	entropy = -sum(p * math.log2(p) for p in prob)
	return entropy


def is_garbage(content: str) -> bool:
	"""
	Dictates if a chunk of text is machine noise/garbage.
	It evaluates CI strings, ANSI ratios, and repetition loops.
	"""
	if not content:
		return False

	content_stripped = content.strip()
	if len(content_stripped) < 5:
		return True  # Very short content is essentially noise for memory

	# ANSI removal for clean evaluation
	ansi_stripped = ANSI_ESCAPE.sub("", content_stripped)

	content_lower = ansi_stripped.lower()

	# Definitive CI/Tooling signatures
	ci_definitive = [
		"pre-pr audit protocol",
		"b760 pre-pr audit",
		"formatting check (ruff)",
		"linting check (ruff)",
		"static analysis (mypy)",
		"neural validation (pytest)",
		"pre-pr audit [",
		"=================================== failures ===================================",
		"========= short test summary info =========",
		"collected ",
		" items / ",
		" errors",
		"subprocess.run(",
		"git rev-parse",
		"git status",
		"git commit",
		"finding files...",
	]
	if any(sig in content_lower for sig in ci_definitive):
		return True

	# Weighted noise markers
	ci_markers = [
		"--- formatting check",
		"--- linting check",
		"--- static analysis",
		"--- neural validation",
		"warnings summary",
		"passed in",
		"PASS",
		"FAIL",
		"pytest.org",
		"short test summary",
		"capture-warnings",
		"check-lint",
		"check-format",
		"no issues found",
		"success:",
		"failure:",
	]
	ci_hits = sum(1 for m in ci_markers if m.lower() in content_lower)
	if ci_hits >= 2:
		return True

	# ANSI noise threshold: If >40% of the string was ANSI escapes, it's a terminal dump
	if len(content_stripped) > 30 and len(ansi_stripped) < len(content_stripped) * 0.6:
		return True

	# Repetition check: Detect local loops or highly repetitive logs
	words = content_lower.split()
	if len(words) > 10:
		freq = Counter(words)
		most_common_count = freq.most_common(1)[0][1]
		if most_common_count > len(words) * 0.35:
			return True

	# Entropy check: Low entropy usually means repetitive/boilerplate content (e.g. "........")
	# High entropy on small strings can also mean random noise/hashes.
	if len(ansi_stripped) > 100:
		entropy = calculate_entropy(ansi_stripped)
		# 2.5 is a very low threshold (repetitive),
		# average English is ~4.0-5.0. Code can be lower but <3.0 is suspicious.
		if entropy < 2.5:
			return True

	return False


def filter_noise_from_turn(text: str) -> str:
	"""
	Surgically extract memory-safe content separating the human element
	from the raw terminal noise trapped inside MDCB.
	"""
	if not text:
		return text

	# 1. Surgical block-level filtering
	cleaned_text = MD_CODE_BLOCK.sub(lambda m: "```\n[...]\n```" if is_garbage(m.group(1)) else m.group(0), text)

	# 2. Global turn-level filtering
	# If the result (after surgical truncation) still looks like garbage, discard.
	if is_garbage(cleaned_text):
		return ""

	return cleaned_text
