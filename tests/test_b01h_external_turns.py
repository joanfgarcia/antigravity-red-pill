"""B-01h — write-ahead de turnos en arneses externos."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import red_pill.session.external_turns as ext
from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry

CID = "01a1728b-8cc4-7cf8-a9e2-f110b1b5857d"


@pytest.fixture
def state(tmp_path, monkeypatch):
	root = tmp_path / "red-pill" / "state"
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
	monkeypatch.setattr(ext, "get_state_dir", lambda: root)
	return root


@pytest.fixture
def db(tmp_path):
	path = tmp_path / "session.db"
	return path, SessionRegistry(str(path)), SessionMirror(str(path))


def _hook_module(monkeypatch, name, filename):
	path = Path(__file__).resolve().parents[1] / "seeds" / "settings" / "hooks" / filename
	spec = importlib.util.spec_from_file_location(name, path)
	assert spec and spec.loader
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def test_journal_roundtrip_and_supersede(state):
	first = ext.begin_external_turn(provider="opencode", session_id="s1", prompt="uno")
	second = ext.begin_external_turn(provider="opencode", session_id="s1", prompt="dos")
	assert second["request_id"] != first["request_id"]
	archive = state / ext.ARCHIVE_DIR / f"opencode__s1__{ext._safe(first['request_id'])}.json"
	assert archive.is_file()
	data = json.loads(archive.read_text())
	assert data["status"] == "aborted" and data["reason"] == "superseded"


def test_import_completed_turn_into_mirror(state, db):
	path, registry, mirror = db
	registry.upsert_session(originator="opencode:s1", continuity_id=CID, mission_id="repo:next", role="task")
	turn = ext.begin_external_turn(provider="opencode", session_id="s1", prompt="hola")
	ext.finish_external_turn(provider="opencode", session_id="s1", response="mundo", model="m")
	counts = ext.import_external_turns(mirror=mirror, registry=registry, root=state)
	assert counts["completed"] == 1
	rows = mirror.pending_turns(CID, include_aborted=True)
	assert rows == []
	# El archivo cerrado se consume; el espejo conserva user+assistant.
	archives = list((state / ext.ARCHIVE_DIR).glob("*.json"))
	assert archives == []
	con = __import__("sqlite3").connect(path)
	statuses = con.execute("SELECT status FROM session_mirror WHERE request_id=?", (turn["request_id"],)).fetchall()
	con.close()
	assert statuses == [("completed",), ("completed",)]


def test_unregistered_originator_is_not_invented(state, db):
	_, registry, mirror = db
	ext.begin_external_turn(provider="opencode", session_id="ghost", prompt="hola")
	counts = ext.import_external_turns(mirror=mirror, registry=registry, root=state)
	assert counts["skipped"] == 1
	assert list((state / ext.CURRENT_DIR).glob("*.json"))


def test_aborted_turn_keeps_partial_response(state, db):
	_, registry, mirror = db
	registry.upsert_session(originator="pi:s1", continuity_id=CID, mission_id="repo:next", role="task")
	turn = ext.begin_external_turn(provider="pi", session_id="s1", prompt="hola")
	ext.finish_external_turn(provider="pi", session_id="s1", status="aborted", response="a medias", reason="timeout")
	ext.import_external_turns(mirror=mirror, registry=registry, root=state)
	rows = mirror.pending_turns(CID, include_aborted=True)
	assert any(r["request_id"] == turn["request_id"] and r["status"] == "aborted" for r in rows)
	assert any("a medias" in str(r.get("content")) for r in rows)


def test_claude_hooks_write_same_journal(state, monkeypatch, db):
	_, registry, mirror = db
	registry.upsert_session(originator="claude_code:s1", continuity_id=CID, mission_id="repo:next", role="task")
	start = _hook_module(monkeypatch, "b01h_turn_start", "redpill_turn_start.py")
	scribe = _hook_module(monkeypatch, "b01h_scribe", "redpill_scribe.py")
	start._begin_turn({"prompt": "hola", "cwd": "/tmp"}, "s1")
	scribe._finish_turn("s1", "mundo", "claude-x", "completed")
	counts = ext.import_external_turns(mirror=mirror, registry=registry, root=state)
	assert counts["completed"] == 1


def test_el_turno_importado_sale_sellado_con_reloj_e_identidad(state, db):
	"""El agujero que esto cierra (medido 2026-10-30): 20.204 filas del espejo y
	NINGUNA con `global_turn > 0`, así que `fetch_divergent_turns` (D15) no podía
	leer nada. El turno importado tiene que salir con número y con identidad propia.
	"""
	path, registry, mirror = db
	registry.upsert_session(originator="opencode:s1", continuity_id=CID, mission_id="repo:next", role="task")
	ext.begin_external_turn(provider="opencode", session_id="s1", prompt="hola")
	ext.finish_external_turn(provider="opencode", session_id="s1", response="mundo", model="m")
	counts = ext.import_external_turns(mirror=mirror, registry=registry, root=state)
	assert counts["completed"] == 1

	import sqlite3

	con = sqlite3.connect(str(path))
	rows = con.execute(
		"SELECT role, global_turn, turn_id FROM session_mirror WHERE continuity_id = ? ORDER BY seq",
		(CID,),
	).fetchall()
	con.close()

	assert len(rows) == 2, "user + assistant"
	assert all(gt > 0 for _r, gt, _t in rows), f"turnos sin sellar: {rows}"
	assert len({t for _r, _g, t in rows if t}) == 1, "las filas del mismo turno comparten identidad"
	assert rows[0][1] == rows[1][1], "y comparten número de reloj"


def test_un_request_id_repetido_no_se_traga_el_siguiente_turno(state, db):
	"""El id del arnés no identifica: se conserva como procedencia."""
	path, registry, mirror = db
	registry.upsert_session(originator="opencode:s2", continuity_id=CID, mission_id="repo:next", role="task")
	for prompt in ("uno", "dos"):
		ext.begin_external_turn(provider="opencode", session_id="s2", prompt=prompt)
		ext.finish_external_turn(provider="opencode", session_id="s2", response=f"eco {prompt}")
	ext.import_external_turns(mirror=mirror, registry=registry, root=state)

	import sqlite3

	con = sqlite3.connect(str(path))
	turns = [r[0] for r in con.execute(
		"SELECT turn_id FROM session_mirror WHERE continuity_id = ? AND role = 'user'", (CID,)
	)]
	con.close()
	assert len(turns) == 2 and len(set(turns)) == 2, f"dos turnos, dos identidades: {turns}"


def test_un_request_id_repetido_por_el_arnes_no_pierde_el_segundo_turno(state, db):
	"""Dos turnos distintos con el MISMO `request_id` (arnés que reinicia contador).

	Antes: `source_ref = f"{request}:user"` colisionaba, `INSERT OR IGNORE` tiraba
	la fila del segundo turno en silencio. Ahora la clave lleva el contenido.
	"""
	path, registry, mirror = db
	registry.upsert_session(originator="opencode:s3", continuity_id=CID, mission_id="repo:next", role="task")
	current = state / ext.CURRENT_DIR
	current.mkdir(parents=True, exist_ok=True)
	for prompt in ("turno uno", "turno dos"):
		journal = {
			"request_id": "repetido-42",
			"originator": "opencode:s3",
			"prompt": prompt,
			"response": f"eco de {prompt}",
			"status": "completed",
			"started_at": 1793000000.0,
			"finished_at": 1793000001.0,
			"model": "m",
			"provider": "opencode",
			"session_id": "s3",
		}
		(current / f"opencode__s3__{prompt.replace(' ', '_')}.json").write_text(json.dumps(journal))

	ext.import_external_turns(mirror=mirror, registry=registry, root=state)

	import sqlite3

	con = sqlite3.connect(str(path))
	users = con.execute(
		"SELECT turn_id, global_turn, status FROM session_mirror WHERE continuity_id=? AND role='user' ORDER BY seq",
		(CID,),
	).fetchall()
	con.close()
	assert len(users) == 2, f"se perdió un turno: {users}"
	assert len({u[0] for u in users}) == 2, "cada turno con su identidad"
	assert all(u[1] > 0 for u in users), "y sellados con reloj"
