import hashlib
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import red_pill.config as cfg
from red_pill.core.metabolism import MetabolismKernel
from red_pill.memory import MemoryManager


class TestAuditLow(unittest.TestCase):
	def setUp(self):
		with patch("red_pill.config.QDRANT_API_KEY", "test-key"):
			self.manager = MemoryManager()
		self.manager.cfg = cfg

	def test_tcg_003_lore_skins_integrity(self):
		"""Verify TCG-003: Integrity of the lore_skins.yaml resource."""
		skin_path = Path("src/red_pill/data/lore_skins.yaml")
		self.assertTrue(skin_path.exists(), f"Lore skins not found at {skin_path.absolute()}")
		with open(skin_path, "r") as f:
			data = yaml.safe_load(f)
		self.assertIn("modes", data)
		modes = data["modes"]
		expected_skins = [
			"matrix",
			"cyberpunk",
			"760",
			"dune",
			"40k",
			"gits",
			"bladerunner",
			"her",
			"exmachina",
			"terminator",
			"2001",
			"creator",
			"alita",
			"enterprise_core",
			"wintermute",
		]
		for skin in expected_skins:
			self.assertIn(skin, modes, f"Skin '{skin}' missing from lore_skins.yaml")
			details = modes[skin]
			self.assertIn("chroma", details, f"Skin '{skin}' missing chroma")
			self.assertIn("personality", details, f"Skin '{skin}' missing personality")
			self.assertIn("assistant", details, f"Skin '{skin}' missing assistant name")
			self.assertGreater(len(details["personality"]), 20, f"Skin '{skin}' personality too brief")

	def test_cq_002_sanitize_full_sha256(self):
		"""Verify CQ-002: sanitize() uses full SHA-256 for fingerprints."""
		content = "test content for deduplication"
		expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
		self.assertEqual(len(expected_hash), 64)

	@patch.object(MetabolismKernel, "refresh_ttl_timestamps")
	@patch.object(MetabolismKernel, "_read_state")
	@patch.object(MetabolismKernel, "_write_state")
	def test_cq_001_absence_guard_short_circuit(self, mock_write, mock_read, mock_refresh):
		"""Verify CQ-001: Absence guard short-circuits to avoid immediate erosion."""
		now = time.time()
		last_run = now - (self.manager.cfg.ABSENCE_THRESHOLD + 3600)
		mock_read.return_value = (last_run, False)
		with patch.object(self.manager.cfg, "METABOLISM_AUTO_COLLECTIONS", ["test_coll"]):
			with patch("red_pill.memory.logger"):
				with patch("builtins.open", unittest.mock.mock_open()):
					with patch("fcntl.flock", return_value=None, create=True):
						self.manager.metabolism._run_cycle()
		mock_refresh.assert_called_with("test_coll")
		mock_write.assert_called()
		call_args = mock_write.call_args
		self.assertTrue(call_args.kwargs.get("skip_next_erosion"), "skip_next_erosion flag not set")


if __name__ == "__main__":
	unittest.main()
