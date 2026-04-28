from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from red_pill.mcp_server import (
	handle_configure_neuro_agentic_tuning,
	handle_control_bunker,
	handle_list_all_skins,
	handle_memorize_interaction,
	handle_mystique_suggest_skin,
)
from red_pill.mcp_server import main as mcp_main
from red_pill.utils.mystique import MystiqueEngine


@pytest.mark.asyncio
async def test_mcp_control_bunker_export():
	with patch("red_pill.mcp_server.SoulManager") as mock_soul:
		mock_soul.return_value.export_soul = AsyncMock(return_value=True)
		res = await handle_control_bunker({"command": "export"})
		assert "Soul Kit exported" in res[0].text
		assert mock_soul.return_value.export_soul.called


@pytest.mark.asyncio
async def test_mcp_memorize_interaction_fallback():
	mock_queue = MagicMock()
	with patch("red_pill.core.queue_manager.MemoryQueueManager", return_value=mock_queue):
		res = await handle_memorize_interaction({"prompt": "Valid test prompt long enough to bypass", "response": "Valid log enough to bypass ping."})
	assert "Engram queue registration initiated" in res[0].text
	mock_queue.enqueue_memory.assert_called_once()


@pytest.mark.asyncio
async def test_mcp_configure_sna_tuning():
	with patch("scripts.update_env.update_env") as mock_update:
		res = await handle_configure_neuro_agentic_tuning({"log_noise_filter": "High"})
		assert "Neuro-Agentic Tuning Optimized" in res[0].text
		assert mock_update.called


@pytest.mark.asyncio
async def test_mcp_list_all_skins():
	res = await handle_list_all_skins({})
	assert "BÜNKER LORE SKIN CATALOG" in res[0].text
	assert "MATRIX" in res[0].text


@pytest.mark.asyncio
async def test_mcp_suggest_skin_logic():
	res = await handle_mystique_suggest_skin({"strategy": "contrast", "context": "work"})
	assert "MYSTIQUE SUGGESTION" in res[0].text


@pytest.mark.asyncio
async def test_mcp_main_coverage():
	with patch("red_pill.mcp_server.stdio_server") as mock_stdio:
		mock_stdio.return_value.__aenter__.return_value = (MagicMock(), MagicMock())
		with patch("red_pill.mcp_server.server.run") as mock_run:
			await mcp_main()
			assert mock_run.called


def test_mystique_not_candidates_fallback():
	engine = MystiqueEngine()
	engine.skins = {}
	with patch("red_pill.utils.mystique.get_current_sync_state", return_value={"mood": "cyan"}):
		res = engine.suggest_skin()
		assert res["name"] == "enterprise_core"
