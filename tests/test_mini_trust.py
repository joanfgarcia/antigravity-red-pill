"""Trust boundaries and hardening for the mini harness."""

import sys

import pytest

from red_pill.mini.bridge import MiniLocalBridge
from red_pill.mini.tools import ToolError, WorkspaceTools
from red_pill.mini.trust import (
	MiniTrustError,
	normalize_local_mini_payload,
	validate_db_path,
	validate_loopback_url,
	validate_socket_path,
	validate_workspace,
)


def test_workspace_outside_roots_is_rejected(tmp_path):
	with pytest.raises(MiniTrustError):
		validate_workspace("/etc")
	assert validate_workspace(str(tmp_path)) == str(tmp_path.resolve())


def test_db_socket_and_flm_are_bounded(tmp_path):
	assert validate_db_path(str(tmp_path / "session.db"))
	with pytest.raises(MiniTrustError):
		validate_db_path("/etc/passwd")
	assert validate_socket_path(str(tmp_path / "forge.sock"))
	with pytest.raises(MiniTrustError):
		validate_socket_path("/etc/passwd")
	assert validate_loopback_url("http://127.0.0.1:52625")
	with pytest.raises(MiniTrustError):
		validate_loopback_url("http://169.254.169.254/latest/meta-data")


def test_bridge_rejects_home_workspace(tmp_path):
	with pytest.raises(MiniTrustError):
		MiniLocalBridge(profile="forge", workspace="/etc")


def test_payload_cannot_choose_another_soul_or_transport(tmp_path):
	payload = {
		"profile": "loom-tools",
		"continuity_id": "other-soul",
		"mission_id": "mission:other",
		"workspace": str(tmp_path),
		"db_path": str(tmp_path / "other.db"),
		"gpu_socket": "/tmp/other.sock",
		"flm_url": "http://169.254.169.254",
	}
	with pytest.raises(MiniTrustError):
		normalize_local_mini_payload(payload, {"continuity_id": "mine", "mission_id": "mission:mine"})
	out = normalize_local_mini_payload(
		{**payload, "continuity_id": "mine", "mission_id": "mission:mine"},
		{"continuity_id": "mine", "mission_id": "mission:mine"},
	)
	assert out["continuity_id"] == "mine"
	assert "db_path" not in out and "gpu_socket" not in out and "flm_url" not in out


def test_symlink_escape_is_rejected(tmp_path):
	workspace = tmp_path / "ws"
	workspace.mkdir()
	(workspace / "link").symlink_to("/etc/passwd")
	tools = WorkspaceTools(str(workspace))
	with pytest.raises(ToolError):
		tools.read_file("link")


def test_run_tests_scrubs_env_and_secrets(tmp_path, monkeypatch):
	monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-0123456789abcdef0123456789abcdef")
	tools = WorkspaceTools(
		str(tmp_path),
		tests_cmd=[sys.executable, "-c", "import os; print(os.getenv('OPENROUTER_API_KEY')); print('sk-or-v1-0123456789abcdef0123456789abcdef')"],
	)
	result = tools.run_tests()
	assert result["ok"] is True
	assert "DEADBEEF" not in result["output"]
	assert "0123456789abcdef0123456789abcdef" not in result["output"]
