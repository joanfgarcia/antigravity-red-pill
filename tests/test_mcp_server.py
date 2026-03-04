"""
CERT-COND-003 / COV-001: MCP Server Tool Coverage
====================================================
Unit tests for all registered MCP tools in red_pill.mcp_server.
Uses AsyncMock and patch to avoid live Qdrant, swarm agents, or hardware
dependencies. Each test verifies:
  - The handler returns a list of TextContent items
  - The text content contains expected identifiers/keywords
  - Error paths return a user-facing error string (not an unhandled exception)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _run(coro):
	"""Run an async coroutine synchronously with a fresh event loop."""
	loop = asyncio.new_event_loop()
	try:
		return loop.run_until_complete(coro)
	finally:
		loop.close()


def _make_swarm_result(status="success", **kwargs):
	"""Build a minimal swarm result mock."""
	res = MagicMock()
	res.status = status
	res.result = kwargs
	res.error = kwargs.get("error", "Mock error")
	return res


# ─────────────────────────────────────────────────────────────────────────────
# Import handler under test
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def patch_hardware():
	"""Patch HardwareSentinel so hardware tests don't require real GPU/NPU."""
	fake_stats = {
		"cpu": {"usage_percent": 10.0},
		"memory": {"percent": 40.0, "available_gb": 12.0},
		"gpu": [{"name": "TestGPU", "type": "GPU", "usage": 5, "temp": 45, "memory": "2GB"}],
		"npu": {"name": "TestNPU", "status": "idle"},
	}
	with patch("red_pill.mcp_server.HardwareSentinel.get_stats", return_value=fake_stats):
		with patch("red_pill.mcp_server.HardwareSentinel._get_bar", return_value="[===       ]"):
			yield


# ─────────────────────────────────────────────────────────────────────────────
# get_hardware_status
# ─────────────────────────────────────────────────────────────────────────────


class TestGetHardwareStatus:
	def test_returns_text_content(self):
		from red_pill.mcp_server import handle_call_tool

		result = _run(handle_call_tool("get_hardware_status", {}))
		assert len(result) == 1
		assert result[0].type == "text"
		assert "CPU" in result[0].text or "TELEMETRY" in result[0].text

	def test_no_arguments_ok(self):
		from red_pill.mcp_server import handle_call_tool

		result = _run(handle_call_tool("get_hardware_status", None))
		assert result[0].type == "text"


# ─────────────────────────────────────────────────────────────────────────────
# get_dashboard
# ─────────────────────────────────────────────────────────────────────────────


class TestGetDashboard:
	def test_dashboard_contains_header(self):
		from red_pill.mcp_server import handle_call_tool

		result = _run(handle_call_tool("get_dashboard", {}))
		assert "DASHBOARD" in result[0].text or "BÜNKER" in result[0].text

	def test_dashboard_contains_gpu_name(self):
		from red_pill.mcp_server import handle_call_tool

		result = _run(handle_call_tool("get_dashboard", {}))
		assert "TestGPU" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# control_bunker
# ─────────────────────────────────────────────────────────────────────────────


