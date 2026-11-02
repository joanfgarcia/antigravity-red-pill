"""opencode v2: las sesiones nuevas vuelven a llegar a Memento (2026-11-02).

La migración a v2 movió el contenido a `session_message` y dejó de escribir
`message`/`part`. La fuente seguía leyendo v1, así que **toda** sesión posterior
quedó invisible: la última renderizada fue del 27-oct y la de hoy tenía 793
mensajes sin ver. Este test fija el puente v2 → forma message/part.
"""

import json
import sqlite3

from red_pill.chronicle_sources.opencode import OpencodeSourcePlugin


def _db(tmp_path, *, v2: bool):
	path = tmp_path / "opencode.db"
	con = sqlite3.connect(path)
	con.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INT, data TEXT)")
	con.execute("CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT, time_created INT, data TEXT)")
	if v2:
		con.execute(
			"CREATE TABLE session_message (id TEXT, session_id TEXT, type TEXT, seq INT, time_created INT, time_updated INT, data TEXT)"
		)
		rows = [
			("m1", "ses_v2", "user", 1, 1_800_000_000_000, 0, json.dumps({"text": "hola"})),
			(
				"m2",
				"ses_v2",
				"assistant",
				2,
				1_800_000_001_000,
				0,
				json.dumps(
					{
						"content": [
							{"type": "reasoning", "text": "pienso"},
							{"type": "text", "text": "qué tal"},
							{"type": "tool", "name": "bash", "state": {"input": {"cmd": "ls"}, "output": "a.txt"}},
						]
					}
				),
			),
			("m3", "ses_v2", "idle", 3, 1_800_000_002_000, 0, "{}"),
		]
		con.executemany("INSERT INTO session_message VALUES (?,?,?,?,?,?,?)", rows)
	con.commit()
	con.close()
	return path


def test_descubre_y_carga_la_sesion_v2(tmp_path):
	plugin = OpencodeSourcePlugin(db_path=_db(tmp_path, v2=True))
	assert plugin.discover() == [("ses_v2", 2)]  # user + assistant; `idle` no cuenta
	turns = plugin.load("ses_v2")
	assert [t["role"] for t in turns] == ["user", "assistant"]
	assert turns[0]["content"] == "hola"
	assert "qué tal" in turns[1]["content"]
	assert "bash" in turns[1]["content"]  # la tool se compacta a su marcador
	assert not any("pienso" in t["content"] for t in turns)  # reasoning fuera


def test_sin_tabla_v2_sigue_leyendo_v1(tmp_path):
	path = _db(tmp_path, v2=False)
	con = sqlite3.connect(path)
	con.execute("INSERT INTO message VALUES ('m1','ses_v1',1800000000000,?)", (json.dumps({"role": "user", "time": {"created": 1800000000000}}),))
	con.execute("INSERT INTO part VALUES ('p1','m1','ses_v1',1800000000000,?)", (json.dumps({"type": "text", "text": "viejo"}),))
	con.commit()
	con.close()
	plugin = OpencodeSourcePlugin(db_path=path)
	assert plugin.discover() == [("ses_v1", 1)]
	assert plugin.load("ses_v1")[0]["content"] == "viejo"
