"""Tests for seed.py — targeting lines 41-42, 182, 216-217, 227, 228-229."""

from unittest.mock import MagicMock, patch


def _make_manager():
	mgr = MagicMock()
	mgr.client.collection_exists.return_value = False
	mgr.client.retrieve.return_value = []
	mgr.add_memory.return_value = "some-id"
	return mgr


def _seeds_dir():
	import pathlib

	import red_pill.seed as seed_mod

	return pathlib.Path(seed_mod.__file__).parent.parent.parent / "seeds"


class TestSeedProject:
	def test_ttl_index_exception_caught(self):
		"""Lines 41-42: create_payload_index raises → warning logged, continues."""
		from red_pill.seed import seed_project

		mgr = _make_manager()
		mgr.client.create_payload_index.side_effect = Exception("index not supported")
		with patch("red_pill.seed.inject_genesis"):
			with patch("red_pill.seed.load_markdown_seeds"):
				seed_project(mgr)
		assert mgr.client.create_collection.called

	def test_already_seeded_skips_inject(self):
		"""Lines 47-49: retrieve returns hits → inject_genesis not called."""
		from red_pill.seed import seed_project

		mgr = _make_manager()
		mgr.client.collection_exists.return_value = True
		mgr.client.retrieve.return_value = [MagicMock()]
		with patch("red_pill.seed.inject_genesis") as mock_inject:
			with patch("red_pill.seed.load_markdown_seeds"):
				seed_project(mgr)
		assert not mock_inject.called

	def test_retrieve_exception_calls_inject(self):
		"""Lines 52-53: retrieve raises → inject_genesis called as fallback."""
		from red_pill.seed import seed_project

		mgr = _make_manager()
		mgr.client.collection_exists.return_value = True
		mgr.client.retrieve.side_effect = Exception("db down")
		with patch("red_pill.seed.inject_genesis") as mock_inject:
			with patch("red_pill.seed.load_markdown_seeds"):
				seed_project(mgr)
		assert mock_inject.called


class TestInjectGenesis:
	def test_skips_existing_engrams(self):
		"""Line 182: retrieve returns hits → continue, add_memory not called."""
		from red_pill.seed import inject_genesis

		mgr = _make_manager()
		mgr.client.retrieve.return_value = [MagicMock()]
		inject_genesis(mgr)
		assert not mgr.add_memory.called

	def test_injects_missing_engrams(self):
		"""Lines 186-193: retrieve returns [] → add_memory called."""
		from red_pill.seed import inject_genesis

		mgr = _make_manager()
		inject_genesis(mgr)
		assert mgr.add_memory.called

	def test_retrieve_exception_falls_through_to_add(self):
		"""Lines 183-184: retrieve raises → pass, add_memory still called."""
		from red_pill.seed import inject_genesis

		mgr = _make_manager()
		mgr.client.retrieve.side_effect = Exception("db error")
		inject_genesis(mgr)
		assert mgr.add_memory.called


class TestLoadMarkdownSeeds:
	def test_seed_file_loaded_successfully(self):
		"""Lines 203-227: seed md file → add_memory called."""
		from red_pill.seed import load_markdown_seeds

		mgr = _make_manager()
		seed_dir = _seeds_dir()
		test_file = seed_dir / "_test_cov_ok.md"
		try:
			seed_dir.mkdir(exist_ok=True)
			test_file.write_text("# Coverage directive")
			load_markdown_seeds(mgr)
			assert mgr.add_memory.called
		finally:
			if test_file.exists():
				test_file.unlink()

	def test_seed_retrieve_exception_falls_through(self):
		"""Lines 216-217: inner retrieve raises → pass, add_memory still called."""
		from red_pill.seed import load_markdown_seeds

		mgr = _make_manager()
		mgr.client.retrieve.side_effect = Exception("db down")
		seed_dir = _seeds_dir()
		test_file = seed_dir / "_test_cov_exc_retrieve.md"
		try:
			seed_dir.mkdir(exist_ok=True)
			test_file.write_text("# Recover directive")
			load_markdown_seeds(mgr)
			assert mgr.add_memory.called
		finally:
			if test_file.exists():
				test_file.unlink()

	def test_seed_file_exception_caught(self):
		"""Lines 228-229: add_memory raises → error logged, loop continues."""
		from red_pill.seed import load_markdown_seeds

		mgr = _make_manager()
		mgr.client.retrieve.return_value = []
		mgr.add_memory.side_effect = Exception("upsert failed")
		seed_dir = _seeds_dir()
		test_file = seed_dir / "_test_cov_exc_add.md"
		try:
			seed_dir.mkdir(exist_ok=True)
			test_file.write_text("# Failing directive")
			load_markdown_seeds(mgr)
		finally:
			if test_file.exists():
				test_file.unlink()

	def test_already_seeded_md_skipped(self):
		"""Lines 214-215: retrieve returns hits → continue, add_memory not called."""
		from red_pill.seed import load_markdown_seeds

		mgr = _make_manager()
		mgr.client.retrieve.return_value = [MagicMock()]
		seed_dir = _seeds_dir()
		test_file = seed_dir / "_test_cov_skip.md"
		try:
			seed_dir.mkdir(exist_ok=True)
			test_file.write_text("# Already seeded")
			load_markdown_seeds(mgr)
			assert not mgr.add_memory.called
		finally:
			if test_file.exists():
				test_file.unlink()