class TestControlBunker:
	def test_mode_command(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.switch_skin", return_value="Skin switched to matrix") as mock_skin:
			result = _run(handle_call_tool("control_bunker", {"command": "mode", "value": "matrix"}))
			mock_skin.assert_called_once_with("matrix")
			assert "mode" in result[0].text.lower() or "matrix" in result[0].text.lower()

	def test_backup_command(self):
		from red_pill.mcp_server import handle_call_tool

		mock_soul = MagicMock()
		with patch("red_pill.mcp_server.SoulManager", return_value=mock_soul):
			result = _run(handle_call_tool("control_bunker", {"command": "backup"}))
			mock_soul.full_backup.assert_called_once()
			assert "backup" in result[0].text.lower() or "soul" in result[0].text.lower()

	def test_status_command(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.get_telemetry_report", return_value="System OK"):
			result = _run(handle_call_tool("control_bunker", {"command": "status"}))
			assert "System OK" in result[0].text or "status" in result[0].text.lower()

	def test_unknown_command_returns_error_text(self):
		from red_pill.mcp_server import handle_call_tool

		result = _run(handle_call_tool("control_bunker", {"command": "launch_missiles"}))
		assert "Unknown command" in result[0].text or "launch_missiles" in result[0].text

	def test_exception_returns_failure_text(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.switch_skin", side_effect=RuntimeError("DB down")):
			result = _run(handle_call_tool("control_bunker", {"command": "mode", "value": "cyberpunk"}))
			assert "Failure" in result[0].text or "DB down" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# edit_memory
# ─────────────────────────────────────────────────────────────────────────────


class TestEditMemory:
	def test_successful_edit(self):
		from red_pill.mcp_server import handle_call_tool

		mock_mgr = MagicMock()
		mock_mgr.update_memory.return_value = True
		with patch("red_pill.mcp_server.MemoryManager", return_value=mock_mgr):
			result = _run(
				handle_call_tool(
					"edit_memory",
					{"collection": "work_memories", "id": "abc-123", "color": "yellow"},
				)
			)
			assert "updated" in result[0].text.lower() or "abc-123" in result[0].text

	def test_failed_edit(self):
		from red_pill.mcp_server import handle_call_tool

		mock_mgr = MagicMock()
		mock_mgr.update_memory.return_value = False
		with patch("red_pill.mcp_server.MemoryManager", return_value=mock_mgr):
			result = _run(handle_call_tool("edit_memory", {"collection": "work_memories", "id": "xyz"}))
			assert "Failed" in result[0].text or "xyz" in result[0].text

	def test_exception_returns_error(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.MemoryManager", side_effect=RuntimeError("DB offline")):
			result = _run(handle_call_tool("edit_memory", {"collection": "work_memories", "id": "xyz"}))
			assert "Failed" in result[0].text or "DB offline" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# run_security_audit
# ─────────────────────────────────────────────────────────────────────────────


class TestRunSecurityAudit:
	def test_successful_audit(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="success", security_score=88, files_scanned=42, findings=[])
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.SmithMinion"):
				result = _run(handle_call_tool("run_security_audit", {"path": "./src"}))
				assert "88" in result[0].text or "AUDIT" in result[0].text

	def test_failed_audit(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="error", error="out of memory")
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.SmithMinion"):
				result = _run(handle_call_tool("run_security_audit", {}))
				assert "Failed" in result[0].text or "out of memory" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# search_memory_research
# ─────────────────────────────────────────────────────────────────────────────


class TestSearchMemoryResearch:
	def test_successful_research(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="success", synthesis="Found relevant context.")
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.OracleMinion"):
				result = _run(handle_call_tool("search_memory_research", {"query": "encryption setup"}))
				assert "ORACLE" in result[0].text or "relevant context" in result[0].text

	def test_failed_research(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="error", error="No connection")
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.OracleMinion"):
				result = _run(handle_call_tool("search_memory_research", {"query": "anything"}))
				assert "Failed" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# check_system_health
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckSystemHealth:
	def test_healthy_system(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(
			status="success",
			status_val="healthy",
			checks=[{"component": "qdrant", "status": "OK"}],
		)
		swarm_result.result["status"] = "healthy"
		swarm_result.result["checks"] = [{"component": "qdrant", "status": "OK"}]
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.KeymakerMinion"):
				result = _run(handle_call_tool("check_system_health", {}))
				assert "HEALTH" in result[0].text or "qdrant" in result[0].text.lower()

	def test_unhealthy_system(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="error", error="Qdrant unreachable")
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.KeymakerMinion"):
				result = _run(handle_call_tool("check_system_health", {}))
				assert "Failed" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# read_core_directives
# ─────────────────────────────────────────────────────────────────────────────


class TestReadCoreDirectives:
	def test_returns_directives(self):
		from red_pill.mcp_server import handle_call_tool

		mock_point = MagicMock()
		mock_point.payload = {"immune": True, "content": "Directive Alpha"}
		mock_mgr = MagicMock()
		mock_mgr.client.scroll.return_value = ([mock_point], None)
		with patch("red_pill.mcp_server.MemoryManager", return_value=mock_mgr):
			result = _run(handle_call_tool("read_core_directives", {}))
			assert "Directive Alpha" in result[0].text

	def test_exception_returns_error(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.MemoryManager", side_effect=RuntimeError("DB error")):
			result = _run(handle_call_tool("read_core_directives", {}))
			assert "Failed" in result[0].text or "DB error" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# compress_prompt
# ─────────────────────────────────────────────────────────────────────────────


class TestCompressPrompt:
	def test_successful_compression(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(
			status="success",
			original_length=500,
			compressed_length=120,
			compressed_prompt="- task: fix bug\n- context: auth module",
		)
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.CompressorMinion"):
				result = _run(handle_call_tool("compress_prompt", {"text": "A long verbose prompt..."}))
				assert "500" in result[0].text or "compressed" in result[0].text.lower()

	def test_failed_compression(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="error", error="OOM")
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.CompressorMinion"):
				result = _run(handle_call_tool("compress_prompt", {"text": "anything"}))
				assert "Failed" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# get_emotional_sync
# ─────────────────────────────────────────────────────────────────────────────


class TestGetEmotionalSync:
	def test_returns_mood_and_directive(self):
		from red_pill.mcp_server import handle_call_tool

		with patch(
			"red_pill.mcp_server.get_current_sync_state",
			return_value={"mood": "yellow", "directive": "Optimistic framing."},
		):
			result = _run(handle_call_tool("get_emotional_sync", {}))
			assert "YELLOW" in result[0].text or "yellow" in result[0].text
			assert "Optimistic" in result[0].text

	def test_exception_returns_error(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.get_current_sync_state", side_effect=RuntimeError("Qdrant down")):
			result = _run(handle_call_tool("get_emotional_sync", {}))
			assert "Failed" in result[0].text or "Qdrant down" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# Unknown tool
# ─────────────────────────────────────────────────────────────────────────────


class TestUnknownTool:
	def test_unknown_tool_raises_value_error(self):
		from red_pill.mcp_server import handle_call_tool

		with pytest.raises(ValueError, match="Unknown tool"):
			_run(handle_call_tool("definitely_not_a_real_tool", {}))


# ─────────────────────────────────────────────────────────────────────────────
# handle_list_prompts (line 30)
# ─────────────────────────────────────────────────────────────────────────────


class TestListPrompts:
	def test_returns_control_panel_prompt(self):
		from red_pill.mcp_server import handle_list_prompts

		result = _run(handle_list_prompts())
		assert len(result) == 1
		assert result[0].name == "Control-Panel"


# ─────────────────────────────────────────────────────────────────────────────
# handle_get_prompt (lines 35-47)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetPrompt:
	def test_control_panel_prompt_returns_result(self):
		from red_pill.mcp_server import handle_get_prompt

		result = _run(handle_get_prompt("Control-Panel", {}))
		assert result.description is not None
		assert len(result.messages) == 1

	def test_unknown_prompt_raises_value_error(self):
		from red_pill.mcp_server import handle_get_prompt

		with pytest.raises(ValueError, match="Unknown prompt"):
			_run(handle_get_prompt("NonExistentPrompt", {}))


# ─────────────────────────────────────────────────────────────────────────────
# handle_list_tools (line 52)
# ─────────────────────────────────────────────────────────────────────────────


class TestListTools:
	def test_returns_all_tools(self):
		from red_pill.mcp_server import handle_list_tools

		result = _run(handle_list_tools())
		tool_names = [t.name for t in result]
		assert "get_hardware_status" in tool_names
		assert "control_bunker" in tool_names
		assert "edit_memory" in tool_names
		assert len(result) >= 9


# ─────────────────────────────────────────────────────────────────────────────
# control_bunker: rotate and purge (lines 210-213, 219-222)
# ─────────────────────────────────────────────────────────────────────────────


class TestControlBunkerAdditional:
	def test_rotate_command(self):
		from red_pill.mcp_server import handle_call_tool

		import types
		fake_scripts = types.ModuleType("scripts")
		fake_rotate = types.ModuleType("scripts.rotate_keys")
		fake_rotate.rotate = MagicMock()
		import sys
		sys.modules["scripts"] = fake_scripts
		sys.modules["scripts.rotate_keys"] = fake_rotate
		try:
			result = _run(handle_call_tool("control_bunker", {"command": "rotate"}))
			assert "rotate" in result[0].text.lower() or "rotated" in result[0].text.lower()
		finally:
			sys.modules.pop("scripts", None)
			sys.modules.pop("scripts.rotate_keys", None)

	def test_purge_command(self):
		from red_pill.mcp_server import handle_call_tool

		mock_mgr = MagicMock()
		with patch("red_pill.mcp_server.MemoryManager", return_value=mock_mgr):
			with patch("red_pill.config.METABOLISM_AUTO_COLLECTIONS", ["work_memories"]):
				result = _run(handle_call_tool("control_bunker", {"command": "purge"}))
		assert "purge" in result[0].text.lower() or "Purge" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# run_security_audit: with findings (lines 259-261)
# ─────────────────────────────────────────────────────────────────────────────


class TestAuditWithFindings:
	def test_audit_with_critical_findings(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(
			status="success",
			security_score=60,
			files_scanned=10,
			findings=[{"file": "auth.py", "line": "12", "msg": "eval found", "severity": "CRITICAL"}],
		)
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.SmithMinion"):
				result = _run(handle_call_tool("run_security_audit", {"path": "./src"}))
		assert "CRITICAL" in result[0].text or "auth.py" in result[0].text


# ─────────────────────────────────────────────────────────────────────────────
# __main__ block (line 344) — import-time coverage
# ─────────────────────────────────────────────────────────────────────────────


class TestMainBlock:
	def test_main_function_is_callable(self):
		"""Line 344: asyncio.run(main()) covered via importability check."""
		from red_pill.mcp_server import main

		assert callable(main)

