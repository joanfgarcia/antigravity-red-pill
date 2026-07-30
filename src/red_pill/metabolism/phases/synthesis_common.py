"""Shared plumbing for sleep synthesis phases (OperatorProfile, RecentActivity).

These phases *remember* — they read the Bünker with raw read-only scrolls that
never go through search_and_reinforce(), so recalling context for a synthesis
does NOT strengthen the engrams involved. They synthesize with the local LLM
and atomically publish an .md artifact that the wake-up ritual injects.
"""

import json
import logging
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

QDRANT_URL = "http://localhost:6333"
LLM_URL = "http://127.0.0.1:8760/v1/chat/completions"
LLM_TIMEOUT_S = 150  # Granite on shared VRAM needs 50-65s warm; 30s starved every call

# Consolidation by-products and hub fragments must never feed a synthesis prompt
NON_CANONICAL_FILTER: Dict[str, Any] = {
	"must_not": [
		{"key": "lazarus_phase", "match": {"any": ["raw_parent", "sequence_chunk", "texture_shadow"]}},
		{"key": "_is_fragment", "match": {"value": True}},
	]
}


def _qdrant_headers() -> Dict[str, str]:
	load_dotenv(Path.home() / ".config/red-pill/.env")
	headers = {"Content-Type": "application/json"}
	api_key = os.getenv("QDRANT_API_KEY", "")
	if api_key:
		headers["api-key"] = api_key
	return headers


def scroll_contents(collection: str, limit: int, flt: Optional[dict] = None, newest_first: bool = False, tag: str = "SYNTH") -> List[str]:
	"""Read-only scroll returning engram contents. No reinforcement side-effects."""
	payload_dict: Dict[str, Any] = {"limit": limit, "with_payload": ["content"]}
	if flt:
		payload_dict["filter"] = flt
	if newest_first:
		payload_dict["order_by"] = {"key": "created_at", "direction": "desc"}

	url = f"{QDRANT_URL}/collections/{collection}/points/scroll"
	req = urllib.request.Request(url, data=json.dumps(payload_dict).encode("utf-8"), headers=_qdrant_headers(), method="POST")
	try:
		with urllib.request.urlopen(req, timeout=10) as resp:
			points = json.loads(resp.read().decode()).get("result", {}).get("points", [])
	except Exception as e:
		if newest_first:
			# order_by needs a payload index on created_at; degrade to unordered rather than empty
			logger.warning(f"[{tag}] Ordered scroll failed for {collection} ({e}); retrying unordered.")
			payload_dict.pop("order_by")
			req = urllib.request.Request(url, data=json.dumps(payload_dict).encode("utf-8"), headers=_qdrant_headers(), method="POST")
			try:
				with urllib.request.urlopen(req, timeout=10) as resp:
					points = json.loads(resp.read().decode()).get("result", {}).get("points", [])
			except Exception as e2:
				logger.warning(f"[{tag}] Qdrant query failed for {collection}: {e2}")
				return []
		else:
			logger.warning(f"[{tag}] Qdrant query failed for {collection}: {e}")
			return []

	return [c for p in points if (c := (p.get("payload") or {}).get("content", ""))]


def recall_recent(collection: str, limit: int, tag: str = "SYNTH") -> List[str]:
	"""Newest canonical engrams: synthesis hubs AND not-yet-split memories alike."""
	return scroll_contents(collection, limit, flt=NON_CANONICAL_FILTER, newest_first=True, tag=tag)


def chat(system: str, user: str, max_tokens: int, tag: str = "SYNTH") -> str:
	"""One deterministic call to the local LLM. Empty string on failure."""
	payload = json.dumps(
		{
			"messages": [
				{"role": "system", "content": system},
				{"role": "user", "content": user},
			],
			"temperature": 0.0,
			"max_tokens": max_tokens,
			"seed": 760,
		}
	).encode("utf-8")

	req = urllib.request.Request(LLM_URL, data=payload, headers={"Content-Type": "application/json"})
	try:
		with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
			return json.loads(resp.read().decode())["choices"][0]["message"]["content"].strip()
	except Exception as e:
		logger.warning(f"[{tag}] LLM call failed: {e}")
		return ""


def publish(path: Path, text: str) -> None:
	"""Atomic write so a concurrent wake-up never reads a half-written artifact."""
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_name(path.name + ".tmp")
	tmp.write_text(text)
	tmp.replace(path)


def is_fresh(path: Path, max_age_hours: float) -> bool:
	"""True if the artifact exists and is younger than max_age_hours (skip re-synthesis)."""
	try:
		return path.exists() and (time.time() - path.stat().st_mtime) < max_age_hours * 3600
	except Exception:
		return False
