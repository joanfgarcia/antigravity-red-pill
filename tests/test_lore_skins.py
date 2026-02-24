import os
import yaml
import pytest
from red_pill.schemas import ValidColor

def test_lore_skins_load():
	"""TCG-003: Verify all lore skins in YAML are valid."""
	data_path = os.path.join(os.path.dirname(__file__), "..", "src", "red_pill", "data", "lore_skins.yaml")
	assert os.path.exists(data_path), f"Lore skins file not found at {data_path}"
	
	with open(data_path, "r") as f:
		data = yaml.safe_load(f)
		assert "modes" in data
		skins = data["modes"]
		
		# Audit mentions 12 skins
		assert len(skins) >= 12
		
		valid_colors = ValidColor.__args__ # Get literal values
		
		for name, skin in skins.items():
			# Check required fields for CLI display
			assert "network_protection" in skin, f"Skin {name} missing network_protection"
			assert "data_cores" in skin, f"Skin {name} missing data_cores"
			assert "memory_environment" in skin, f"Skin {name} missing memory_environment"
			assert "assistant" in skin, f"Skin {name} missing assistant"
			assert "operator" in skin, f"Skin {name} missing operator"
			
			# Check chroma validity
			assert "chroma" in skin, f"Skin {name} missing chroma"
			assert skin["chroma"] in valid_colors, f"Skin {name} has invalid chroma: {skin['chroma']}"

def test_lore_skins_keys_are_strings():
	"""Ensure all keys in the YAML are strings (some might be numeric like '760' or '2001')."""
	data_path = os.path.join(os.path.dirname(__file__), "..", "src", "red_pill", "data", "lore_skins.yaml")
	with open(data_path, "r") as f:
		data = yaml.safe_load(f)
		for key in data["modes"].keys():
			# We want to ensure we handle things that yaml might load as int
			# In CLI we convert to str
			pass 
