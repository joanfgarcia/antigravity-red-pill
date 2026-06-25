import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest

from red_pill.core.paths import get_staging_dir, get_data_dir
from red_pill.metabolism.chronicle.claude_code_plugin import ClaudeCodeExtractorPlugin


def test_claude_code_extractor_standard_and_incremental(tmp_path):
	# Set up isolated directories
	claude_dir = tmp_path / ".claude" / "projects" / "test_project"
	claude_dir.mkdir(parents=True, exist_ok=True)
	session_file = claude_dir / "session_1.jsonl"

	# Mock data directory and staging directory by patching get_data_dir and get_staging_dir
	data_dir = tmp_path / "data"
	staging_dir = tmp_path / "staging"
	data_dir.mkdir(parents=True, exist_ok=True)
	staging_dir.mkdir(parents=True, exist_ok=True)

	# Mock Path.home to return tmp_path
	with patch("red_pill.metabolism.chronicle.claude_code_plugin.Path.home", return_value=tmp_path), \
		patch("red_pill.metabolism.chronicle.claude_code_plugin.get_data_dir", return_value=data_dir), \
		patch("red_pill.metabolism.chronicle.claude_code_plugin.get_staging_dir", return_value=staging_dir):

		# 1. Create a standard turn record
		records = [
			{
				"type": "user",
				"message": {
					"content": "What is the status of the bridge?"
				}
			},
			{
				"type": "assistant",
				"uuid": "uuid-turn-1",
				"message": {
					"model": "claude-3-5-sonnet-20241022",
					"content": [
						{"type": "text", "text": "The bridge is modularized."}
					],
					"stop_reason": "end_turn"
				}
			}
		]

		# Write to jsonl
		with open(session_file, "w", encoding="utf-8") as f:
			for r in records:
				f.write(json.dumps(r) + "\n")

		plugin = ClaudeCodeExtractorPlugin()
		count = plugin.extract()
		assert count == 1

		# Verify staged output
		staged_file = staging_dir / "claude_code_uuid-turn-1.json"
		assert staged_file.exists()
		with open(staged_file, "r", encoding="utf-8") as sf:
			payload = json.load(sf)
			assert payload["id"] == "claude_code_uuid-turn-1"
			assert payload["model"] == "claude-3-5-sonnet-20241022"
			assert len(payload["steps"]) == 2
			assert payload["steps"][0]["intent"] == "USER"
			assert payload["steps"][0]["message"]["text"] == "What is the status of the bridge?"
			assert payload["steps"][1]["intent"] == "ASSISTANT"
			assert payload["steps"][1]["message"]["text"] == "The bridge is modularized."

		# Verify offset saved
		offsets_file = data_dir / "chronicle_processed.json"
		assert offsets_file.exists()
		with open(offsets_file, "r", encoding="utf-8") as of:
			offsets = json.load(of)
			assert str(session_file.resolve()) in offsets
			first_offset = offsets[str(session_file.resolve())]
			assert first_offset > 0

		# 2. Extract again without changes: should stage 0 new turns
		count_again = plugin.extract()
		assert count_again == 0

		# 3. Append sidechain and a new turn containing tool use & tool result
		new_records = [
			{
				"type": "user",
				"isSidechain": True,
				"message": {
					"content": "Ignore this sidechain message"
				}
			},
			{
				"type": "user",
				"message": {
					"content": "Verify CUDA again."
				}
			},
			{
				"type": "assistant",
				"uuid": "uuid-turn-2",
				"message": {
					"model": "claude-3-5-sonnet-20241022",
					"content": [
						{"type": "tool_use", "name": "check_cuda", "input": {"verbose": True}}
					]
				}
			},
			{
				"type": "user",
				"message": {
					"content": [
						{
							"type": "tool_result",
							"tool_use_id": "tool-1",
							"content": "CUDA active"
						}
					]
				}
			},
			{
				"type": "assistant",
				"uuid": "uuid-turn-2",
				"message": {
					"model": "claude-3-5-sonnet-20241022",
					"content": [
						{"type": "text", "text": "CUDA is healthy."}
					],
					"stop_reason": "end_turn"
				}
			}
		]

		# Append to the jsonl file
		with open(session_file, "a", encoding="utf-8") as f:
			for r in new_records:
				f.write(json.dumps(r) + "\n")

		count_new = plugin.extract()
		assert count_new == 1

		# Verify staged output for turn 2
		staged_file2 = staging_dir / "claude_code_uuid-turn-2.json"
		assert staged_file2.exists()
		with open(staged_file2, "r", encoding="utf-8") as sf2:
			payload2 = json.load(sf2)
			assert payload2["id"] == "claude_code_uuid-turn-2"
			assert len(payload2["steps"]) == 4
			assert payload2["steps"][0]["intent"] == "USER"
			assert payload2["steps"][0]["message"]["text"] == "Verify CUDA again."
			assert payload2["steps"][1]["intent"] == "ASSISTANT"
			assert "[TOOL USE: check_cuda" in payload2["steps"][1]["message"]["text"]
			assert payload2["steps"][2]["intent"] == "USER"
			assert "[TOOL RESULT: id=tool-1 output=CUDA active]" in payload2["steps"][2]["message"]["text"]
			assert payload2["steps"][3]["intent"] == "ASSISTANT"
			assert payload2["steps"][3]["message"]["text"] == "CUDA is healthy."


