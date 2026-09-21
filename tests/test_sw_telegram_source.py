"""AD-034/D15 — fuente chronicle de Telegram + exclusión en opencode."""

from __future__ import annotations

import json

from red_pill.chronicle_sources.telegram import TelegramSourcePlugin


def _write(conv_dir, sid, steps, created="2026-05-28T18:01:17.970534Z"):
	d = {"id": sid, "status": "active", "channel_user_id": "u1", "summary": {"createdAt": created, "lastUpdatedAt": created, "summary": "x"}, "steps": steps}
	(conv_dir / f"{sid}.json").write_text(json.dumps(d), encoding="utf-8")


def test_telegram_source_discover_load_y_prefix(tmp_path):
	_write(tmp_path, "abc", [
		{"intent": "USER", "message": {"text": "hola"}},
		{"intent": "ASSISTANT", "message": {"text": "qué tal"}},
	])
	sp = TelegramSourcePlugin(conv_dir=tmp_path)
	assert sp.discover() == [("abc", 2)]
	msgs = sp.load("abc")
	assert [m["role"] for m in msgs] == ["user", "assistant"]
	assert msgs[0]["content"] == "hola"
	assert sp.qualify("abc") == "telegram:abc"
	assert sp.workspace_of("abc") is None


def test_opencode_source_excluye_sesiones_telegram(tmp_path, monkeypatch):
	import red_pill.swarm.bridges.opencode as br
	from red_pill.chronicle_sources import opencode as oc

	db = tmp_path / "o.db"
	db.write_text("")
	src = oc.OpencodeSourcePlugin(db_path=db)

	class FakeCon:
		def execute(self, q):
			return type("R", (), {"fetchall": lambda self: [("sid1", 5), ("sid2", 3)]})()

		def close(self):
			pass

	monkeypatch.setattr(src, "_connect", lambda: FakeCon())
	monkeypatch.setattr(br, "read_opencode_origins", lambda: {"sid1": {"origin": "telegram"}})
	assert src.discover() == [("sid2", 3)]
