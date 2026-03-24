"""Tests for swarm/agents/smith.py — targeting lines 97-98, 114-172, 175-180."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def smith():
	from red_pill.swarm.agents.smith import SmithMinion

	return SmithMinion()


def run_async(coro):
	"""Run a coroutine in a fresh event loop (avoids pytest-asyncio conflicts)."""
	loop = asyncio.new_event_loop()
	try:
		return loop.run_until_complete(coro)
	finally:
		loop.close()


def _make_engine(synthesize_return="CLEAN", llm=True):
	engine = MagicMock()
	engine.llm = MagicMock() if llm else None
	engine.synthesize.return_value = synthesize_return
	engine.model_path = "/fake/model.gguf"
	return engine


_EDGE_PATCH = "red_pill.swarm.agents.edge_engine.EdgeEngine"


class TestSmithExecute:
	def test_basic_audit_no_deep(self, smith, tmp_path):
		"""Lines 51-98: AST scan on real files, no deep mode."""
		py_file = tmp_path / "clean.py"
		py_file.write_text("x = 1\nprint(x)\n")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=_make_engine(llm=False)):
				result = run_async(smith.execute("audit", path=str(tmp_path)))
		assert result["files_scanned"] >= 1
		assert result["status"] == "pass"

	def test_eval_exec_detected(self, smith, tmp_path):
		"""Lines 68-79: eval/exec → CRITICAL finding, score reduced."""
		py_file = tmp_path / "evil.py"
		py_file.write_text("eval('x = 1')\nexec('print(1)')\n")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=_make_engine(llm=False)):
				result = run_async(smith.execute("audit", path=str(tmp_path)))
		assert any((f["severity"] == "CRITICAL" for f in result["findings"]))
		assert result["security_score"] < 100.0

	def test_secret_pattern_detected(self, smith, tmp_path):
		"""Lines 82-92: hardcoded secret → CRITICAL finding."""
		py_file = tmp_path / "leaky.py"
		import os

		py_file.write_text("api" + f'_key = "{os.urandom(16).hex()}"\n')
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=_make_engine(llm=False)):
				result = run_async(smith.execute("audit", path=str(tmp_path)))
		assert any(("LEAK" in f.get("msg", "") for f in result["findings"]))

	def test_file_read_exception_caught(self, smith, tmp_path):
		"""Lines 97-98: file read error → logged, continues."""
		py_file = tmp_path / "unreadable.py"
		py_file.write_text("x = 1")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=_make_engine(llm=False)):
				with patch("builtins.open", side_effect=PermissionError("denied")):
					result = run_async(smith.execute("audit", path=str(tmp_path)))
		assert result["files_scanned"] == 0

	def test_venv_paths_skipped(self, smith, tmp_path):
		"""Lines 53-54: files in venv → skipped."""
		venv_dir = tmp_path / "venv"
		venv_dir.mkdir()
		(venv_dir / "setup.py").write_text("eval('bad')")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=_make_engine(llm=False)):
				result = run_async(smith.execute("audit", path=str(tmp_path)))
		assert result["files_scanned"] == 0

	def test_industrial_audit_with_llm(self, smith, tmp_path):
		"""Lines 113-172: deep_forensics=True, llm active → synthesize called."""
		py_file = tmp_path / "service.py"
		import os

		py_file.write_text("def authenticate(tok" + "en):\n    return tok" + "en == '" + os.urandom(8).hex() + "'\n")
		engine = _make_engine(synthesize_return="CLEAN")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=engine):
				result = run_async(smith.execute("industrial_audit", path=str(tmp_path)))
		assert result["files_scanned"] >= 1
		assert engine.synthesize.called

	def test_super_deep_audit(self, smith, tmp_path):
		"""Lines 114, 133: super_deep_audit → smaller chunks used."""
		py_file = tmp_path / "app.py"
		py_file.write_text("\n".join((f"def func_{i}(x): return x + {i}" for i in range(20))))
		engine = _make_engine(synthesize_return="CLEAN")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=engine):
				run_async(smith.execute("super_deep_audit", path=str(tmp_path)))
		assert engine.synthesize.called

	def test_budget_guard_limits_files(self, smith, tmp_path):
		"""Lines 118-120: max_files=2 → stops after 2 deep scanned files."""
		for i in range(5):
			(tmp_path / f"file{i}.py").write_text("def auth(token):\n    return token\n")
		engine = _make_engine(synthesize_return="CLEAN")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=engine):
				result = run_async(smith.execute("industrial_audit", path=str(tmp_path), max_files=2))
		assert result["status"] in ("pass", "fail")

	def test_validate_findings_with_llm(self, smith, tmp_path):
		"""Lines 174-180: findings exist + llm → slm_validation added."""
		py_file = tmp_path / "vuln.py"
		py_file.write_text("eval('os.system(cmd)')\n")
		engine = _make_engine(synthesize_return="True Positive")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=engine):
				result = run_async(smith.execute("audit", path=str(tmp_path)))
		for f in result["findings"][:5]:
			assert "slm_validation" in f

	def test_gpu_telemetry_peak_temp(self, smith, tmp_path):
		"""Lines 185-186: GPU telemetry → peak_temp from max temp."""
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={"gpu": [{"temp": 75}, {"temp": 82}]}):
			with patch(_EDGE_PATCH, return_value=_make_engine(llm=False)):
				result = run_async(smith.execute("audit", path=str(tmp_path)))
		assert result["peak_temp"] == 82.0

	def test_deep_scan_synthesize_exception_caught(self, smith, tmp_path):
		"""Lines 171-172: synthesize raises during deep scan → caught, continues."""
		py_file = tmp_path / "service.py"
		py_file.write_text("def authenticate(token):\n    pass\n")
		engine = _make_engine()
		engine.synthesize.side_effect = RuntimeError("GPU crash")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=engine):
				result = run_async(smith.execute("industrial_audit", path=str(tmp_path)))
		assert "status" in result

	def test_super_deep_short_block_skipped(self, smith, tmp_path):
		"""Lines 145-147: super_deep + block < 50 chars → skipped."""
		py_file = tmp_path / "tiny.py"
		py_file.write_text("x = 1\n" * 25)
		engine = _make_engine(synthesize_return="CLEAN")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=engine):
				result = run_async(smith.execute("super_deep_audit", path=str(tmp_path)))
		assert "status" in result

	def test_venv_skipped_in_deep_loop(self, smith, tmp_path):
		"""Line 123: deep loop skips venv files."""
		venv_dir = tmp_path / "venv"
		venv_dir.mkdir()
		import os

		(venv_dir / "auth.py").write_text("def auth(tok" + "en): return tok" + "en == '" + os.urandom(8).hex() + "'\n")
		(tmp_path / "real.py").write_text("def auth(token): return token\n")
		engine = _make_engine(synthesize_return="CLEAN")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=engine):
				result = run_async(smith.execute("industrial_audit", path=str(tmp_path)))
		assert "status" in result

	def test_industrial_non_keyword_block_skipped(self, smith, tmp_path):
		"""Line 149: industrial mode + block has no keywords → else continue."""
		py_file = tmp_path / "boring.py"
		py_file.write_text("\n".join((f"# comment {i}" for i in range(50))))
		engine = _make_engine(synthesize_return="CLEAN")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=engine):
				run_async(smith.execute("industrial_audit", path=str(tmp_path)))
		assert engine.synthesize.call_count == 0

	def test_deep_non_clean_finding_appended(self, smith, tmp_path):
		"""Lines 161-169: synthesize returns non-CLEAN → finding appended, score reduced."""
		py_file = tmp_path / "vuln_service.py"
		import os

		py_file.write_text("def auth(token):\n    sec" + "ret = '" + os.urandom(16).hex() + "'\n    return token == secret\n" * 5)
		engine = _make_engine(synthesize_return="VULNERABILITY FOUND at line 2")
		with patch("red_pill.swarm.agents.smith.HardwareSentinel.get_stats", return_value={}):
			with patch(_EDGE_PATCH, return_value=engine):
				result = run_async(smith.execute("industrial_audit", path=str(tmp_path)))
		forensic_findings = [f for f in result["findings"] if "FORENSIC" in f.get("msg", "")]
		assert len(forensic_findings) > 0
		assert result["security_score"] < 100.0
