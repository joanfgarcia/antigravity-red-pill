"""El extractor del chronicle no puede perder turnos en silencio.

El IDE cerrado deja conversaciones sin volcar y, si nadie lo dice, el buffer de
interacción las purga a los 30 días (incidente 2026-11-01: 6 turnos perdidos).
`_signal_offline_debt` convierte eso en una señal de dolor con enfriamiento.
"""

import importlib.util
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def extractor():
	spec = importlib.util.spec_from_file_location("chronicle_extractor_ls", Path("scripts/chronicle_extractor_ls.py"))
	assert spec and spec.loader
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def _pending(tmp_path: Path, count: int, age_days: float) -> list[Path]:
	files = []
	for i in range(count):
		p = tmp_path / f"conv-{i}.pb"
		p.write_bytes(b"x")
		stamp = time.time() - age_days * 86400
		os.utime(p, (stamp, stamp))
		files.append(p)
	return files


class TestOfflineDebt:
	def test_sin_pendientes_no_hay_senal(self, extractor, tmp_path):
		with patch("red_pill.memory.MemoryManager") as mem:
			extractor._signal_offline_debt([])
		mem.assert_not_called()

	def test_ide_cerrado_declara_la_deuda(self, extractor, tmp_path):
		pending = _pending(tmp_path, 3, age_days=1)
		mem = MagicMock()
		with (
			patch.object(extractor, "get_state_dir", return_value=tmp_path),
			patch("red_pill.memory.MemoryManager", return_value=mem),
		):
			extractor._signal_offline_debt(pending)

		mem.inject_signal.assert_called_once()
		kwargs = mem.inject_signal.call_args.kwargs
		assert kwargs["name"] == "chronicle_blocked_by_ide"
		assert kwargs["signal_type"] == "pain"
		assert kwargs["source"] == "ChronicleExtractor"
		assert "3 conversación" in kwargs["message"]
		assert kwargs["intensity"] == 4.0

	def test_deuda_vieja_sube_la_intensidad(self, extractor, tmp_path):
		pending = _pending(tmp_path, 1, age_days=25)
		mem = MagicMock()
		with (
			patch.object(extractor, "get_state_dir", return_value=tmp_path),
			patch("red_pill.memory.MemoryManager", return_value=mem),
		):
			extractor._signal_offline_debt(pending)
		assert mem.inject_signal.call_args.kwargs["intensity"] == 9.0

	def test_enfriamiento_de_24h(self, extractor, tmp_path):
		state = tmp_path / extractor.DEBT_STATE_FILE
		state.write_text(json.dumps({"signaled_at": time.time() - 60}), encoding="utf-8")
		pending = _pending(tmp_path, 2, age_days=2)
		mem = MagicMock()
		with (
			patch.object(extractor, "get_state_dir", return_value=tmp_path),
			patch("red_pill.memory.MemoryManager", return_value=mem),
		):
			extractor._signal_offline_debt(pending)
		mem.inject_signal.assert_not_called()

	def test_tras_el_enfriamiento_vuelve_a_declarar(self, extractor, tmp_path):
		state = tmp_path / extractor.DEBT_STATE_FILE
		state.write_text(json.dumps({"signaled_at": time.time() - 2 * 86400}), encoding="utf-8")
		pending = _pending(tmp_path, 2, age_days=2)
		mem = MagicMock()
		with (
			patch.object(extractor, "get_state_dir", return_value=tmp_path),
			patch("red_pill.memory.MemoryManager", return_value=mem),
		):
			extractor._signal_offline_debt(pending)
		mem.inject_signal.assert_called_once()
		persisted = json.loads(state.read_text(encoding="utf-8"))
		assert persisted["pending"] == 2

	def test_backlog_no_recuperable_no_declara_deuda(self, extractor, tmp_path):
		"""Las conversaciones que ya superaron el tope de 30 d no se recuperan: no
		se declara una deuda que no se puede pagar (el log sí lo dice)."""
		pending = _pending(tmp_path, 2, age_days=40)
		mem = MagicMock()
		with (
			patch.object(extractor, "get_state_dir", return_value=tmp_path),
			patch("red_pill.memory.MemoryManager", return_value=mem),
		):
			extractor._signal_offline_debt(pending)
		mem.inject_signal.assert_not_called()
		assert not (tmp_path / extractor.DEBT_STATE_FILE).exists()

	def test_canal_roto_no_rompe_el_cron(self, extractor, tmp_path):
		pending = _pending(tmp_path, 1, age_days=3)
		with (
			patch.object(extractor, "get_state_dir", return_value=tmp_path),
			patch("red_pill.memory.MemoryManager", side_effect=RuntimeError("qdrant caído")),
		):
			extractor._signal_offline_debt(pending)  # no debe lanzar
		assert not (tmp_path / extractor.DEBT_STATE_FILE).exists()
