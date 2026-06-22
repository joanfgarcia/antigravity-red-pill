import os
import sys
import shutil
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as cfg
from red_pill.core import workspaces as ws_core
from red_pill.core.workspaces import Workspace
from red_pill.memory import MemoryManager
from red_pill.metabolism.memory_sync import (
	sync_workspace_memory,
	compact_workspace_memory,
	enable_workspace_memory,
	disable_workspace_memory,
	execute_preservation_hook,
)
from red_pill.swarm.bridges import ConversationResult


@pytest.fixture
def temp_workspace(tmp_path):
	"""Sets up a mock workspace directory."""
	ws_root = tmp_path / "my_project"
	ws_root.mkdir()
	return ws_root


@pytest.fixture
def mock_registry_file(tmp_path, monkeypatch):
	"""Sets up a temporary workspaces.yaml registry."""
	reg_file = tmp_path / "workspaces.yaml"
	reg_file.write_text(
		"version: 1\n"
		"agent_core: ~/Agent_Core\n"
		"workspaces: []\n",
		encoding="utf-8"
	)
	monkeypatch.setattr(ws_core, "registry_path", lambda: reg_file)
	return reg_file


class TestWorkspaceMemorySync:

	def test_enable_workspace_memory_scaffolds_folders(self, temp_workspace, mock_registry_file):
		# Register workspace
		ws_core.add_or_enable_workspace(str(temp_workspace), name="my_project")

		# Enable memory
		success = enable_workspace_memory("my_project")
		assert success is True

		# Verify scaffolding
		ws = ws_core.find_workspace("my_project")
		assert ws is not None
		assert ws.memory is True

		mem_path = ws.get_memory_path
		assert mem_path is not None
		assert mem_path.exists()
		assert (mem_path / "history" / "archived").exists()
		assert (mem_path / "MEMORY.md").exists()

	def test_disable_workspace_memory(self, temp_workspace, mock_registry_file):
		ws_core.add_or_enable_workspace(str(temp_workspace), name="my_project")
		enable_workspace_memory("my_project")
		
		success = disable_workspace_memory("my_project")
		assert success is True
		
		ws = ws_core.find_workspace("my_project")
		assert ws.memory is False

	def test_preservation_hook_isolated_execution(self, temp_workspace):
		# Create hooks script
		hook_dir = temp_workspace / ".red-pill"
		hook_dir.mkdir(parents=True)
		hook_file = hook_dir / "memory_hooks.py"
		hook_file.write_text(
			"def get_preservation_context(root):\n"
			"\treturn f'ARCH CONTEXT FOR {root}'\n",
			encoding="utf-8"
		)

		ws = Workspace(name="proj_hook", root=temp_workspace, memory=True)
		context = execute_preservation_hook(ws)
		assert context == f"ARCH CONTEXT FOR {str(temp_workspace)}"

		# Verify namespace isolation: load a second hook with different code
		temp_workspace2 = temp_workspace.parent / "my_project2"
		temp_workspace2.mkdir()
		hook_dir2 = temp_workspace2 / ".red-pill"
		hook_dir2.mkdir(parents=True)
		hook_file2 = hook_dir2 / "memory_hooks.py"
		hook_file2.write_text(
			"def get_preservation_context(root):\n"
			"\treturn f'DIFFERENT CONTEXT FOR {root}'\n",
			encoding="utf-8"
		)

		ws2 = Workspace(name="proj_hook_2", root=temp_workspace2, memory=True)
		context2 = execute_preservation_hook(ws2)
		assert context2 == f"DIFFERENT CONTEXT FOR {str(temp_workspace2)}"
		assert context != context2  # Verify no collision occurred

	def test_preservation_hook_fallback_agent_dir(self, temp_workspace):
		# Create hooks script in fallback .agent dir
		hook_dir = temp_workspace / ".agent"
		hook_dir.mkdir(parents=True)
		hook_file = hook_dir / "memory_hooks.py"
		hook_file.write_text(
			"def get_preservation_context(root):\n"
			"\treturn 'FALLBACK CONTEXT'\n",
			encoding="utf-8"
		)

		ws = Workspace(name="proj_hook_fallback", root=temp_workspace, memory=True)
		context = execute_preservation_hook(ws)
		assert context == "FALLBACK CONTEXT"

	def test_sync_projects_memories_chronologically(self, temp_workspace, mock_registry_file):
		ws_core.add_or_enable_workspace(str(temp_workspace), name="sync_test")
		enable_workspace_memory("sync_test")
		ws = ws_core.find_workspace("sync_test")

		# Mock Qdrant memory points
		mock_point1 = MagicMock()
		mock_point1.payload = {
			"content": "First Technical Decision",
			"created_at": 1000.0,
			"importance": 5.0,
			"emotion": "neutral",
			"workspace": "sync_test"
		}
		mock_point2 = MagicMock()
		mock_point2.payload = {
			"content": "Second Technical Decision",
			"created_at": 2000.0,
			"importance": 7.0,
			"emotion": "confidence",
			"workspace": "sync_test"
		}
		# Point for different workspace to check isolation
		mock_point3 = MagicMock()
		mock_point3.payload = {
			"content": "Other Project Decision",
			"created_at": 1500.0,
			"workspace": "other_project"
		}

		mock_mm = MagicMock()
		mock_mm.client.scroll.return_value = ([mock_point2, mock_point3, mock_point1], None)

		sync_workspace_memory(ws, mock_mm)

		decisions_file = ws.get_memory_path / "sync_test-decisions.md"
		assert decisions_file.exists()
		text = decisions_file.read_text(encoding="utf-8")
		assert "First Technical Decision" in text
		assert "Second Technical Decision" in text
		assert "Other Project Decision" not in text

		# Assert chronological ordering: First should appear before Second
		idx1 = text.find("First Technical Decision")
		idx2 = text.find("Second Technical Decision")
		assert idx1 < idx2

	@patch("red_pill.metabolism.memory_sync.create_bridge")
	@patch("red_pill.metabolism.memory_sync._resolve_prompt_path")
	def test_compaction_atomic_replace_and_backup(self, mock_resolve_path, mock_create_bridge, temp_workspace, mock_registry_file):
		ws_core.add_or_enable_workspace(str(temp_workspace), name="compact_test")
		enable_workspace_memory("compact_test")
		ws = ws_core.find_workspace("compact_test")

		# Mock compaction prompt seed resolution
		prompt_file = temp_workspace / "optimizer_prompt.txt"
		prompt_file.write_text("Optimize memory please.", encoding="utf-8")
		mock_resolve_path.return_value = prompt_file

		# Set up mock bridge
		mock_bridge = MagicMock()
		mock_create_bridge.return_value = mock_bridge
		
		# Initial MEMORY.md
		memory_file = ws.get_memory_path / "MEMORY.md"
		memory_file.write_text("Original MEMORY.md content", encoding="utf-8")
		
		# Create decisions file so compaction doesn't skip
		decisions_file = ws.get_memory_path / "compact_test-decisions.md"
		decisions_file.write_text("Decision log", encoding="utf-8")

		# Case 1: Compaction returns valid output
		mock_bridge.prompt.return_value = ConversationResult(
			conversation_id="test",
			response="Compacted MEMORY.md content"
		)

		mock_mm = MagicMock()
		compact_workspace_memory(ws, mock_mm)

		assert memory_file.read_text(encoding="utf-8") == "Compacted MEMORY.md content"
		# Verify backup
		assert (ws.get_memory_path / "MEMORY.md.bak").read_text(encoding="utf-8") == "Original MEMORY.md content"

		# Case 2: Compaction fails or returns empty (should preserve original)
		mock_bridge.prompt.return_value = ConversationResult(
			conversation_id="test2",
			response="",
			error="LLM failed"
		)
		compact_workspace_memory(ws, mock_mm)
		# Content should remain compacted from Case 1
		assert memory_file.read_text(encoding="utf-8") == "Compacted MEMORY.md content"


