import json
import sqlite3

from red_pill.coro import mailbox


def _event(**over):
	ev = {
		"event_id": "a" * 32,
		"mission_id": "repo:sharing",
		"to_continuity": "01a187ba-a9f6-718d-b9e1-d531b8d7a947",
		"verb": "notify",
		"thread_id": "E-test",
		"ref": None,
		"hop": 0,
		"hop_max": 2,
		"expects_reply": False,
		"value_class": "now",
		"expires_at": 9999999999.0,
		"summary": "TEXTO QUE NO DEBE VIAJAR EN EL SOBRE",
	}
	ev.update(over)
	return ev


def _rows(db_path):
	con = sqlite3.connect(db_path)
	con.row_factory = sqlite3.Row
	try:
		return [dict(r) for r in con.execute("SELECT * FROM outbox ORDER BY id")]
	finally:
		con.close()


def test_publish_inserts_envelope_without_text(tmp_path):
	db = tmp_path / "events.db"
	assert mailbox.publish_message(_event(), db_path=str(db)) is True
	rows = _rows(db)
	assert len(rows) == 1
	assert rows[0]["channel"] == "soul"
	assert rows[0]["channel_user_id"] == _event()["to_continuity"]
	assert rows[0]["status"] == "PENDING"
	payload = json.loads(rows[0]["payload"])
	assert payload["event_id"] == "a" * 32
	assert payload["continuity_id"] == _event()["to_continuity"]
	assert payload["mission_id"] == "repo:sharing"
	assert "summary" not in payload
	assert "TEXTO QUE NO DEBE VIAJAR" not in rows[0]["payload"]


def test_publish_is_idempotent(tmp_path):
	db = tmp_path / "events.db"
	assert mailbox.publish_message(_event(), db_path=str(db)) is True
	assert mailbox.publish_message(_event(), db_path=str(db)) is True
	assert len(_rows(db)) == 1


def test_publish_rejects_event_without_target(tmp_path):
	db = tmp_path / "events.db"
	assert mailbox.publish_message(_event(to_continuity=None), db_path=str(db)) is False
	assert not db.exists()


def test_publish_never_raises_on_bad_db(tmp_path):
	bad = tmp_path / "nope" / "events.db"
	# El directorio no existe: init_db lo crea; forzamos un fallo con un fichero
	# que no es SQLite.
	bad.parent.mkdir(parents=True, exist_ok=True)
	bad.write_text("not a sqlite db")
	assert mailbox.publish_message(_event(), db_path=str(bad)) is False
