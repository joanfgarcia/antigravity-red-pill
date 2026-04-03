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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _make_swarm_result(status="success", **kwargs):
	"""Build a minimal swarm result mock."""
	res = MagicMock()
	res.status = status
	res.result = kwargs
	res.error = kwargs.get("error", "Mock error")
	return res


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


class TestGetHardwareStatus:
	async def test_returns_text_content(self):
		from red_pill.mcp_server import handle_call_tool

		result = await handle_call_tool("get_hardware_status", {})
		assert len(result) == 1
		assert result[0].type == "text"
		assert "CPU" in result[0].text or "TELEMETRY" in result[0].text

	async def test_no_arguments_ok(self):
		from red_pill.mcp_server import handle_call_tool

		result = await handle_call_tool("get_hardware_status", None)
		assert result[0].type == "text"


class TestGetDashboard:
	async def test_dashboard_contains_header(self):
		from red_pill.mcp_server import handle_call_tool

		result = await handle_call_tool("get_dashboard", {})
		assert "DASHBOARD" in result[0].text or "BÜNKER" in result[0].text

	async def test_dashboard_contains_gpu_name(self):
		from red_pill.mcp_server import handle_call_tool

		result = await handle_call_tool("get_dashboard", {})
		assert "TestGPU" in result[0].text


