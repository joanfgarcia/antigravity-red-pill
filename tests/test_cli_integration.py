import subprocess

import pytest


def run_cli(args, input_text=None):
	"""Helper to run the red-pill CLI."""
	import os
	import sys

	env = os.environ.copy()
	env["PYTHONPATH"] = os.path.join(os.getcwd(), "src")
	cmd = [sys.executable, "-m", "red_pill.cli"] + args
	result = subprocess.run(cmd, input=input_text, capture_output=True, text=True, env=env)
	return result


@pytest.mark.integration
def test_cli_search_deep_recall():
	"""Verify that the --deep flag works via CLI."""
	result = run_cli(["search", "work", "Lazarus", "--deep"])
	assert result.returncode == 0 or "Protocol Failure" in result.stderr
	assert "NameError" not in result.stderr


@pytest.mark.integration
def test_cli_search_trigger_keyword():
	"""Verify that deep recall trigger keywords work via CLI (BUG-001 check)."""
	result = run_cli(["search", "work", "despierta"])
	assert result.returncode == 0 or "Protocol Failure" in result.stderr
	assert "NameError" not in result.stderr


@pytest.mark.integration
def test_cli_mode_switch():
	"""Verify lore skin switching via CLI."""
	result = run_cli(["mode", "cyberpunk"], input_text="Y\n")
	assert result.returncode == 0
	assert "Operational Mode: CYBERPUNK" in result.stdout


@pytest.mark.integration
def test_cli_help():
	"""Verify help command works."""
	result = run_cli(["--help"])
	assert result.returncode == 0
	assert "Red Pill Protocol CLI" in result.stdout
