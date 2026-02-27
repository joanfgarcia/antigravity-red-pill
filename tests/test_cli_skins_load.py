import os

import pytest
import yaml


def test_lore_skins_yaml_load_all():
	"""TCG-003: Asserts all 12 skins load from yaml, have a name, and a valid chroma value."""
	data_path = os.path.join(os.path.dirname(__file__), "..", "src", "red_pill", "data", "lore_skins.yaml")
	assert os.path.exists(data_path), "lore_skins.yaml missing"

	with open(data_path, "r") as f:
		raw_skins = yaml.safe_load(f).get("modes", {})

	assert len(raw_skins) >= 12, f"Expected at least 12 skins, found {len(raw_skins)}"

	valid_colors = ["orange", "yellow", "purple", "cyan", "blue", "gray", "red", "green", "emerald", "black"]

	for skin_name, skin_data in raw_skins.items():
		assert "chroma" in skin_data, f"Skin '{skin_name}' missing chroma color"
		assert skin_data["chroma"] in valid_colors, f"Skin '{skin_name}' has invalid chroma '{skin_data['chroma']}'"


@pytest.mark.parametrize(
	"skin", ["matrix", "cyberpunk", "760", "dune", "40k", "gits", "bladerunner", "her", "exmachina", "terminator", "2001", "creator"]
)
def test_cli_switch_skin_behavior(skin):
	"""Test that CLI switch_skin function correctly handles all 12 preset skins."""
	# This function also tries to persist the skin in Qdrant (directive_memories).
	# We should mock MemoryManager if we only want to test the loading part
	from unittest.mock import patch

	with patch("red_pill.cli.MemoryManager") as mock_mgr:
		from red_pill.cli import switch_skin

		report = switch_skin(skin)
		assert skin.upper() in report
		assert "Operational Mode" in report
		assert mock_mgr.return_value.add_memory.called
