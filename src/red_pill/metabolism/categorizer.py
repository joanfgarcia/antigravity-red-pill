"""Heuristic work/social classifier for raw interaction text.

Extracted from sleep.py per ADR-SLEEP-001. Pure text analysis — no LLM, no GPU.
"""

import re
from typing import Any

_TECH_KEYWORDS = {
	"code", "código", "test", "pytest", "bug", "error", "git", "github", "diff",
	"patch", "repo", "repository", "docker", "systemd", "systemctl", "mcp", "api",
	"endpoint", "database", "db", "query", "python", "rust", "compile", "script",
	"cli", "command", "terminal", "bash", "shell", "exception", "traceback",
	"stacktrace", "import", "class", "def", "fn", "const", "impl", "interface",
	"refactor", "build", "deploy", "server", "client", "vram", "gpu", "cuda", "npu",
	"cpu", "memory", "cache", "token", "llm", "prompt", "model", "config", "port",
	"socket", "grpc", "json", "xml", "yaml", "file", "directory", "path",
	"permissions", "chmod", "chown", "ssh", "curl", "wget", "http",
}


def detect_category_heuristics(text: Any) -> str:
	"""Classify text as 'work' if it carries technical/development signals, else 'social'."""
	if not isinstance(text, str):
		text = str(text)
	text_lower = text.lower()
	if "```" in text:
		return "work"
	words = set(re.findall(r"[a-zA-Z0-9_]+", text_lower))
	if words.intersection(_TECH_KEYWORDS):
		return "work"
	return "social"
