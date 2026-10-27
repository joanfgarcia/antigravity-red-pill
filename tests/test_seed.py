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

	def test_always_calls_inject_genesis(self):
		"""inject_genesis is always called for migrations."""
		from red_pill.seed import seed_project

		mgr = _make_manager()
		mgr.client.collection_exists.return_value = True
		mgr.client.retrieve.return_value = [MagicMock()]
		with patch("red_pill.seed.inject_genesis") as mock_inject:
			with patch("red_pill.seed.load_markdown_seeds"):
				seed_project(mgr)
		assert mock_inject.called

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
	def test_skips_existing_state_engrams(self):
		"""State-tracking engrams (MOOD/ACTIVE_SKIN) are skipped if retrieve returns hits."""
		from red_pill.seed import ID_DIR_ACTIVE_SKIN, ID_OPERATOR_MOOD, inject_genesis

		mgr = _make_manager()
		mgr.client.retrieve.return_value = [MagicMock()]
		inject_genesis(mgr)
		assert mgr.add_memory.called
		called_ids = [call.kwargs.get("point_id") for call in mgr.add_memory.call_args_list]
		assert ID_OPERATOR_MOOD not in called_ids
		assert ID_DIR_ACTIVE_SKIN not in called_ids

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


class TestGenesisSinPlaceholders:
	"""Incidente 2026-10-27: el engrama `ID_DIR_GIT_RULE` se sembraba con
	`${AGENT_CORE_DIR}` crudo porque el texto vive en código y nadie lo resolvía.
	El agente leía una ruta que no existe en vez del desk real."""

	def test_render_paths_resuelve_el_desk(self):
		from red_pill.core.paths import get_agent_core_root
		from red_pill.seed import _render_paths

		assert _render_paths("DESK (${AGENT_CORE_DIR})") == f"DESK ({get_agent_core_root()})"
		# Un texto sin placeholders no se toca.
		assert _render_paths("sin rutas") == "sin rutas"
		assert "${" not in _render_paths("${AGENT_CORE_DIR}/${REDPILL_DIR}")

	def test_genesis_se_siembra_sin_placeholders(self):
		from red_pill.seed import ID_DIR_GIT_RULE, inject_genesis

		mgr = _make_manager()
		mgr.client.retrieve.return_value = []
		inject_genesis(mgr)

		textos = {call.args[1] for call in mgr.add_memory.call_args_list if len(call.args) > 1}
		assert textos, "inject_genesis no sembró nada"
		crudos = [t for t in textos if "${" in t]
		assert not crudos, f"engramas con placeholder sin resolver: {[t[:80] for t in crudos]}"

		git_rule = [
			c.kwargs.get("point_id") or (c.args[0] if c.args else None) for c in mgr.add_memory.call_args_list
		]
		assert ID_DIR_GIT_RULE in git_rule
		texto_git = next(
			c.args[1] for c in mgr.add_memory.call_args_list if c.kwargs.get("point_id") == ID_DIR_GIT_RULE
		)
		assert "DESK (" in texto_git and "${" not in texto_git
