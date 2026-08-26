"""Normalización de ruido compartida (RFC-002 §5.2).

Extraída de `ChronicleIngester._refine_content` (scripts/antigravity_ingest.py)
para que el ingester y el renderer Memento produzcan texto limpio byte-idéntico.
Cualquier cambio aquí afecta a AMBOS pipelines a la vez — esa es la gracia.
"""

from __future__ import annotations

import re

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_LOG_NOISE_RE = re.compile(r"\[.*\] (DEBUG|TRACE|INFO) .*")
_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{200,}")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def normalize_noise(text: str) -> str:
	"""Heuristic Semantic Normalization: ANSI, líneas de log y blobs fuera; newlines colapsados."""
	text = _ANSI_RE.sub("", text)
	text = _LOG_NOISE_RE.sub("", text)
	text = _BLOB_RE.sub("[CONTENT_BLOB_REDACTED]", text)
	text = _MULTI_NEWLINE_RE.sub("\n\n", text)
	return text.strip()
