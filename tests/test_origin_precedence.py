"""Precedencia provider-first: el source que tiene el raw manda (2026-11-03).

Regla acordada: si una sesión existe en el store de un provider, se renderiza
desde el provider (venga de Telegram o no); el source `telegram` solo sirve lo
que ningún provider cubre. Antes era al revés — el provider excluía las sesiones
`origin=telegram` y Telegram era el hogar fijo.

Hoy no hay solapes (los 16 `origin=telegram` del registro no están en
`opencode.db`), así que el cambio es un no-op medido; estos tests fijan la regla
para cuando el bridge vuelva a ejecutar conversaciones por un provider.
"""

import json
import sqlite3

import pytest

from red_pill.chronicle_sources.opencode import OpencodeSourcePlugin
from red_pill.chronicle_sources.pi import PiSourcePlugin
from red_pill.chronicle_sources.telegram import TelegramSourcePlugin


@pytest.fixture
def opencode_db(tmp_path):
	db = tmp_path / "opencode.db"
	con = sqlite3.connect(db)
	con.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT)")
	con.execute("CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT)")
	for mid, sid in (("m1", "ses_tg"), ("m2", "ses_tg"), ("m3", "ses_plain")):
		con.execute(
			"INSERT INTO message VALUES (?, ?, 1, 1, ?)",
			(mid, sid, json.dumps({"role": "user", "time": {"created": 1}})),
		)
	con.commit()
	con.close()
	return db


def test_opencode_ya_no_excluye_las_sesiones_de_telegram(opencode_db, monkeypatch):
	monkeypatch.setattr(
		"red_pill.swarm.bridges.opencode.read_opencode_origins",
		lambda: {"ses_tg": {"origin": "telegram"}},
	)
	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: opencode_db.parent)

	ids = {cid for cid, _ in OpencodeSourcePlugin(db_path=opencode_db).discover()}

	assert ids == {"ses_tg", "ses_plain"}, "el provider tiene el raw: lo renderiza él"


@pytest.fixture
def pi_sessions(tmp_path):
	base = tmp_path / "sessions"
	(base / "--proj--").mkdir(parents=True)
	records = [
		{"type": "session", "version": 3, "id": "01a10000-0000-7000-8000-000000000001", "cwd": "/proj", "timestamp": "2026-11-03T10:00:00.000Z"},
		{"type": "message", "id": "m1", "timestamp": "2026-11-03T10:00:10.000Z", "message": {"role": "user", "content": "hola", "timestamp": 1}},
		{"type": "message", "id": "m2", "timestamp": "2026-11-03T10:00:20.000Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "hola"}], "timestamp": 2}},
	]
	path = base / "--proj--" / "2026-11-03T10-00-00-000Z_01a10000-0000-7000-8000-000000000001.jsonl"
	path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
	return base


def test_pi_ya_no_excluye_las_sesiones_de_telegram(pi_sessions, monkeypatch):
	monkeypatch.setattr("red_pill.core.origins.telegram_sessions", lambda provider: {"01a10000-0000-7000-8000-000000000001"})

	ids = {cid for cid, _ in PiSourcePlugin(base_dir=pi_sessions).discover()}

	assert any("01a10000" in cid for cid in ids)


@pytest.fixture
def telegram_convs(tmp_path):
	conv = tmp_path / "telegram_conversations"
	conv.mkdir()
	for cid in ("conv-1", "conv-2"):
		(conv / f"{cid}.json").write_text(
			json.dumps({"id": cid, "steps": [{"intent": "USER", "message": {"text": "hola"}}]}),
			encoding="utf-8",
		)
	return conv


def test_telegram_sirve_solo_lo_que_ningun_provider_cubre(telegram_convs, monkeypatch):
	# `conv-1` ya la tiene un provider (registro de orígenes); `conv-2` no.
	monkeypatch.setattr(
		"red_pill.core.origins.read_origins",
		lambda provider=None: {"conv-1": {"origin": "telegram"}} if provider == "opencode" else {},
	)

	ids = {cid for cid, _ in TelegramSourcePlugin(conv_dir=telegram_convs).discover()}

	assert ids == {"conv-2"}, "el provider manda; Telegram es el respaldo"


def test_telegram_sin_cobertura_sigue_siendo_el_hogar(telegram_convs, monkeypatch):
	monkeypatch.setattr("red_pill.core.origins.read_origins", lambda provider=None: {})

	ids = {cid for cid, _ in TelegramSourcePlugin(conv_dir=telegram_convs).discover()}

	assert ids == {"conv-1", "conv-2"}
