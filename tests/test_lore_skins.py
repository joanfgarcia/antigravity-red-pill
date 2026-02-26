"""
TCG-003: Lore Skin Configuration Integrity
==========================================
Validates that src/red_pill/data/lore_skins.yaml contains all required fields 
for every defined skin (mode) and that chroma values map to the ValidColor spectrum.
"""

import os
from unittest.mock import MagicMock, patch

import yaml
from red_pill.schemas import ValidColor


def test_lore_skins_yaml_integrity():
	"""Ensures every skin in lore_skins.yaml is valid and fully defined."""
	data_path = os.path.join(os.path.dirname(__file__), "..", "src", "red_pill", "data", "lore_skins.yaml")
	assert os.path.exists(data_path), f"Lore skins YAML not found at {data_path}"

	with open(data_path, "r") as f:
		data = yaml.safe_load(f)

	assert "modes" in data, "YAML missing 'modes' root key"
	modes = data["modes"]

	# We expect at least the CORE skins + expanded ones (12+ as per audit report)
	assert len(modes) >= 12, f"Expected at least 12 skins, found {len(modes)}"

	required_keys = {
		"network_protection",
		"data_cores",
		"memory_environment",
		"assistant",
		"operator",
		"chroma",
	}

	# Get set of valid colors from the pydantic schema for validation
	from typing import get_args
	valid_colors = set(get_args(ValidColor))

	for name, skin in modes.items():
		# 1. Check all required fields exist
		for key in required_keys:
			assert key in skin, f"Skin '{name}' is missing required key: {key}"
			assert skin[key], f"Skin '{name}' has empty value for: {key}"

		# 2. Check chroma is a valid recognized color for the UI/Bünker
		assert skin["chroma"] in valid_colors, (
			f"Skin '{name}' uses invalid chroma '{skin['chroma']}'. "
			f"Must be one of: {valid_colors}"
		)

		# 3. Optional: Check personality length if present
		if "personality" in skin:
			assert len(skin["personality"]) > 20, f"Skin '{name}' personality blurb is too short"


def test_skin_switching_logic_integration():
	"""Verify the switch_skin function in cli.py loads the YAML correctly (logic check)."""
	from red_pill.cli import switch_skin

	# Mock MemoryManager to avoid Qdrant calls during skin logic validation
	with patch("red_pill.cli.MemoryManager") as mock_mgr_cls:
		mock_mgr = MagicMock()
		mock_mgr_cls.return_value = mock_mgr

		# Test known good skin
		result = switch_skin("matrix")
		assert "OPERATIONAL MODE: MATRIX" in result.upper()
		assert "[OK] Skin 'matrix' synchronized" in result

		# Check call parameters to MemoryManager
		mock_mgr.add_memory.assert_called_once()
		call_args = mock_mgr.add_memory.call_args[1]
		assert call_args["collection"] == "directive_memories"
		assert call_args["metadata"]["skin_name"] == "matrix"
		assert call_args["color"] == "cyan"  # matrix chroma

		# Test invalid skin
		result = switch_skin("not_a_real_skin_123456")
		assert "Invalid mode" in result
		assert "matrix" in result  # Should list valid options
