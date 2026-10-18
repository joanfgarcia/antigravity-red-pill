"""Tests del digest determinista OPEN LOOPS (P0-3)."""

from __future__ import annotations

import json

from red_pill.core import open_loops as ol


def _note(desk, target="Operador"):
	notes = desk / "awakening" / "notes"
	notes.mkdir(parents=True, exist_ok=True)
	(notes / "n.md").write_text(f"---\npara: {target}\n---\n\n# Decisión\n", encoding="utf-8")


def _blocked_rfc(desk):
	d = desk / "planner" / "design" / "x"
	d.mkdir(parents=True, exist_ok=True)
	(d / "RFC_X.md").write_text(
		"---\nid: RFC-X\ntype: rfc\nstatus: blocked\nreason: esperando otro RFC\n---\n\n# X\n",
		encoding="utf-8",
	)


def _shards(ws, open_n=2, done_n=1):
	cell = ws / ".cell"
	cell.mkdir(parents=True, exist_ok=True)
	shards = [{"id": f"SHARD-{i}", "status": "OPEN"} for i in range(open_n)]
	shards += [{"id": f"SHARD-D{i}", "status": "DONE"} for i in range(done_n)]
	(cell / "shards.json").write_text(json.dumps({"shards": shards}), encoding="utf-8")


def test_open_loops_vacio(tmp_path):
	(tmp_path / "planner").mkdir()
	assert ol.open_loops_line(desk=tmp_path, workspace=tmp_path) == ""


def test_open_loops_agrega(tmp_path):
	desk = tmp_path / "desk"
	ws = tmp_path / "ws"
	desk.mkdir()
	ws.mkdir()
	_note(desk)
	_blocked_rfc(desk)
	_shards(ws, open_n=2)
	line = ol.open_loops_line(desk=desk, workspace=ws)
	assert line.startswith("OPEN LOOPS: ")
	assert "1 decisión(es) del Operador" in line
	assert "1 RFC blocked/paused" in line
	assert "2 shards OPEN" in line


def test_open_loops_no_lanza_sin_rutas(tmp_path):
	assert ol.open_loops_line(desk=tmp_path / "no", workspace=tmp_path / "no-ws") == ""
