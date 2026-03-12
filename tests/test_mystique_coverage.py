from unittest.mock import MagicMock, patch

import pytest

from red_pill.utils.mystique import MystiqueEngine


def test_mystique_suggest_skin_all_strategies():
	engine = MystiqueEngine()

	with patch("red_pill.utils.mystique.get_current_sync_state") as mock_sync:
		# Test affinity
		mock_sync.return_value = {"mood": "cyan"}
		res = engine.suggest_skin(strategy="affinity", context="work")
		assert res["name"] == "matrix"

		# Test complementary (cyan -> yellow/orange logic)
		mock_sync.return_value = {"mood": "cyan"}
		res = engine.suggest_skin(strategy="complementary", context="work")
		assert res["name"] != "matrix"

		# Test contrast (blue -> red/orange)
		mock_sync.return_value = {"mood": "blue"}
		res = engine.suggest_skin(strategy="contrast", context="work")
		assert "name" in res

		# Test gray/yellow/emerald/gold/purple branches for full branch coverage
		for mood in ["gray", "yellow", "emerald", "gold", "purple", "orange", "red", "green", "pink"]:
			mock_sync.return_value = {"mood": mood}
			engine.suggest_skin(strategy="affinity")
			engine.suggest_skin(strategy="complementary")
			engine.suggest_skin(strategy="contrast")


def test_mystique_get_all_skins():
	with patch("builtins.open", side_effect=FileNotFoundError):
		with pytest.raises(FileNotFoundError):
			MystiqueEngine()

	with patch("builtins.open", MagicMock()):
		with patch("yaml.safe_load", return_value={}):
			engine = MystiqueEngine()
			assert engine.get_all_skins() == {}
