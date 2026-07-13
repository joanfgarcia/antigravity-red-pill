"""
Regression test for the payload field bug (Hito 1).

Interceptors 08 (Emotive Recall) and 10 (Predictive Preload) used to read
`payload.get("text")`, but MemoryManager.add_memory persists the engram text
under the `content` key. The mismatch made both plugins inject empty strings
forever. These tests pin the canonical field: a sentinel stored in `content`
MUST surface in the injected block.

Plugin modules start with digits, so import them via importlib.
MemoryManager is imported lazily inside execute(), so patch it at the source.
"""

import asyncio
import importlib
from unittest.mock import MagicMock, patch

_SENTINEL = "ENGRAMA_SENTINEL_XYZ"


def _hit():
	r = MagicMock()
	r.payload = {
		"content": _SENTINEL,
		"color": "cyan",
		"emotion": "joy",
		"intensity": 0.9,
		"created_at": 0.0,
	}
	return r


def _mem_mock():
	m = MagicMock()
	m.search_and_reinforce.return_value = [_hit()]
	return m


def test_emotive_recall_injects_content_field():
	mod = importlib.import_module("red_pill.interceptors.08_emotive_recall")
	p = mod.EmotiveRecallPlugin()
	with (
		patch.object(mod, "get_current_sync_state", return_value={"mood": "cyan"}),
		patch("red_pill.memory.MemoryManager", return_value=_mem_mock()),
	):
		result = asyncio.run(p.execute("test"))
	assert _SENTINEL in result


def test_predictive_preload_injects_content_field():
	mod = importlib.import_module("red_pill.interceptors.10_predictive_preload")
	p = mod.PredictivePreloadPlugin()
	with (
		patch.object(mod, "get_current_sync_state", return_value={"mood": "cyan"}),
		patch("red_pill.memory.MemoryManager", return_value=_mem_mock()),
	):
		result = asyncio.run(p.execute("test"))
	assert _SENTINEL in result
