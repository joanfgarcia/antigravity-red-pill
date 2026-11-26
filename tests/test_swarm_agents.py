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
import os
from unittest.mock import MagicMock, patch

import pytest

from red_pill.swarm.base import Minion, SwarmResult


def run(coro):
	"""Synchronous runner for async tests."""
	return asyncio.run(coro)


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
		with patch("red_pill.swarm.agents.edge_engine.EdgeEngine") as mock_engine_cls:
			mock_engine = MagicMock()
			mock_engine.llm = None
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
		leaky.write_text("api" + '_key = "' + os.urandom(16).hex() + '"\n')
		result = self._run_smith(smith, tmp_path)
		secret_findings = [f for f in result["findings"] if "LEAK" in f.get("msg", "").upper()]
		assert len(secret_findings) >= 1

	def test_env_var_access_not_flagged(self, smith, tmp_path):
		"""Reading secrets via os.getenv() must NOT be flagged."""
		safe = tmp_path / "safe.py"
		safe.write_text('import os\napi_key = os.getenv("API_KEY")\n')
		result = self._run_smith(smith, tmp_path)
		secret_findings = [f for f in result["findings"] if "POSSIBLE LEAK" in f.get("msg", "")]
		assert len(secret_findings) == 0

	def test_score_penalized_for_each_critical(self, smith, tmp_path):
		"""Multiple eval() calls penalize the score cumulatively."""
		multi = tmp_path / "multi.py"
		multi.write_text("eval('a')\neval('b')\neval('c')\n")
		result = self._run_smith(smith, tmp_path)
		assert result["security_score"] <= 70.0

	def test_venv_directory_skipped(self, smith, tmp_path):
		"""Files under .venv/ directories are excluded from scanning."""
		venv_dir = tmp_path / ".venv" / "lib"
		venv_dir.mkdir(parents=True)
		(venv_dir / "poison.py").write_text("eval('danger')\n")
		result = self._run_smith(smith, tmp_path)
		venv_findings = [f for f in result["findings"] if ".venv" in f.get("file", "")]
		assert len(venv_findings) == 0

	def test_result_has_required_keys(self, smith, tmp_path):
		"""SmithMinion result always contains the expected schema keys."""
		(tmp_path / "dummy.py").write_text("x = 1\n")
		result = self._run_smith(smith, tmp_path)
		for key in ["status", "findings", "security_score", "files_scanned", "lines_analyzed", "duration"]:
			assert key in result, f"Missing key: {key}"


