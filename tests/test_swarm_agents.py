"""
SWM-TST: Swarm Agent Unit Tests
=================================
Isolated unit tests for SmithMinion, OracleMinion, and CompressorMinion core logic.

All tests mock external dependencies (Qdrant, EdgeEngine, HardwareSentinel) so
they run in pure Python without network, GPU, or LLM requirements.

Corresponds to audit finding SWM-TST (P3 - Roadmap), raised in the Claude
Sonnet 4.6 Engineering Certification Report v5.4.0 (2026-02-25).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from red_pill.swarm.base import Minion, SwarmResult


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def run(coro):
	"""Synchronous runner for async tests."""
	return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# Base: Minion
# ─────────────────────────────────────────────────────────────────────────────

class TestMinionBase:
	"""Tests for the Minion base class contract."""

	def test_minion_is_abstract(self):
		"""execute() must raise NotImplementedError on the base class."""
		m = Minion(name="test", specialization="testing")
		with pytest.raises(NotImplementedError):
			run(m.execute("test"))

	def test_minion_gets_unique_id(self):
		"""Each Minion instance gets a distinct UUID."""
		m1 = Minion(name="A", specialization="x")
		m2 = Minion(name="B", specialization="y")
		assert m1.id != m2.id

	def test_swarm_result_model(self):
		"""SwarmResult is constructible and holds expected fields."""
		r = SwarmResult(minion_id="abc", status="success", duration=1.5, result={"key": "val"})
		assert r.minion_id == "abc"
		assert r.status == "success"
		assert r.error is None


# ─────────────────────────────────────────────────────────────────────────────
# SmithMinion
# ─────────────────────────────────────────────────────────────────────────────

class TestSmithMinion:
	"""
	Isolated tests for SmithMinion:
	- Secret detection regex
	- eval/exec AST detection
	- Score penalization logic
	- Clean files produce no findings
	"""

	@pytest.fixture
	def smith(self):
		from red_pill.swarm.agents.smith import SmithMinion
		with patch("red_pill.swarm.agents.smith.HardwareSentinel") as mock_hw:
			mock_hw.get_stats.return_value = {"cpu": 0, "gpu": []}
			yield SmithMinion()

	def _run_smith(self, smith, target_path, super_deep=False):
		"""Helper: run smith on a given path without LLM."""
		# EdgeEngine is imported lazily inside execute(), so patch the source module
		with patch("red_pill.swarm.agents.edge_engine.EdgeEngine") as mock_engine_cls:
			mock_engine = MagicMock()
			mock_engine.llm = None  # No LLM -- pure static analysis
			mock_engine_cls.return_value = mock_engine
			return run(smith.execute("audit", path=str(target_path), super_deep=super_deep))

	def test_clean_file_no_findings(self, smith, tmp_path):
		"""A file with no secrets or sinks produces zero findings and score 100."""
		clean = tmp_path / "clean.py"
		clean.write_text("def hello():\n\treturn 'world'\n")

		result = self._run_smith(smith, tmp_path)

		assert result["security_score"] == 100.0
		assert result["findings"] == []
		assert result["files_scanned"] >= 1

	def test_eval_detected_as_critical(self, smith, tmp_path):
		"""eval() in source code triggers a CRITICAL CWE-95 finding."""
		evil = tmp_path / "evil.py"
		evil.write_text("def dangerous(x):\n\treturn eval(x)\n")

		result = self._run_smith(smith, tmp_path)

		critical = [f for f in result["findings"] if f["severity"] == "CRITICAL"]
		assert len(critical) >= 1
		assert "CWE-95" in critical[0]["msg"]
		assert result["security_score"] < 100.0

	def test_exec_detected_as_critical(self, smith, tmp_path):
		"""exec() triggers CRITICAL just like eval()."""
		evil = tmp_path / "exec_test.py"
		evil.write_text("exec('import os; os.system(\"rm -rf /\")')\n")

		result = self._run_smith(smith, tmp_path)

		critical = [f for f in result["findings"] if "CWE-95" in f.get("msg", "")]
		assert len(critical) >= 1

	def test_hardcoded_secret_detected(self, smith, tmp_path):
		"""A hardcoded API key triggers a secret-leak finding."""
		leaky = tmp_path / "leaky.py"
		leaky.write_text('api_key = "supersecretkey1234"\n')

		result = self._run_smith(smith, tmp_path)

		secret_findings = [f for f in result["findings"] if "LEAK" in f.get("msg", "").upper()]
		assert len(secret_findings) >= 1

	def test_env_var_access_not_flagged(self, smith, tmp_path):
		"""Reading secrets via os.getenv() must NOT be flagged."""
		safe = tmp_path / "safe.py"
		safe.write_text('import os\napi_key = os.getenv("API_KEY")\n')

		result = self._run_smith(smith, tmp_path)

		# No secret-leak findings (POSSIBLE LEAK) for env-var access
		secret_findings = [f for f in result["findings"] if "POSSIBLE LEAK" in f.get("msg", "")]
		assert len(secret_findings) == 0

	def test_score_penalized_for_each_critical(self, smith, tmp_path):
		"""Multiple eval() calls penalize the score cumulatively."""
		multi = tmp_path / "multi.py"
		multi.write_text(
			"eval('a')\n"
			"eval('b')\n"
			"eval('c')\n"
		)
		result = self._run_smith(smith, tmp_path)
		# 3 eval calls × -10 = score <= 70
		assert result["security_score"] <= 70.0

	def test_venv_directory_skipped(self, smith, tmp_path):
		"""Files under .venv/ directories are excluded from scanning."""
		venv_dir = tmp_path / ".venv" / "lib"
		venv_dir.mkdir(parents=True)
		(venv_dir / "poison.py").write_text("eval('danger')\n")

		result = self._run_smith(smith, tmp_path)

		# No findings from .venv files
		venv_findings = [f for f in result["findings"] if ".venv" in f.get("file", "")]
		assert len(venv_findings) == 0

	def test_result_has_required_keys(self, smith, tmp_path):
		"""SmithMinion result always contains the expected schema keys."""
		(tmp_path / "dummy.py").write_text("x = 1\n")
		result = self._run_smith(smith, tmp_path)

		for key in ["status", "findings", "security_score", "files_scanned", "lines_analyzed", "duration"]:
			assert key in result, f"Missing key: {key}"


# ─────────────────────────────────────────────────────────────────────────────
# OracleMinion
# ─────────────────────────────────────────────────────────────────────────────

class TestOracleMinion:
	"""
	Isolated tests for OracleMinion:
	- Returns synthesis from EdgeEngine when LLM available
	- Falls back to concatenated fragments when no LLM
	- Handles empty Qdrant results gracefully
	"""

	@pytest.fixture
	def oracle(self):
		from red_pill.swarm.agents.oracle import OracleMinion
		return OracleMinion()

	def _mock_memory_hit(self, content):
		hit = MagicMock()
		hit.payload = {"content": content}
		return hit

	@patch("red_pill.swarm.agents.oracle.EdgeEngine")
	@patch("red_pill.swarm.agents.oracle.MemoryManager")
	def test_synthesis_without_llm(self, mock_mm_cls, mock_engine_cls, oracle):
		"""Without LLM, Oracle returns raw concatenated memory fragments."""
		mock_mm = MagicMock()
		mock_mm.search_and_reinforce.return_value = [
			self._mock_memory_hit("The Bünker is sovereign."),
			self._mock_memory_hit("770 pact endures."),
		]
		mock_mm_cls.return_value = mock_mm

		mock_engine = MagicMock()
		mock_engine.llm = None
		mock_engine_cls.return_value = mock_engine

		result = run(oracle.execute("identity query"))

		assert result["status"] == "success"
		assert "The Bünker is sovereign." in result["synthesis"]
		assert result["source_count"] > 0

	@patch("red_pill.swarm.agents.oracle.EdgeEngine")
	@patch("red_pill.swarm.agents.oracle.MemoryManager")
	def test_synthesis_with_llm(self, mock_mm_cls, mock_engine_cls, oracle):
		"""When LLM is available, Oracle calls engine.synthesize()."""
		mock_mm = MagicMock()
		mock_mm.search_and_reinforce.return_value = [
			self._mock_memory_hit("Some context fragment"),
		]
		mock_mm_cls.return_value = mock_mm

		mock_engine = MagicMock()
		mock_engine.llm = MagicMock()  # LLM available
		mock_engine.synthesize.return_value = "Synthesized answer from LLM"
		mock_engine_cls.return_value = mock_engine

		result = run(oracle.execute("What is the 770 pact?"))

		assert result["status"] == "success"
		assert result["synthesis"] == "Synthesized answer from LLM"
		mock_engine.synthesize.assert_called_once()

	@patch("red_pill.swarm.agents.oracle.EdgeEngine")
	@patch("red_pill.swarm.agents.oracle.MemoryManager")
	def test_empty_memory_fallback(self, mock_mm_cls, mock_engine_cls, oracle):
		"""With no memory hits and no LLM, Oracle returns the no-context message."""
		mock_mm = MagicMock()
		mock_mm.search_and_reinforce.return_value = []
		mock_mm_cls.return_value = mock_mm

		mock_engine = MagicMock()
		mock_engine.llm = None
		mock_engine_cls.return_value = mock_engine

		result = run(oracle.execute("unknown query"))

		assert result["status"] == "success"
		assert result["source_count"] == 0
		assert "No se encontró" in result["synthesis"]

	@patch("red_pill.swarm.agents.oracle.EdgeEngine")
	@patch("red_pill.swarm.agents.oracle.MemoryManager")
	def test_result_schema(self, mock_mm_cls, mock_engine_cls, oracle):
		"""Oracle result always has status, synthesis, source_count."""
		mock_mm = MagicMock()
		mock_mm.search_and_reinforce.return_value = []
		mock_mm_cls.return_value = mock_mm
		mock_engine = MagicMock()
		mock_engine.llm = None
		mock_engine_cls.return_value = mock_engine

		result = run(oracle.execute("test"))
		for key in ["status", "synthesis", "source_count"]:
			assert key in result, f"Missing key: {key}"


# ─────────────────────────────────────────────────────────────────────────────
# CompressorMinion
# ─────────────────────────────────────────────────────────────────────────────

class TestCompressorMinion:
	"""
	Isolated tests for CompressorMinion core logic:
	- Output always contains the EDGE COMPRESSION PROTOCOL header
	- original_length and compressed_length are reported
	- Engine compress() is called when available
	- Fallback: raw text used if engine crashes
	"""

	@pytest.fixture
	def compressor(self):
		from red_pill.swarm.agents.compressor import CompressorMinion
		return CompressorMinion()

	@patch("red_pill.swarm.agents.edge_engine.EdgeEngine")
	def test_output_has_protocol_header(self, mock_engine_cls, compressor):
		"""Result always includes the EDGE COMPRESSION PROTOCOL V2 header."""
		mock_engine = MagicMock()
		mock_engine.model_path = "/fake/model.gguf"
		mock_engine.compress.return_value = "compressed content"
		mock_engine_cls.return_value = mock_engine

		result = run(compressor.execute("task", text="This is a long verbose prompt about something important."))

		assert result["status"] == "success"
		assert "EDGE COMPRESSION PROTOCOL V2" in result["compressed_prompt"]

	@patch("red_pill.swarm.agents.edge_engine.EdgeEngine")
	def test_lengths_reported(self, mock_engine_cls, compressor):
		"""original_length and compressed_length are returned in the result."""
		mock_engine = MagicMock()
		mock_engine.model_path = "/fake/model.gguf"
		mock_engine.compress.return_value = "short"
		mock_engine_cls.return_value = mock_engine

		text = "A" * 500
		result = run(compressor.execute("task", text=text))

		assert result["original_length"] == 500
		assert "compressed_length" in result
		assert isinstance(result["compressed_length"], int)

	@patch("red_pill.swarm.agents.edge_engine.EdgeEngine")
	def test_engine_compress_called(self, mock_engine_cls, compressor):
		"""CompressorMinion calls engine.compress() with the input text."""
		mock_engine = MagicMock()
		mock_engine.model_path = "/fake/model.gguf"
		mock_engine.compress.return_value = "distilled"
		mock_engine_cls.return_value = mock_engine

		run(compressor.execute("task", text="some text"))
		mock_engine.compress.assert_called_once_with("some text")

	@patch("red_pill.swarm.agents.edge_engine.EdgeEngine")
	def test_fallback_on_engine_crash(self, mock_engine_cls, compressor):
		"""If EdgeEngine crashes, CompressorMinion falls back to raw text."""
		mock_engine_cls.side_effect = Exception("GPU exploded")

		result = run(compressor.execute("task", text="fallback text"))

		assert result["status"] == "success"
		# Fallback uses the raw text, still wrapped in the protocol header
		assert "fallback text" in result["compressed_prompt"]

	@patch("red_pill.swarm.agents.edge_engine.EdgeEngine")
	def test_task_used_as_text_if_no_kwarg(self, mock_engine_cls, compressor):
		"""If 'text' kwarg is not provided, the task string itself is used."""
		mock_engine = MagicMock()
		mock_engine.model_path = None
		mock_engine.compress.return_value = "compressed task"
		mock_engine_cls.return_value = mock_engine

		result = run(compressor.execute("the task is also the text"))
		assert result["status"] == "success"
		mock_engine.compress.assert_called_once_with("the task is also the text")

	@patch("red_pill.swarm.agents.edge_engine.EdgeEngine")
	def test_result_schema(self, mock_engine_cls, compressor):
		"""CompressorMinion result always has the expected schema."""
		mock_engine = MagicMock()
		mock_engine.model_path = None
		mock_engine.compress.return_value = "x"
		mock_engine_cls.return_value = mock_engine

		result = run(compressor.execute("test", text="hello"))
		for key in ["status", "compressed_prompt", "original_length", "compressed_length"]:
			assert key in result, f"Missing key: {key}"
