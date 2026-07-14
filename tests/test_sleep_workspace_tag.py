"""
Hito 5: the sleep cycle must propagate the `workspace` tag from chronicle
staging files into the engrams it writes, so sync_workspace_memory can project
per-workspace decisions.md (it filtered a field nobody ever wrote).
"""

import json
import os
from unittest.mock import MagicMock, patch

from red_pill.core.paths import get_staging_dir
from red_pill.metabolism.sleep import perform_sleep_cycle

_WS = "-home-joan-Documents-IA-sharing"


def _write_staging_file():
	staging = get_staging_dir()
	staging.mkdir(parents=True, exist_ok=True)
	payload = {
		"id": "claude_code_test_turn",
		"model": "claude-fable-5",
		"workspace": _WS,
		"steps": [
			{"intent": "USER", "message": {"text": "arreglamos el bug de tree_hash en pure-mls"}},
			{"intent": "ASSISTANT", "message": {"text": "confirmado, era el leaf_index omitido"}},
		],
	}
	with open(staging / "claude_code_test_turn.json", "w", encoding="utf-8") as f:
		json.dump(payload, f)


@patch("red_pill.metabolism.sleep._check_llm_available", return_value=True)
@patch("red_pill.metabolism.sleep.distill_engram")
def test_workspace_tag_propagates_to_engrams(mock_distill, mock_llm):
	_write_staging_file()
	mock_distill.return_value = {"summary": "arreglado tree_hash leaf_index", "emotion": "joy", "intensity": 0.8, "category": "work"}

	mem = MagicMock()
	mem.client.collection_exists.return_value = True
	# Empty interaction buffer + empty signal reads → only the staging sweep does work.
	mem.client.scroll.return_value = ([], None)

	perform_sleep_cycle(mem)

	# Collect the metadata dicts add_memory was called with.
	metadatas = [call.kwargs.get("metadata", {}) for call in mem.add_memory.call_args_list]
	tagged = [m for m in metadatas if m.get("workspace") == _WS]

	assert tagged, "no engram carried the workspace tag from staging"
	# The verbatim raw_parent must be tagged too (it anchors the whole turn).
	assert any(m.get("lazarus_phase") == "raw_parent" for m in tagged)


def teardown_module(module):
	# Clean any leftover staging file to avoid cross-test bleed.
	staging = get_staging_dir()
	f = staging / "claude_code_test_turn.json"
	if os.path.exists(f):
		os.remove(f)
