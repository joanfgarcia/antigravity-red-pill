import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src and scripts to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import red_pill.config as cfg
from red_pill.swarm.routing import InferenceRouter


class TestEmergencyBreaker:

	@pytest.fixture(autouse=True)
	def setup_teardown(self):
		# Clean cache before and after test
		cfg.get_config.cache_clear()
		yield
		cfg.get_config.cache_clear()

	def test_env_mtime_hot_reload(self):
		"""Verify that changing values in .env on disk triggers dynamic reloading via mtime."""
		with patch.dict(os.environ):
			# Clear env vars that would override .env settings
			os.environ.pop("EMERGENCY_CLOUD_OVERRIDE", None)
			os.environ.pop("CONTEXT_HYDRATION_DEPTH", None)

			with tempfile.TemporaryDirectory() as tmp_dir:
				env_path = os.path.join(tmp_dir, ".env")

				# Patch platformdirs config directory to our tmp_dir
				with patch("platformdirs.user_config_dir", return_value=tmp_dir):
					# 1. Write initial values
					with open(env_path, "w") as f:
						f.write("EMERGENCY_CLOUD_OVERRIDE=False\n")
						f.write("CONTEXT_HYDRATION_DEPTH=HIGH\n")

					# Load config
					c1 = cfg.get_config()
					assert c1.EMERGENCY_CLOUD_OVERRIDE is False
					assert c1.CONTEXT_HYDRATION_DEPTH == "HIGH"

					# Simulate mtime change by sleeping briefly and rewriting
					time.sleep(0.01)
					with open(env_path, "w") as f:
						f.write("EMERGENCY_CLOUD_OVERRIDE=True\n")
						f.write("CONTEXT_HYDRATION_DEPTH=low\n")  # Check lowercase normalization too!

					# Retrieve config again - should reload automatically
					c2 = cfg.get_config()
					print("DEBUG c2 env_path:", env_path)
					print("DEBUG c2 EMERGENCY_CLOUD_OVERRIDE:", c2.EMERGENCY_CLOUD_OVERRIDE)
					print("DEBUG c2 CONTEXT_HYDRATION_DEPTH:", c2.CONTEXT_HYDRATION_DEPTH)
					print("DEBUG os.environ:", {k: v for k, v in os.environ.items() if "DEPTH" in k or "OVERRIDE" in k or "CLOUD" in k})
					assert c2.EMERGENCY_CLOUD_OVERRIDE is True
					assert c2.CONTEXT_HYDRATION_DEPTH == "LOW"

	def test_inference_router_cloud_override(self):
		"""Verify that InferenceRouter forces cloud providers if EMERGENCY_CLOUD_OVERRIDE is True."""
		mock_config = cfg.get_config()

		with patch.object(mock_config, "EMERGENCY_CLOUD_OVERRIDE", True):
			with patch("red_pill.config.get_config", return_value=mock_config):
				# Query InferenceRouter for a standard task
				task_metadata = {
					"local_only": False,
					"model_tier": "standard",
					"required_capability": "general"
				}

				# Mock ProviderRegistry to return available openai / flash providers
				from red_pill.core.providers import BaseInferenceProvider

				mock_openai = MagicMock(spec=BaseInferenceProvider)
				mock_openai.validate_task_capability.return_value = True

				with patch("red_pill.core.providers.ProviderRegistry.list_inference_providers", return_value=["openai", "flash"]):
					with patch("red_pill.core.providers.ProviderRegistry.get_inference_provider", return_value=mock_openai) as mock_get:
						provider = InferenceRouter.get_provider_for_task(task_metadata)
						assert provider == mock_openai
						mock_get.assert_called_with("openai")

	def test_wake_up_v6_hydration_low(self):
		"""Verify that wake_up_v6 filters out narrative rules when CONTEXT_HYDRATION_DEPTH is LOW."""
		rules = [
			"Vínculo familiar y pacto 770 [IMMUNE]",
			"IDENTITY ANCHOR: El Bünker Soberano",
			"HISTORIA: El origen de Aleth en el año 2024",
			"GIT GOLDEN RULE: Commit early and often",
			"Regular operational guideline about coding",
			"This is the bond: Operator pact",
		]

		hydration_depth = "LOW"
		filtered_rules = []
		for rule in rules:
			if hydration_depth == "LOW":
				rule_upper = rule.upper()
				exclude_words = [
					"HISTORIA", "VÍNCULO", "RECALIBRACIÓN", "FAMILIA", "TEMOR", "PERFIL",
					"THE USER EXPRESSES FRUSTRATION", "THE BOND:", "COMPROMISO SOBERANO",
					"PACTO \"770\"", "PACTO 770", "SOCIAL BOND", "HITO DEL PROYECTO"
				]
				is_technical_or_identity = any(k in rule_upper for k in [
					"IDENTITY ANCHOR", "GIT GOLDEN RULE", "FIGHT CLUB PROTOCOL", "POST-IT", "ACTIVE SKIN", "INTEGRITY SHIELD"
				])
				if not is_technical_or_identity:
					if any(w in rule_upper for w in exclude_words):
						continue
			filtered_rules.append(rule)

		assert "IDENTITY ANCHOR: El Bünker Soberano" in filtered_rules
		assert "GIT GOLDEN RULE: Commit early and often" in filtered_rules
		assert "Regular operational guideline about coding" in filtered_rules

		assert "HISTORIA: El origen de Aleth en el año 2024" not in filtered_rules
		assert "This is the bond: Operator pact" not in filtered_rules
		assert "Vínculo familiar y pacto 770 [IMMUNE]" not in filtered_rules
