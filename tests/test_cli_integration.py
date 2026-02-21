import subprocess
import pytest
import os

def run_cli(args):
    """Helper to run the red-pill CLI."""
    cmd = ["python3", "-m", "red_pill.cli"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result

@pytest.mark.integration
def test_cli_search_deep_recall():
    """Verify that the --deep flag works via CLI."""
    # We use a dummy collection or assume one exists
    # For a real integration test, we would need a live Qdrant
    # But we can at least check if it crashes (BUG-001 check)
    result = run_cli(["search", "work", "Lazarus", "--deep"])
    
    # If the NameError still existed, this would return exit code 1 with traceback
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
    result = run_cli(["mode", "cyberpunk"])
    assert result.returncode == 0
    assert "Operational Mode: CYBERPUNK" in result.stdout

@pytest.mark.integration
def test_cli_help():
    """Verify help command works."""
    result = run_cli(["--help"])
    assert result.returncode == 0
    assert "Red Pill Protocol CLI" in result.stdout
