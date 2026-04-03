import pytest
from red_pill.utils.telemetry_filter import is_garbage, filter_noise_from_turn


def test_is_garbage_empty_or_short():
	assert is_garbage("") is False
	assert is_garbage("   ") is False
	assert is_garbage("hi") is False


def test_is_garbage_pytest():
	content = "=================================== FAILURES ===================================\nERROR tests/test_sound_of_silence.py\n========= short test summary info ========="
	assert is_garbage(content) is True


def test_is_garbage_pre_pr_audit():
	content = "[B760 PRE-PR AUDIT PROTOCOL v2.0]\n--- Formatting Check (Ruff) ---\nPASS\n"
	assert is_garbage(content) is True


def test_is_garbage_ansi():
	# 90% ANSI string
	content = "\x1b[0;34m" * 15 + "hello" + "\x1b[0m" * 15
	assert is_garbage(content) is True


def test_is_garbage_clean_text():
	content = "This is a clean and totally fine explanation about how we can optimize Qdrant with HNSW indexes."
	assert is_garbage(content) is False


def test_filter_noise_clean_prompt():
	prompt = "I think the architecture is solid. See this function:\n```python\ndef test(): pass\n```\nWhat do you think?"
	# Should remain unchanged since it's not garbage
	res = filter_noise_from_turn(prompt)
	assert "def test(): pass" in res
	assert "architecture is solid" in res


def test_filter_noise_surgical_truncate():
	prompt = "This test failed miserably:\n```bash\n=================================== FAILURES ===================================\nERROR tests/something.py\n```\nBut don't worry, the philosophical meaning behind this failure is that human error is inevitable."
	res = filter_noise_from_turn(prompt)

	# The garbage block should be truncated
	assert "FAILURES" not in res
	assert "[...]" in res
	# The human philosophy MUST remain untouched
	assert "failed miserably:" in res
	assert "inevitable." in res
