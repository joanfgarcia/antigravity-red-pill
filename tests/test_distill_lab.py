"""Unit tests for tools/distill_lab.py harness."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
	sys.path.insert(0, tools_dir)


def test_distill_lab_chunk_cmd():
	cmd = [
		sys.executable,
		"tools/distill_lab.py",
		"chunk",
		"--text",
		"USER: Hola Aleth.\nASSISTANT: Hola Joan, ¿en qué estamos trabajando hoy?\nUSER: En el destilador.",
		"--size",
		"80",
	]
	res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).parent.parent))
	assert res.returncode == 0
	assert "[CHUNK EVAL]" in res.stdout
	assert "chunk(s) producidos" in res.stdout


def test_distill_lab_telegram_cmd(tmp_path):
	telegram_file = tmp_path / "test_chat.json"
	telegram_file.write_text(
		json.dumps([{"text": "USER: Estaba en Porto Pi comprando un Emilio Moro Reserva para Carmen."}]),
		encoding="utf-8",
	)

	mock_distill = {
		"summary": "Prueba de compra",
		"emotion": "neutral",
		"intensity": 0.5,
		"category": "social",
		"texture": "",
		"lang": "es",
		"relics": [],
	}
	mock_hub = {"title": "Título de prueba", "summary": "Resumen maestro", "texture": "", "lang": "es"}

	import distill_lab

	with patch("distill_lab.distill_engram", return_value=mock_distill), patch("distill_lab.synthesize_hub_v2", return_value=mock_hub):
		with patch.object(sys, "argv", ["distill_lab.py", "telegram", "--file", str(telegram_file)]):
			distill_lab.main()


def test_distill_lab_fixtures_cmd():
	mock_distill = {
		"summary": "Prueba de engrama fixture",
		"emotion": "neutral",
		"intensity": 0.5,
		"category": "social",
		"texture": "",
		"lang": "es",
		"relics": [],
	}
	mock_hub = {"title": "Título fixture", "summary": "Resumen fixture", "texture": "", "lang": "es"}

	import distill_lab

	with patch("distill_lab.distill_engram", return_value=mock_distill), patch("distill_lab.synthesize_hub_v2", return_value=mock_hub):
		with patch.object(sys, "argv", ["distill_lab.py", "fixtures"]):
			distill_lab.main()


def test_distill_lab_upgrade_all_cmd():
	mock_distill = {
		"summary": "Resumen re-destilado en 1ª persona",
		"emotion": "joy",
		"intensity": 0.8,
		"category": "social",
		"texture": "Textura autobiográfica",
		"lang": "es",
		"relics": ["Cita literal"],
	}
	mock_hub = {"title": "Título upgrade", "summary": "Resumen maestro upgrade", "texture": "Textura maestra", "lang": "es"}
	mock_mm = MagicMock()
	mock_client = mock_mm.client
	mock_client.collection_exists.return_value = True

	point1 = MagicMock(id="p1", payload={"summary": "Joan me informó...", "content": "USER: Hola Aleth..."})
	mock_client.scroll.side_effect = [([point1], None), ([], None)]

	import distill_lab

	with (
		patch("red_pill.memory.MemoryManager", return_value=mock_mm),
		patch("distill_lab.distill_engram", return_value=mock_distill),
		patch("distill_lab.synthesize_hub_v2", return_value=mock_hub),
	):
		with patch.object(sys, "argv", ["distill_lab.py", "upgrade-all", "--limit", "5"]):
			distill_lab.main()
