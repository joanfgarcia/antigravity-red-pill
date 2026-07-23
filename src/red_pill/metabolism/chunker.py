"""Text chunking, LLM-JSON sanitation, and template-echo detection.

Extracted from sleep.py per ADR-SLEEP-001. Pure text utilities — no LLM, no GPU.
"""

import re
from typing import List, Optional

import red_pill.config as cfg

_VALID_ESCAPES = frozenset('"\\bfnrtu/')

# Substrings that betray the distiller echoing its own prompt/format spec back
# as if it were memory content (observed in production hubs).
_TEMPLATE_ECHO_MARKERS = (
	"synthesize these memory chunks",
	"[memory synthesis",
	"master summary",
	"the emotion is one of",
	"the intensity is a float",
	"memory chunks into a",
)


def chunk_text(text: str, size: Optional[int] = None) -> List[str]:
	"""Break large interactions into biologically manageable sequences, respecting turn boundaries."""
	if size is None:
		size = cfg.SLEEP_CHUNK_SIZE

	if not text or not text.strip():
		return []

	chunks = []
	start = 0
	while start < len(text):
		end = start + size
		if end >= len(text):
			chunks.append(text[start:])
			break

		# Heuristic 0: Try finding turn/dialogue boundary markers (\nUSER:, \nASSISTANT:, \n---, \n\n)
		turn_break = -1
		for marker in ["\nUSER:", "\nASSISTANT:", "\nFixer:", "\nAleth:", "\n---", "\n\n"]:
			t_idx = text.rfind(marker, start, end)
			if t_idx > turn_break:
				turn_break = t_idx

		if turn_break != -1 and turn_break > start + (size // 3):
			end = turn_break + 1
		else:
			# Heuristic 1: Try finding a newline near the cut
			last_break = text.rfind("\n", start, end)
			if last_break != -1 and last_break > start + (size // 2):
				end = last_break + 1
			else:
				# Heuristic 2: Try finding a sentence terminator or comma
				found_punct = -1
				for punct in [". ", "? ", "! ", ", "]:
					p_idx = text.rfind(punct, start, end)
					if p_idx > found_punct:
						found_punct = p_idx

				if found_punct != -1 and found_punct > start + (size // 2):
					end = found_punct + 1  # Include the punctuation mark
				else:
					# Heuristic 3: Fallback to the last space
					last_space = text.rfind(" ", start, end)
					if last_space != -1 and last_space > start + (size // 2):
						end = last_space + 1

		chunks.append(text[start:end])
		start = end

	# Runt absorption: a trailing shard below 15% of the target size carries too
	# little signal to distill on its own (observed to induce texture hallucination)
	# — fold it into the previous chunk instead of emitting it.
	if len(chunks) >= 2 and len(chunks[-1]) < size * 0.15:
		chunks[-2] += chunks[-1]
		chunks.pop()
	return chunks


def _sanitize_llm_json(raw_json: str) -> str:
	"""Double illegal backslash escapes so json.loads stops raising 'Invalid \\escape'.

	JSON only allows \\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX. Local LLMs emit others
	(\\e, \\s, ...); any non-legal \\X is turned into a literal backslash + char.
	"""

	def _fix_escape(m: "re.Match") -> str:
		char_after = m.group(1)
		if char_after in _VALID_ESCAPES:
			return str(m.group(0))  # legal — leave untouched
		return str("\\\\" + char_after)

	return re.sub(r"\\(.)", _fix_escape, raw_json)


def _is_template_echo(text: str) -> bool:
	"""True if the distiller leaked its instructions (or produced nothing) instead of content.

	No length heuristic: a legitimately short summary ("Bug de tree_hash arreglado.")
	must survive. The high-precision signal is the instruction echo itself.
	"""
	if not text or not text.strip():
		return True
	low = text.strip().lower()
	return any(marker in low for marker in _TEMPLATE_ECHO_MARKERS)
