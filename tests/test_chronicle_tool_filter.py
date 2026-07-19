"""Chronicle noise pre-filter: compact tool markers instead of full payload dumps."""

import red_pill.config as cfg
from red_pill.metabolism.chronicle.claude_code_plugin import (
	_render_tool_result,
	_render_tool_use,
	extract_assistant_blocks,
	extract_user_content,
)


def test_tool_use_compacted_with_hint(monkeypatch):
	monkeypatch.setattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", True)
	text = _render_tool_use("Edit", {"file_path": "/home/joan/x.py", "old_string": "A" * 5000, "new_string": "B" * 5000})
	assert text == "[TOOL: Edit file_path=/home/joan/x.py]"
	assert len(text) < 120


def test_tool_use_full_when_flag_off(monkeypatch):
	monkeypatch.setattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", False)
	text = _render_tool_use("Edit", {"file_path": "/x.py"})
	assert text.startswith("[TOOL USE: Edit(") and "/x.py" in text


def test_tool_result_keeps_head_where_verdicts_live(monkeypatch):
	monkeypatch.setattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", True)
	output = "FAILED tests/test_x.py::test_y - AssertionError\n" + "ruido " * 2000
	text = _render_tool_result("tu_1", output)
	assert "FAILED tests/test_x.py::test_y" in text
	assert len(text) < 220
	assert "omitted" in text


def test_extract_assistant_blocks_uses_compact_marker(monkeypatch):
	monkeypatch.setattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", True)
	message = {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls -la", "big": "x" * 9000}}]}
	blocks = extract_assistant_blocks(message)
	assert blocks[0]["message"]["text"] == "[TOOL: Bash command=ls -la]"


def test_extract_user_content_compacts_tool_result(monkeypatch):
	monkeypatch.setattr(cfg, "CHRONICLE_STRIP_TOOL_PAYLOADS", True)
	message = {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "salida " * 500}]}
	text = extract_user_content(message)
	assert len(text) < 220 and text.startswith("[TOOL RESULT:")
