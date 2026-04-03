import re
from collections import Counter

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
MD_CODE_BLOCK = re.compile(r'```(?:[a-zA-Z0-9#\-\+]+)?\n(.*?)\n```', re.DOTALL)


def is_garbage(content: str) -> bool:
	"""
	Dictates if a chunk of text is machine noise/garbage.
	It evaluates CI strings, ANSI ratios, and repetition loops.
	"""
	if not content or len(content.strip()) < 5:
		return False

	ansi_stripped = ANSI_ESCAPE.sub("", content)

	content_lower_stripped = ansi_stripped.lower()
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
	]
	if any(sig in content_lower_stripped for sig in ci_definitive):
		return True

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
		"capture-warnings"
	]
	ci_hits = sum(1 for m in ci_markers if m.lower() in content_lower_stripped)
	if ci_hits >= 2:
		return True

	if len(content) > 30 and len(ansi_stripped) < len(content) * 0.6:
		return True

	words = content.lower().split()
	if len(words) > 10:
		freq = Counter(words)
		most_common = freq.most_common(1)[0][1]
		if most_common > len(words) * 0.35:
			return True

	return False


def filter_noise_from_turn(text: str) -> str:
	"""
	Surgically extract memory-safe content separating the human element
	from the raw terminal noise trapped inside MDCB.
	"""
	if not text:
		return text

	def evaluate_block(match):
		block_content = match.group(1)
		if is_garbage(block_content):
			return "```\n[...]\n```"
		# If it's valid code, we preserve the original match
		return match.group(0)

	cleaned_text = MD_CODE_BLOCK.sub(evaluate_block, text)
	return cleaned_text