class TestOracleMinion:
	"""Oracle entrega FUENTES (dossier), no una síntesis fingida.

	Regresión 2026-11-26: `if engine.llm` se evaluaba antes del lazy-load, así que
	Oracle siempre devolvía la concatenación cruda etiquetada como «ORACLE
	SYNTHESIS». Ahora el modo es explícito y la síntesis es opcional (daemon).
	"""

	@pytest.fixture
	def oracle(self):
		from red_pill.swarm.agents.oracle import OracleMinion

		return OracleMinion()

	def _hit(self, content, title="Nota", score=0.9, point_id="abc12345"):
		hit = MagicMock()
		hit.payload = {"content": content, "title": title}
		hit.score = score
		hit.id = point_id
		return hit

	@patch("red_pill.memory.MemoryManager")
	def test_raw_por_defecto_devuelve_fuentes(self, mock_mm_cls, oracle):
		mock_mm = MagicMock()
		mock_mm.search_and_reinforce.side_effect = [
			[self._hit("El Búnker es soberano.", "Soberanía")],
			[self._hit("El pacto 770 sigue vivo.", "Pacto")],
		]
		mock_mm_cls.return_value = mock_mm
		result = run(oracle.execute("identidad"))
		assert result["mode"] == "raw"
		assert result["synthesis"] is None
		assert result["source_count"] == 2
		assert [h["collection"] for h in result["hits"]] == ["work_memories", "social_memories"]
		assert result["hits"][0]["title"] == "Soberanía"

	@patch("red_pill.memory.MemoryManager")
	def test_synthesize_opcional_usa_el_daemon(self, mock_mm_cls, oracle, monkeypatch):
		mock_mm = MagicMock()
		mock_mm.search_and_reinforce.return_value = [self._hit("fragmento")]
		mock_mm_cls.return_value = mock_mm
		llamadas = []

		def fake(background, query, timeout=60):
			llamadas.append((background, query))
			return "Resumen del daemon"

		monkeypatch.setattr("red_pill.swarm.agents.oracle._synthesize_with_daemon", fake)
		result = run(oracle.execute("pregunta", synthesize=True))
		assert result["mode"] == "synthesized"
		assert result["synthesis"] == "Resumen del daemon"
		assert llamadas and llamadas[0][1] == "pregunta"

	@patch("red_pill.memory.MemoryManager")
	def test_si_el_daemon_falla_se_entrega_crudo(self, mock_mm_cls, oracle, monkeypatch):
		mock_mm = MagicMock()
		mock_mm.search_and_reinforce.return_value = [self._hit("fragmento")]
		mock_mm_cls.return_value = mock_mm
		monkeypatch.setattr("red_pill.swarm.agents.oracle._synthesize_with_daemon", lambda *a, **k: None)
		result = run(oracle.execute("pregunta", synthesize=True))
		assert result["mode"] == "raw"
		assert result["synthesis"] is None

	@patch("red_pill.memory.MemoryManager")
	def test_dossier_recorta_a_tres_por_coleccion(self, mock_mm_cls, oracle):
		"""La cascada evocativa añade puntos más allá del limit; el dossier no."""
		mock_mm = MagicMock()
		mock_mm.search_and_reinforce.return_value = [self._hit(f"nota {i}") for i in range(7)]
		mock_mm_cls.return_value = mock_mm
		result = run(oracle.execute("q"))
		assert result["source_count"] == 6  # 3 work + 3 social, pese a 7 por colección

	@patch("red_pill.memory.MemoryManager")
	def test_sin_hits_no_inventa_contexto(self, mock_mm_cls, oracle):
		from red_pill.swarm.agents.oracle import render_report

		mock_mm = MagicMock()
		mock_mm.search_and_reinforce.return_value = []
		mock_mm_cls.return_value = mock_mm
		result = run(oracle.execute("desconocido"))
		assert result["source_count"] == 0
		assert "Sin resultados" in render_report(result)

	def test_render_raw_agrupa_por_coleccion_y_cita_ids(self):
		from red_pill.swarm.agents.oracle import render_report

		result = {
			"mode": "raw",
			"query": "q",
			"hits": [
				{"collection": "work_memories", "score": 0.663, "title": "Nota A", "point_id": "7438d580-xxxx", "content": "cuerpo A"},
				{"collection": "social_memories", "score": 0.4, "title": "Nota B", "point_id": "14244a8a", "content": "cuerpo B"},
			],
		}
		text = render_report(result)
		assert text.startswith("ORACLE CONTEXT (raw)")
		assert "## work_memories" in text and "## social_memories" in text
		assert "id=7438d580" in text and "0.663" in text
		assert "ORACLE SYNTHESIS" not in text

	def test_render_sintetizado_marca_lossy_y_lista_fuentes(self):
		from red_pill.swarm.agents.oracle import render_report

		result = {
			"mode": "synthesized",
			"query": "q",
			"synthesis": "Resumen breve",
			"hits": [{"collection": "work_memories", "score": 0.9, "title": "Nota A", "point_id": "abc12345", "content": "x"}],
		}
		text = render_report(result)
		assert text.startswith("ORACLE SYNTHESIS (lossy)")
		assert "Resumen breve" in text
		assert "Fuentes:" in text and "id=abc12345" in text

	def test_render_recorta_cuerpos_largos(self):
		from red_pill.swarm.agents.oracle import render_report

		result = {"mode": "raw", "query": "q", "hits": [{"collection": "work_memories", "score": 0.9, "title": "L", "point_id": "p", "content": "x" * 900}]}
		text = render_report(result, max_chars=100)
		assert "x" * 100 + "…" in text
		assert "x" * 900 not in text


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


class TestCommandMinionTimeout:
	"""CommandMinion honra su cota de tiempo (2026-08-14).

	Antes ignoraba el kwarg `timeout` por completo (`communicate()` sin
	`wait_for`): una etapa command colgada bloqueaba el runner indefinidamente,
	con el run-lock R6 impidiendo que otro runner entrara.
	"""

	@staticmethod
	def _minion():
		from red_pill.swarm.agents.command import CommandMinion

		return CommandMinion()

	def test_hanging_command_is_killed_at_timeout(self):
		result = run(self._minion().execute("", command=["sleep", "30"], timeout=1))
		assert result["status"] == "failed"
		assert result["returncode"] == 124  # convención de timeout (ScriptJobDriver)
		assert result["timed_out"] is True
		assert result["duration"] < 15, "el comando no se abatió: siguió corriendo"

	def test_fast_command_unaffected_by_timeout(self):
		result = run(self._minion().execute("", command=["echo", "hola"], timeout=30))
		assert result["status"] == "success"
		assert result["returncode"] == 0
		assert result["stdout"] == "hola"
		assert "timed_out" not in result

	def test_no_timeout_kwarg_still_works(self):
		result = run(self._minion().execute("", command=["echo", "sin cota"]))
		assert result["status"] == "success" and result["stdout"] == "sin cota"

	def test_timeout_kills_process_tree(self, tmp_path):
		"""El abatimiento mata el ÁRBOL, no solo el líder (incidente 2026-09-17:
		un `uv run`/wrapper dejaba a sus hijos huérfanos consumiendo GPU y
		manteniendo el pipe abierto → communicate() colgado)."""
		import time

		pid_file = tmp_path / "child.pid"
		cmd = [
			"python3",
			"-c",
			(f"import subprocess, time;p = subprocess.Popen(['sleep', '4711']);open({str(pid_file)!r}, 'w').write(str(p.pid));time.sleep(300)"),
		]
		result = run(self._minion().execute("", command=cmd, timeout=2))
		assert result["returncode"] == 124
		# dar un instante al SIGKILL del grupo
		time.sleep(0.3)
		child_pid = int(pid_file.read_text())
		# el hijo del wrapper también debe haber muerto
		with pytest.raises(ProcessLookupError):
			os.kill(child_pid, 0)
