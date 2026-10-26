"""Mapeo Telegram→alma (B-02): continuity estable, leg y espejo."""

from __future__ import annotations

from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry
from red_pill.telegram.session import TelegramSessionManager


def _manager(tmp_path, *, mapping=True):
	return TelegramSessionManager(
		conv_dir=tmp_path / "conversations",
		db_path=str(tmp_path / "session.db"),
		soul_mapping=mapping,
	)


def test_telegram_maps_session_to_stable_soul_and_mirror(tmp_path):
	tsm = _manager(tmp_path)
	session = tsm.create_session("user-42")
	assert session["continuity_id"]
	assert session["mission_id"] == "mission:telegram"
	assert session["continuity_id"] == tsm._soul_continuity("user-42")

	registry = SessionRegistry(str(tmp_path / "session.db"))
	leg = registry.get_by_originator(f"telegram:{session['id']}")
	assert leg is not None
	assert leg["continuity_id"] == session["continuity_id"]
	assert leg["mission_id"] == "mission:telegram"

	tsm.append_message(session["id"], "user", "hola")
	tsm.append_message(session["id"], "assistant", "respuesta")
	mirror = SessionMirror(str(tmp_path / "session.db"))
	turns = mirror.context_turns(session["continuity_id"])
	assert [t["role"] for t in turns] == ["user", "assistant"]
	assert [t["content"] for t in turns] == ["hola", "respuesta"]
	assert turns[0]["source"] == "telegram"


def test_telegram_rotation_keeps_soul_and_expires_old_leg(tmp_path):
	tsm = _manager(tmp_path)
	old = tsm.create_session("user-42")
	tsm.append_message(old["id"], "user", "antes")
	new = tsm.create_session("user-42")
	assert new["id"] != old["id"]
	assert new["continuity_id"] == old["continuity_id"]

	registry = SessionRegistry(str(tmp_path / "session.db"))
	assert tsm.mark_for_deletion(old["id"]) is True
	old_leg = registry.get_by_originator(f"telegram:{old['id']}")
	assert old_leg["ttl_state"] == "expired"
	new_leg = registry.get_by_originator(f"telegram:{new['id']}")
	assert new_leg["continuity_id"] == old["continuity_id"]
	assert new_leg["ttl_state"] == "active"


def test_telegram_mapping_off_is_unchanged(tmp_path):
	tsm = _manager(tmp_path, mapping=False)
	session = tsm.create_session("user-42")
	assert "continuity_id" not in session
	assert "mission_id" not in session
	tsm.append_message(session["id"], "user", "hola")
	mirror = SessionMirror(str(tmp_path / "session.db"))
	assert mirror.read_turns(tsm._soul_continuity("user-42")) == []
