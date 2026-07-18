"""Heuristic work/social classifier for raw interaction text.

Extracted from sleep.py per ADR-SLEEP-001. Pure text analysis — no LLM, no GPU.
"""

import re
from typing import Any

_TECH_KEYWORDS = {
	"code",
	"código",
	"test",
	"pytest",
	"bug",
	"error",
	"git",
	"github",
	"diff",
	"patch",
	"repo",
	"repository",
	"docker",
	"systemd",
	"systemctl",
	"mcp",
	"api",
	"endpoint",
	"database",
	"db",
	"query",
	"python",
	"rust",
	"compile",
	"script",
	"cli",
	"command",
	"terminal",
	"bash",
	"shell",
	"exception",
	"traceback",
	"stacktrace",
	"import",
	"class",
	"def",
	"fn",
	"const",
	"impl",
	"interface",
	"refactor",
	"build",
	"deploy",
	"server",
	"client",
	"vram",
	"gpu",
	"cuda",
	"npu",
	"cpu",
	"memory",
	"cache",
	"token",
	"llm",
	"prompt",
	"model",
	"config",
	"port",
	"socket",
	"grpc",
	"json",
	"xml",
	"yaml",
	"file",
	"directory",
	"path",
	"permissions",
	"chmod",
	"chown",
	"ssh",
	"curl",
	"wget",
	"http",
}


def detect_category_heuristics(text: Any) -> str:
	"""Classify text as 'work' only on DENSE technical signal, else 'social'.

	A single keyword match is not evidence: terms like "error", "test", "model"
	or "file" appear in passing in most personal conversations, and the old
	any-hit rule routed them (hub included) into work_memories — the root cause
	of the social/work imbalance (R1). Ambiguity now resolves to 'social': a
	technical note landing in social keeps its conversational context; a personal
	reflection landing in work loses its soul.
	"""
	if not isinstance(text, str):
		text = str(text)
	text_lower = text.lower()
	if "```" in text:
		return "work"
	words = re.findall(r"[a-zA-Z0-9_]+", text_lower)
	if not words:
		return "social"
	distinct_hits = set(words).intersection(_TECH_KEYWORDS)
	if len(distinct_hits) >= 3:
		return "work"
	# Short texts can't accumulate 3 distinct keywords: use density of keyword
	# occurrences (repetitions count — a stacktrace repeats "error" a lot).
	hit_occurrences = sum(1 for w in words if w in _TECH_KEYWORDS)
	if hit_occurrences / len(words) > 0.08:
		return "work"
	return "social"
