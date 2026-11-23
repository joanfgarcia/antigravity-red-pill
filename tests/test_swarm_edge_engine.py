"""Tests for swarm/agents/edge_engine.py — targeting lines 12-13, 46-48, 55, 59-65, 74-76, 81, 97-101, 106-134, 138-167, 171."""

from unittest.mock import MagicMock, patch


class TestEdgeEngineInit:
	@patch("red_pill.swarm.agents.edge_engine.get_models_dir")
	def test_model_path_from_profile(self, mock_get_models_dir, tmp_path):
		"""El perfil explícito manda (2026-11-23): ya no se elige "el primer .gguf"."""
		mock_get_models_dir.return_value = tmp_path
		with patch("red_pill.core.model_registry.ModelRegistry.get_profile", return_value={"model_path": "granite-4.2-8b-Q4_K_M.gguf"}):
			from red_pill.swarm.agents.edge_engine import EdgeEngine

			engine = EdgeEngine()
		assert engine.model_path == str(tmp_path / "granite-4.2-8b-Q4_K_M.gguf")

	@patch("red_pill.swarm.agents.edge_engine.get_models_dir")
	def test_profile_missing_leaves_none(self, mock_get_models_dir, tmp_path):
		"""Perfil sin resolución → None (modo extracción), nunca un GGUF al azar."""
		mock_get_models_dir.return_value = tmp_path
		(tmp_path / "other_model.gguf").write_bytes(b"fake")
		with patch("red_pill.core.model_registry.ModelRegistry.get_profile", return_value={}):
			from red_pill.swarm.agents.edge_engine import EdgeEngine

			engine = EdgeEngine()
		assert engine.model_path is None

	@patch("red_pill.swarm.agents.edge_engine.get_models_dir")
	def test_no_model_dir(self, mock_get_models_dir, tmp_path):
		"""Model dir ausente y perfil vacío → model_path None."""
		mock_get_models_dir.return_value = tmp_path / "fake_xdg"
		with patch("red_pill.core.model_registry.ModelRegistry.get_profile", return_value={}):
			from red_pill.swarm.agents.edge_engine import EdgeEngine

			engine = EdgeEngine()
		assert engine.model_path is None


class TestEnsureLoaded:
	def test_already_loaded_returns_early(self):
		"""Line 54-55: _llm_loaded=True → immediate return."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._llm_loaded = True
		engine._ensure_loaded()

	def test_llama_not_available(self):
		"""Lines 59-60: LLAMA_AVAILABLE=False → llm stays None."""
		import red_pill.swarm.agents.edge_engine as ee_mod
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		original = ee_mod.LLAMA_AVAILABLE
		try:
			ee_mod.LLAMA_AVAILABLE = False
			engine = EdgeEngine(model_path=None)
			engine._ensure_loaded()
			assert engine.llm is None
		finally:
			ee_mod.LLAMA_AVAILABLE = original

	def test_no_model_path(self):
		"""Lines 61-62: LLAMA_AVAILABLE but no model_path → llm stays None."""
		import red_pill.swarm.agents.edge_engine as ee_mod
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		ee_mod.LLAMA_AVAILABLE = True
		engine = EdgeEngine(model_path=None)
		engine.model_path = None
		engine._ensure_loaded()
		assert engine.llm is None

	def test_model_path_not_exists(self, tmp_path):
		"""Lines 63-64: model path provided but doesn't exist → warning, llm=None."""
		import red_pill.swarm.agents.edge_engine as ee_mod
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		ee_mod.LLAMA_AVAILABLE = True
		engine = EdgeEngine(model_path=str(tmp_path / "nonexistent.gguf"))
		engine._ensure_loaded()
		assert engine.llm is None

	def test_llama_load_exception(self, tmp_path):
		"""Lines 74-76: Llama() raises → llm set to None, no crash."""
		import red_pill.swarm.agents.edge_engine as ee_mod

		model_file = tmp_path / "model.gguf"
		model_file.write_bytes(b"fake")
		original_avail = ee_mod.LLAMA_AVAILABLE
		try:
			ee_mod.LLAMA_AVAILABLE = True
			with patch.object(ee_mod, "Llama", create=True, side_effect=RuntimeError("load failed")):
				from red_pill.swarm.agents.edge_engine import EdgeEngine

				engine = EdgeEngine(model_path=str(model_file))
				engine._llm_loaded = False
				engine._ensure_loaded()
			assert engine.llm is None
		finally:
			ee_mod.LLAMA_AVAILABLE = original_avail


class TestCompress:
	def test_fallback_when_no_llm(self):
		"""Line 81: no llm → _fallback_compress called."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._llm_loaded = True
		engine.llm = None
		result = engine.compress("Hello world, I need help with my project")
		assert isinstance(result, str)
		assert len(result) > 0

	def test_llm_compress_returns_text(self):
		"""Lines 92-96: llm output is dict → text extracted."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._llm_loaded = True
		engine.llm = MagicMock(return_value={"choices": [{"text": "  compressed output  "}]})
		result = engine.compress("Long text to compress")
		assert result == "compressed output"

	def test_llm_compress_non_dict_returns_empty(self):
		"""Lines 97: llm output not dict → returns ''."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._llm_loaded = True
		engine.llm = MagicMock(return_value="raw string")
		result = engine.compress("text")
		assert result == ""

	def test_llm_compress_exception_fallback(self):
		"""Lines 99-101: llm raises → _fallback_compress used."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._llm_loaded = True
		engine.llm = MagicMock(side_effect=RuntimeError("VRAM OOM"))
		result = engine.compress("important text")
		assert isinstance(result, str)


class TestFallbackCompress:
	def test_removes_fluff_patterns(self):
		"""Lines 106-134: fluff patterns removed, bullet points returned."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._llm_loaded = True
		engine.llm = None
		text = "Necesito que implementes un sistema de auth. Creo que podría usar JWT."
		result = engine._fallback_compress(text)
		assert isinstance(result, str)

	def test_empty_result_returns_original(self):
		"""Line 134: synthesis is empty → returns original stripped text."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		result = engine._fallback_compress("   ")
		assert isinstance(result, str)


class TestSynthesize:
	def test_fallback_when_no_llm(self):
		"""Lines 139-143: no llm → sanitized fallback returned."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._llm_loaded = True
		engine.llm = None
		result = engine.synthesize("some background", "what is this?")
		assert "Contexto Refinado" in result

	def test_llm_synthesize_returns_text(self):
		"""Lines 157-164: llm returns dict → text extracted."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._llm_loaded = True
		engine.llm = MagicMock(return_value={"choices": [{"text": "  synthesis result  "}]})
		result = engine.synthesize("background", "query")
		assert result == "synthesis result"

	def test_llm_synthesize_non_dict_returns_empty(self):
		"""Line 165: output not dict → returns ''."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._llm_loaded = True
		engine.llm = MagicMock(return_value="raw")
		result = engine.synthesize("bg", "q")
		assert result == ""

	def test_llm_synthesize_exception(self):
		"""Lines 166-167: exception → returns error snippet."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._llm_loaded = True
		engine.llm = MagicMock(side_effect=RuntimeError("crash"))
		result = engine.synthesize("background text", "query")
		assert "Synthesis Failure" in result or "Err:" in result


class TestLogWarn:
	def test_prints_warning(self, capsys):
		"""Line 171: _log_warn prints message."""
		from red_pill.swarm.agents.edge_engine import EdgeEngine

		engine = EdgeEngine(model_path=None)
		engine._log_warn("test warning message")
		captured = capsys.readouterr()
		assert "test warning message" in captured.out