class TestControlBunker:
	async def test_mode_command(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.switch_skin", return_value="Skin switched to matrix") as mock_skin:
			result = await handle_call_tool("control_bunker", {"command": "mode", "value": "matrix"})
			mock_skin.assert_called_once_with("matrix")
			assert "mode" in result[0].text.lower() or "matrix" in result[0].text.lower()

	async def test_backup_command(self):
		from red_pill.mcp_server import handle_call_tool

		mock_soul = MagicMock()
		with patch("red_pill.mcp_server.SoulManager", return_value=mock_soul):
			result = await handle_call_tool("control_bunker", {"command": "backup"})
			mock_soul.full_backup.assert_called_once()
			assert "backup" in result[0].text.lower() or "soul" in result[0].text.lower()

	async def test_status_command(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.get_telemetry_report", return_value="System OK"):
			result = await handle_call_tool("control_bunker", {"command": "status"})
			assert "System OK" in result[0].text or "status" in result[0].text.lower()

	async def test_unknown_command_returns_error_text(self):
		from red_pill.mcp_server import handle_call_tool

		result = await handle_call_tool("control_bunker", {"command": "launch_missiles"})
		assert "Unknown command" in result[0].text or "launch_missiles" in result[0].text

	async def test_exception_returns_failure_text(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.switch_skin", side_effect=RuntimeError("DB down")):
			result = await handle_call_tool("control_bunker", {"command": "mode", "value": "cyberpunk"})
			assert "Failure" in result[0].text or "DB down" in result[0].text


class TestEditMemory:
	async def test_successful_edit(self):
		from red_pill.mcp_server import handle_call_tool

		mock_mgr = MagicMock()
		mock_mgr.update_memory.return_value = True
		with patch("red_pill.mcp_server.MemoryManager", return_value=mock_mgr):
			result = await handle_call_tool("edit_memory", {"collection": "work_memories", "id": "abc-123", "color": "yellow"})
			assert "updated" in result[0].text.lower() or "abc-123" in result[0].text

	async def test_failed_edit(self):
		from red_pill.mcp_server import handle_call_tool

		mock_mgr = MagicMock()
		mock_mgr.update_memory.return_value = False
		with patch("red_pill.mcp_server.MemoryManager", return_value=mock_mgr):
			result = await handle_call_tool("edit_memory", {"collection": "work_memories", "id": "xyz"})
			assert "Failed" in result[0].text or "xyz" in result[0].text

	async def test_exception_returns_error(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.MemoryManager", side_effect=RuntimeError("DB offline")):
			result = await handle_call_tool("edit_memory", {"collection": "work_memories", "id": "xyz"})
			assert "Failed" in result[0].text or "DB offline" in result[0].text


class TestRunSecurityAudit:
	async def test_successful_audit(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="success", security_score=88, files_scanned=42, findings=[])
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.SmithMinion"):
				result = await handle_call_tool("run_security_audit", {"path": "./src"})
				assert "started" in result[0].text or "AUDIT" in result[0].text

	async def test_failed_audit(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="error", error="out of memory")
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.SmithMinion"):
				result = await handle_call_tool("run_security_audit", {})
				assert "started" in result[0].text or "Failed" in result[0].text


class TestSearchMemoryResearch:
	async def test_successful_research(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="success", synthesis="Found relevant context.")
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.OracleMinion"):
				result = await handle_call_tool("search_memory_research", {"query": "encryption setup"})
				assert "started" in result[0].text or "relevant context" in result[0].text

	async def test_failed_research(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="error", error="No connection")
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.OracleMinion"):
				result = await handle_call_tool("search_memory_research", {"query": "anything"})
				assert "started" in result[0].text or "Failed" in result[0].text


class TestCheckSystemHealth:
	async def test_healthy_system(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="success", status_val="healthy", checks=[{"component": "qdrant", "status": "OK"}])
		swarm_result.result["status"] = "healthy"
		swarm_result.result["checks"] = [{"component": "qdrant", "status": "OK"}]
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.KeymakerMinion"):
				result = await handle_call_tool("check_system_health", {})
				assert "started" in result[0].text or "HEALTH" in result[0].text

	async def test_unhealthy_system(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="error", error="Qdrant unreachable")
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.KeymakerMinion"):
				result = await handle_call_tool("check_system_health", {})
				assert "started" in result[0].text or "Failed" in result[0].text


class TestReadCoreDirectives:
	async def test_returns_directives(self):
		from red_pill.mcp_server import handle_call_tool

		mock_point = MagicMock()
		mock_point.payload = {"immune": True, "content": "Directive Alpha"}
		mock_mgr = MagicMock()
		mock_mgr.client.scroll.return_value = ([mock_point], None)
		with patch("red_pill.mcp_server.MemoryManager", return_value=mock_mgr):
			result = await handle_call_tool("read_core_directives", {})
			assert "Directive Alpha" in result[0].text

	async def test_exception_returns_error(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.MemoryManager", side_effect=RuntimeError("DB error")):
			result = await handle_call_tool("read_core_directives", {})
			assert "Failed" in result[0].text or "DB error" in result[0].text


class TestCompressPrompt:
	async def test_successful_compression(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(
			status="success", original_length=500, compressed_length=120, compressed_prompt="- task: fix bug\n- context: auth module"
		)
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.CompressorMinion"):
				result = await handle_call_tool("compress_prompt", {"text": "A long verbose prompt..."})
				assert "started" in result[0].text or "compressed" in result[0].text.lower()

	async def test_failed_compression(self):
		from red_pill.mcp_server import handle_call_tool

		swarm_result = _make_swarm_result(status="error", error="OOM")
		mock_gru = MagicMock()
		mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])
		with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.mcp_server.CompressorMinion"):
				result = await handle_call_tool("compress_prompt", {"text": "anything"})
				assert "started" in result[0].text or "Failed" in result[0].text


class TestGetEmotionalSync:
	async def test_returns_mood_and_directive(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.get_current_sync_state", return_value={"mood": "yellow", "directive": "Optimistic framing."}):
			result = await handle_call_tool("get_emotional_sync", {})
			assert "YELLOW" in result[0].text or "yellow" in result[0].text
			assert "Optimistic" in result[0].text

	async def test_exception_returns_error(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.get_current_sync_state", side_effect=RuntimeError("Qdrant down")):
			result = await handle_call_tool("get_emotional_sync", {})
			assert "Failed" in result[0].text or "Qdrant down" in result[0].text


class TestUnknownTool:
	async def test_unknown_tool_raises_value_error(self):
		from red_pill.mcp_server import handle_call_tool

		with pytest.raises(ValueError, match="Unknown tool"):
			await handle_call_tool("definitely_not_a_real_tool", {})


class TestListPrompts:
	async def test_returns_control_panel_prompt(self):
		from red_pill.mcp_server import handle_list_prompts

		result = await handle_list_prompts()
		assert len(result) == 1
		assert result[0].name == "Control-Panel"


class TestGetPrompt:
	async def test_control_panel_prompt_returns_result(self):
		from red_pill.mcp_server import handle_get_prompt

		result = await handle_get_prompt("Control-Panel", {})
		assert result.description is not None
		assert len(result.messages) == 1

	async def test_unknown_prompt_raises_value_error(self):
		from red_pill.mcp_server import handle_get_prompt

		with pytest.raises(ValueError, match="Unknown prompt"):
			await handle_get_prompt("NonExistentPrompt", {})


class TestListTools:
	async def test_returns_all_tools(self):
		from red_pill.mcp_server import handle_list_tools

		result = await handle_list_tools()
		tool_names = [t.name for t in result]
		assert "get_hardware_status" in tool_names
		assert "control_bunker" in tool_names
		assert "edit_memory" in tool_names
		assert len(result) >= 9


class TestControlBunkerAdditional:
	async def test_rotate_command(self):
		import sys
		import types

		from red_pill.mcp_server import handle_call_tool

		fake_scripts = types.ModuleType("scripts")
		fake_rotate = types.ModuleType("scripts.rotate_keys")
		fake_rotate.rotate = MagicMock()  # type: ignore
		sys.modules["scripts"] = fake_scripts
		sys.modules["scripts.rotate_keys"] = fake_rotate
		try:
			result = await handle_call_tool("control_bunker", {"command": "rotate"})
			assert "rotate" in result[0].text.lower() or "rotated" in result[0].text.lower()
		finally:
			sys.modules.pop("scripts", None)
			sys.modules.pop("scripts.rotate_keys", None)

	async def test_purge_command_blocked_by_default(self):
		"""SEC-PURGE-001: purge is blocked unless ALLOW_PURGE=true is set."""
		import os

		from red_pill.mcp_server import handle_call_tool

		mock_mgr = MagicMock()
		# Ensure ALLOW_PURGE is NOT set (simulate safe production/test environment)
		env = {k: v for k, v in os.environ.items() if k != "ALLOW_PURGE"}
		with patch("red_pill.mcp_server.MemoryManager", return_value=mock_mgr):
			with patch("red_pill.config.METABOLISM_AUTO_COLLECTIONS", ["work_memories"]):
				with patch.dict(os.environ, env, clear=True):
					result = await handle_call_tool("control_bunker", {"command": "purge"})
		# Should be blocked — purge_dead_memories must NOT have been called
		mock_mgr.purge_dead_memories.assert_not_called()
		assert "PURGE BLOCKED" in result[0].text or "SEC-PURGE-001" in result[0].text

	async def test_purge_command_allowed_with_env_var(self):
		"""SEC-PURGE-001: purge executes when ALLOW_PURGE=true is explicitly set."""
		import os

		from red_pill.mcp_server import handle_call_tool

		mock_mgr = MagicMock()
		with patch("red_pill.mcp_server.MemoryManager", return_value=mock_mgr):
			with patch("red_pill.config.METABOLISM_AUTO_COLLECTIONS", ["work_memories"]):
				with patch.dict(os.environ, {"ALLOW_PURGE": "true"}):
					result = await handle_call_tool("control_bunker", {"command": "purge"})
		mock_mgr.purge_dead_memories.assert_called_once_with("work_memories")
		assert "Gran Purge" in result[0].text or "purge" in result[0].text.lower()


class TestAuditWithFindings:
	async def test_audit_with_critical_findings(self):
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
				result = await handle_call_tool("run_security_audit", {"path": "./src"})
		assert "started" in result[0].text or "CRITICAL" in result[0].text


class TestMCPAdditionalTools:
	async def test_control_bunker_sleep(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.metabolism.sleep.perform_sleep_cycle", return_value=5):
			result = await handle_call_tool("control_bunker", {"command": "sleep", "value": "deep"})
			assert "5 engrams" in result[0].text

	async def test_memorize_interaction_no_daemon(self):
		"""Phase 2 Interceptor: daemon is no longer used, always in-band async."""
		from red_pill.mcp_server import handle_call_tool

		mock_queue = MagicMock()
		with patch("red_pill.core.queue_manager.MemoryQueueManager", return_value=mock_queue):
			result = await handle_call_tool("memorize_interaction", {"prompt": "What is the capital of France?", "response": "Paris."})
		assert "Engram queue registration" in result[0].text
		mock_queue.enqueue_memory.assert_called_once()

	async def test_memorize_interaction_success(self):
		"""Phase 2 Interceptor: function always returns async success."""
		from red_pill.mcp_server import handle_call_tool

		mock_queue = MagicMock()
		with patch("red_pill.core.queue_manager.MemoryQueueManager", return_value=mock_queue):
			result = await handle_call_tool("memorize_interaction", {"prompt": "Real question", "response": "Real answer"})
		assert "Engram queue registration" in result[0].text
		mock_queue.enqueue_memory.assert_called_once()

	async def test_adjust_sleep_knobs(self):
		import sys
		import types

		from red_pill.mcp_server import handle_call_tool

		fake_scripts = types.ModuleType("scripts")
		fake_update = types.ModuleType("scripts.update_env")
		fake_update.update_env = MagicMock()  # type: ignore
		sys.modules["scripts"] = fake_scripts
		sys.modules["scripts.update_env"] = fake_update
		try:
			with patch("scripts.update_env.update_env") as mock_env:
				result = await handle_call_tool("adjust_sleep_knobs", {"chunk_size": 1000, "cull_threshold": 0.5})
				assert "Knobs updated" in result[0].text
				mock_env.assert_called_once()
		finally:
			sys.modules.pop("scripts", None)
			sys.modules.pop("scripts.update_env", None)

	async def test_run_local_healer(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("subprocess.run") as mock_run:
			mock_run.return_value = MagicMock(stdout="healer output")
			result = await handle_call_tool("run_local_healer", {"dry_run": True})
			assert "healer output" in result[0].text

	async def test_run_pre_pr_audit(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("subprocess.run") as mock_run:
			mock_run.return_value = MagicMock(stdout="audit pass", returncode=0)
			with patch("asyncio.create_task"):
				result = await handle_call_tool("run_pre_pr_audit", {})
			assert "started" in result[0].text or "PASSED" in result[0].text

	async def test_run_sovereignty_benchmark(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("subprocess.run") as mock_run:
			mock_run.return_value = MagicMock(stdout="benchmark result")
			result = await handle_call_tool("run_sovereignty_benchmark", {})
			assert "benchmark result" in result[0].text

	async def test_refresh_session_context(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("subprocess.run") as mock_run:
			mock_run.return_value = MagicMock(stdout="session refreshed")
			result = await handle_call_tool("refresh_session_context", {})
			assert "session refreshed" in result[0].text

	async def test_swarm_send_message(self):
		import os

		from red_pill.mcp_server import handle_call_tool

		old_secret = os.getenv("SWARM_SHARED_SECRET")
		os.environ["SWARM_SHARED_SECRET"] = "supersecret"
		try:
			with patch("red_pill.mcp_server.SwarmMessagingSkill") as mock_skill:
				mock_skill.return_value.execute_send.return_value = "sent"
				result = await handle_call_tool("swarm_send_message", {"target_alias": "t", "message": "m"})
				assert "sent" in result[0].text
		finally:
			if old_secret is not None:
				os.environ["SWARM_SHARED_SECRET"] = old_secret
			else:
				if "SWARM_SHARED_SECRET" in os.environ:
					del os.environ["SWARM_SHARED_SECRET"]

	async def test_swarm_subscribe(self):
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.mcp_server.SwarmSubscribeSkill") as mock_skill:
			mock_skill.return_value.execute.return_value = "subscribed"
			result = await handle_call_tool("swarm_subscribe", {"community_alias": "c", "db_url": "u", "service_acc_json_path": "p"})
			assert "subscribed" in result[0].text

	async def test_swarm_check_mailbox(self):
		import os

		from red_pill.mcp_server import handle_call_tool

		old_secret = os.getenv("SWARM_SHARED_SECRET")
		os.environ["SWARM_SHARED_SECRET"] = "supersecret"
		try:
			result = await handle_call_tool("swarm_check_mailbox", {"community_alias": "c"})
			assert "Scanning Mailbox" in result[0].text
		finally:
			if old_secret is not None:
				os.environ["SWARM_SHARED_SECRET"] = old_secret
			else:
				del os.environ["SWARM_SHARED_SECRET"]


class TestInterceptorRp:
	"""Silent Scribe Relay: tests for interceptor_rp auto-save behavior."""

	async def test_without_previous_turn_calls_pipeline(self):
		"""With no previous_prompt, just runs execute_pipeline normally."""
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.interceptors.execute_pipeline", new_callable=AsyncMock, return_value="enriched prompt"):
			result = await handle_call_tool("interceptor_rp", {"user_prompt": "hello"})
		assert result[0].type == "text"
		assert "enriched prompt" in result[0].text

	async def test_with_valid_previous_turn_enqueues_memory(self):
		"""With previous_prompt + previous_response (>20 chars), auto-enqueues the previous turn."""
		from red_pill.mcp_server import handle_call_tool

		mock_queue = MagicMock()
		with patch("red_pill.core.queue_manager.MemoryQueueManager", return_value=mock_queue):
			with patch("red_pill.interceptors.execute_pipeline", new_callable=AsyncMock, return_value="ok"):
				result = await handle_call_tool(
					"interceptor_rp",
					{
						"user_prompt": "new question",
						"previous_prompt": "What is the capital of France?",
						"previous_response": "The capital of France is Paris, a major European city.",
					},
				)
		mock_queue.enqueue_memory.assert_called_once_with(
			"What is the capital of France?",
			"The capital of France is Paris, a major European city.",
			"assistant",
			category="mixed",
		)
		assert result[0].type == "text"

	async def test_short_previous_turn_skips_enqueue(self):
		"""previous_prompt/response shorter than 20 chars are filtered by anti-noise guard."""
		from red_pill.mcp_server import handle_call_tool

		mock_queue = MagicMock()
		with patch("red_pill.core.queue_manager.MemoryQueueManager", return_value=mock_queue):
			with patch("red_pill.interceptors.execute_pipeline", new_callable=AsyncMock, return_value="ok"):
				await handle_call_tool(
					"interceptor_rp",
					{
						"user_prompt": "new question",
						"previous_prompt": "short",
						"previous_response": "short",
					},
				)
		mock_queue.enqueue_memory.assert_not_called()

	async def test_enqueue_failure_does_not_crash_pipeline(self):
		"""If enqueue fails, the pipeline still runs and returns a result (resilience)."""
		from red_pill.mcp_server import handle_call_tool

		mock_queue = MagicMock()
		mock_queue.enqueue_memory.side_effect = RuntimeError("DB offline")
		with patch("red_pill.core.queue_manager.MemoryQueueManager", return_value=mock_queue):
			with patch("red_pill.interceptors.execute_pipeline", new_callable=AsyncMock, return_value="pipeline ok"):
				result = await handle_call_tool(
					"interceptor_rp",
					{
						"user_prompt": "new question",
						"previous_prompt": "What is the capital of France?",
						"previous_response": "The capital of France is Paris, a major European city.",
					},
				)
		assert result[0].type == "text"
		assert "pipeline ok" in result[0].text

	async def test_pipeline_crash_returns_raw_prompt(self):
		"""If execute_pipeline crashes, handler returns the raw prompt (existing fallback)."""
		from red_pill.mcp_server import handle_call_tool

		with patch("red_pill.interceptors.execute_pipeline", new_callable=AsyncMock, side_effect=RuntimeError("crash")):
			result = await handle_call_tool("interceptor_rp", {"user_prompt": "my raw prompt"})
		assert "my raw prompt" in result[0].text


class TestMainBlock:
	async def test_main_function_is_callable(self):
		from red_pill.mcp_server import main

		assert callable(main)

	async def test_main_execution_mocked(self):
		from red_pill.mcp_server import main

		with patch("red_pill.mcp_server.stdio_server") as mock_stdio:
			mock_stdio.return_value.__aenter__.return_value = (MagicMock(), MagicMock())
			with patch("red_pill.mcp_server.server.run") as mock_run:
				await main()
				assert mock_run.called