class TestMCPMemoryActions:

	@pytest.mark.asyncio
	@patch("red_pill.core.workspaces.find_workspace")
	async def test_mcp_read_write_list_workspace_memory(self, mock_find_workspace, temp_workspace):
		# Setup workspace mock
		ws_mem_path = temp_workspace / ".red-pill" / "memory"
		ws_mem_path.mkdir(parents=True)
		(ws_mem_path / "MEMORY.md").write_text("Memory content", encoding="utf-8")

		ws = Workspace(name="mcp_test", root=temp_workspace, memory=True)
		mock_find_workspace.return_value = ws

		from red_pill.mcp_server import handle_read_workspace_memory, handle_write_workspace_memory, handle_list_workspace_memory

		# Test List
		res_list = await handle_list_workspace_memory({"workspace": "mcp_test"})
		assert res_list[0].text == '["MEMORY.md"]'

		# Test Read
		res_read = await handle_read_workspace_memory({"workspace": "mcp_test", "filename": "MEMORY.md"})
		assert res_read[0].text == "Memory content"

		# Test Write
		res_write = await handle_write_workspace_memory({"workspace": "mcp_test", "filename": "test.txt", "content": "hello world"})
		assert "[OK]" in res_write[0].text
		assert (ws_mem_path / "test.txt").read_text(encoding="utf-8") == "hello world"

		# Test Directory Traversal Security Block
		res_block = await handle_read_workspace_memory({"workspace": "mcp_test", "filename": "../../../etc/passwd"})
		assert "[ERROR] Security block" in res_block[0].text