def test_claude_code_extractor_concurrency_partial_lines(tmp_path):
	# Set up isolated directories
	claude_dir = tmp_path / ".claude" / "projects" / "test_project"
	claude_dir.mkdir(parents=True, exist_ok=True)
	session_file = claude_dir / "session_2.jsonl"

	data_dir = tmp_path / "data"
	staging_dir = tmp_path / "staging"
	data_dir.mkdir(parents=True, exist_ok=True)
	staging_dir.mkdir(parents=True, exist_ok=True)

	with patch("red_pill.metabolism.chronicle.claude_code_plugin.Path.home", return_value=tmp_path), \
		patch("red_pill.metabolism.chronicle.claude_code_plugin.get_data_dir", return_value=data_dir), \
		patch("red_pill.metabolism.chronicle.claude_code_plugin.get_staging_dir", return_value=staging_dir):

		# Write a complete user record and a partial/incomplete assistant record
		# The assistant record does not have a trailing newline (or is malformed JSON)
		user_record = {
			"type": "user",
			"message": {
				"content": "Initiate calibration."
			}
		}

		with open(session_file, "wb") as f:
			f.write(json.dumps(user_record).encode("utf-8") + b"\n")
			f.write(b'{"type": "assistant", "uuid": "uuid-turn-3", "message": {"model": "claude-3-5"')  # Partial JSON, no newline

		plugin = ClaudeCodeExtractorPlugin()
		count = plugin.extract()
		# Should not stage anything because the turn was not finished, but it should also not crash
		assert count == 0

		# Verify offset points to the end of user_record (after the newline)
		offsets_file = data_dir / "chronicle_processed.json"
		assert offsets_file.exists()
		with open(offsets_file, "r", encoding="utf-8") as of:
			offsets = json.load(of)
			expected_offset = len(json.dumps(user_record).encode("utf-8") + b"\n")
			assert offsets[str(session_file.resolve())] == 0

		# Now complete the assistant record and run again
		with open(session_file, "r+b") as f:
			f.seek(expected_offset)
			assistant_record = {
				"type": "assistant",
				"uuid": "uuid-turn-3",
				"message": {
					"model": "claude-3-5-sonnet-20241022",
					"content": "Calibration complete.",
					"stop_reason": "end_turn"
				}
			}
			f.write(json.dumps(assistant_record).encode("utf-8") + b"\n")

		count_complete = plugin.extract()
		assert count_complete == 1

		# Verify staging contains the complete turn
		staged_file = staging_dir / "claude_code_uuid-turn-3.json"
		assert staged_file.exists()
		with open(staged_file, "r", encoding="utf-8") as sf:
			payload = json.load(sf)
			assert payload["id"] == "claude_code_uuid-turn-3"
			assert payload["steps"][0]["message"]["text"] == "Initiate calibration."
			assert payload["steps"][1]["message"]["text"] == "Calibration complete."
