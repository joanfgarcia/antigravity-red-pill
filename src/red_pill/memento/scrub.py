"""Scrubber de secretos MUST-9 (RFC-002 §3.1.9, §5.2).

Los tool inputs se renderizan al Memento (comandos bash incluidos), así que
credenciales tecleadas en terminales LLEGARÍAN a disco sin esta pasada. Se
redactan formas comunes de credencial; el histórico git (MAY 16) está gateado
a que esto exista. Sesgo deliberado: mejor un falso positivo puntual que un
token inmortalizado en markdown.
"""

from __future__ import annotations

import re
from typing import List, Pattern

REDACTED = "[SECRET_REDACTED]"

# Formas con estructura propia (prefijos de vendor, JWT, bloques PEM).
_TOKEN_PATTERNS: List[Pattern[str]] = [
	re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"),
	re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
	re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
	re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
	re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
	re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),  # OpenAI / Anthropic style
	re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
	re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),  # Google API key
	re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}\b"),  # Google OAuth access token
	re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"),  # JWT
	re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
]

# Asignaciones `clave = valor` cuya clave huele a credencial. El valor solo se
# redacta si parece un literal secreto (charset de token, ≥8 chars); `$VAR`,
# `<placeholder>` y llamadas a función se respetan para no mutilar código.
_ASSIGNMENT_RE = re.compile(
	r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|apikey|authorization|auth[_-]?token|access[_-]?key|client[_-]?secret)\b"
	r"(\s*[:=]\s*)"
	r"(\"[^\"]{4,}\"|'[^']{4,}'|[A-Za-z0-9_\-./+=]{8,})"
)

# Userinfo en URLs: `scheme://user:pass@host` — se conserva el usuario.
_URL_USERINFO_RE = re.compile(r"(://[^/\s:@]{1,64}):([^/\s@]{1,256})@")


def _redact_assignment(match: "re.Match[str]") -> str:
	value = match.group(3)
	bare = value.strip("\"'")
	if bare.startswith(("$", "<", "{")):
		return match.group(0)
	return f"{match.group(1)}{match.group(2)}{REDACTED}"


def scrub_secrets(text: str) -> str:
	"""Redacta credenciales de formas comunes; idempotente y sin tocar el resto del texto."""
	for pattern in _TOKEN_PATTERNS:
		text = pattern.sub(REDACTED, text)
	text = _ASSIGNMENT_RE.sub(_redact_assignment, text)
	text = _URL_USERINFO_RE.sub(rf"\1:{REDACTED}@", text)
	return text
