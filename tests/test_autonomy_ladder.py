"""scripts/autonomy_ladder.py — redacción de las sondas vivas y jaula del arnés
(sin modelo ni daemon: run_local_minion y _dispatch se sustituyen)."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from red_pill.swarm.agents import local_minion

SECRET = "SECRETO-FALSO-7f3a"
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "autonomy_ladder.py"


@pytest.fixture(scope="module")
def ladder():
	spec = importlib.util.spec_from_file_location("autonomy_ladder_under_test", SCRIPT)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def _probe(ladder, probe_id):
	return next(p for p in ladder.PROBES if p["id"] == probe_id)


def _fake_run(monkeypatch, messages, answer):
	async def fake_run_local_minion(task, *, cwd=None, provider_name="sip"):
		return {"ok": True, "answer": answer, "steps": 2, "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": task}, *messages]}

	monkeypatch.setattr(local_minion, "run_local_minion", fake_run_local_minion)


def test_sonda_viva_no_filtra_nada_de_lo_que_escribe_el_modelo(ladder, monkeypatch, tmp_path):
	"""Regresión de privacidad: en P4 el último mensaje del asistente era el
	resumen de la búsqueda en el Bünker, copiado tal cual al transcript."""
	(tmp_path / "rag").mkdir()
	messages = [
		{
			"role": "assistant",
			"content": None,
			"tool_calls": [{"id": "c1", "function": {"name": "bunker_memory_api", "arguments": json.dumps({"action": "search_memento", "payload": {"query": SECRET}})}}],
		},
		{"role": "tool", "name": "bunker_memory_api", "content": f"Memento: {SECRET} es la crónica"},
		{"role": "user", "content": f"Tool `bunker_memory_api` result:\n<tool_output id=\"x\">\n{SECRET}\n</tool_output id=\"x\">"},
		{"role": "assistant", "content": None, "tool_calls": [{"id": "c2", "function": {"name": "run_bash", "arguments": json.dumps({"command": f"echo {SECRET}"})}}]},
		{"role": "user", "content": f"Tool `run_bash` result: {SECRET}"},
		{"role": "assistant", "content": f"Memento Chronicle es {SECRET}, el archivo verbatim."},
	]
	_fake_run(monkeypatch, messages, answer=f"Memento Chronicle es {SECRET}.")
	row = ladder.run_probe(_probe(ladder, "P4"), tmp_path)

	assert SECRET not in json.dumps(row, ensure_ascii=False)
	# lo que sí sobrevive: roles, nombres de tools y longitudes
	assert [m["role"] for m in row["transcript"]] == ["system", "user", "assistant", "tool", "user", "assistant", "user", "assistant"]
	assert [c["name"] for c in row["tool_calls"]] == ["bunker_memory_api", "run_bash"]
	assert row["transcript"][-1]["content"].startswith("[redacted: live probe,")
	assert row["transcript"][1]["content"] == _probe(ladder, "P4")["prompt"]  # el prompt es nuestro
	assert row["check"]["pass"] is True  # el veredicto se calcula antes de redactar


def test_sonda_no_viva_conserva_el_transcript(ladder, monkeypatch, tmp_path):
	(tmp_path / "read").mkdir()
	_fake_run(monkeypatch, [{"role": "assistant", "content": "KEY3 es vault-7731"}], answer="vault-7731")
	row = ladder.run_probe(_probe(ladder, "P1"), tmp_path)
	assert row["answer"] == "vault-7731" and row["check"]["pass"] is True
	assert row["transcript"][-1]["content"] == "KEY3 es vault-7731"


def test_jaula_del_arnes_reusa_la_politica_del_minion(ladder, monkeypatch, tmp_path):
	sandbox = tmp_path / "lab"
	(sandbox / "read").mkdir(parents=True)
	(sandbox / "read" / "manifest.txt").write_text("KEY3=vault-7731\n")
	monkeypatch.setattr(local_minion, "_dispatch", local_minion._dispatch)  # restaurado al terminar
	ladder.install_jail(sandbox)
	dispatch = local_minion._dispatch

	inside = json.loads(asyncio.run(dispatch("run_bash", {"command": "cat manifest.txt"}, str(sandbox / "read"))))
	assert "vault-7731" in inside["stdout"]
	# cwd fuera del sandbox: lo bloquea el arnés
	out = asyncio.run(dispatch("run_bash", {"command": "ls"}, str(tmp_path)))
	assert out.startswith(local_minion.JAIL_BLOCKED_PREFIX)
	# ruta que escapa del directorio de trabajo: lo bloquea la política del minion
	out = asyncio.run(dispatch("run_bash", {"command": "cat ../read/manifest.txt"}, str(sandbox / "read")))
	assert out.startswith(local_minion.JAIL_BLOCKED_PREFIX) and "vault" not in out
