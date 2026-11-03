"""Cierre del caso «carta `soul` agotada por `no_live_body` → dead letter» (S2.2).

Un mensaje para un alma sin cuerpo vivo no es un fallo de transporte: el
destinatario no estaba. Aun así envejecía hasta `dead_letters` a las 24 h y solo
volvía con `neon-link redrive` a mano. Ahora, si el alma recupera cuerpo, el
reconciliador (cada 60 s desde el SoulHub) devuelve la carta a la cola sola.

Los fallos **reales** de transporte no se reviven, y una carta de un alma que
sigue sin cuerpo tampoco: se quedan en dead letter para que el Operador decida.
"""

import sqlite3

import pytest

from red_pill.coro import mailbox

_OUTBOX_DDL = (
	"CREATE TABLE outbox (id INTEGER PRIMARY KEY, message_id TEXT, channel TEXT, channel_user_id TEXT, "
	"cascade_id TEXT, payload TEXT, status TEXT, created_at TEXT, retries INTEGER, next_attempt_at REAL, deliver_after REAL)"
)
_DEAD_DDL = (
	"CREATE TABLE dead_letters (id INTEGER PRIMARY KEY, original_table TEXT, original_id INTEGER, channel TEXT, "
	"channel_user_id TEXT, payload TEXT, error_reason TEXT, created_at TEXT)"
)


@pytest.fixture
def neon_db(tmp_path, monkeypatch):
	db = tmp_path / "neon.db"
	conn = sqlite3.connect(db)
	conn.execute(_OUTBOX_DDL)
	conn.execute(_DEAD_DDL)
	conn.execute(
		"INSERT INTO outbox (id, channel, channel_user_id, payload, status, retries) VALUES (1, 'soul', 'alma-viva', '{\"t\": \"a\"}', 'FAILED', 9)"
	)
	conn.execute(
		"INSERT INTO outbox (id, channel, channel_user_id, payload, status, retries) VALUES (2, 'soul', 'alma-dormida', '{\"t\": \"b\"}', 'FAILED', 9)"
	)
	conn.execute(
		"INSERT INTO outbox (id, channel, channel_user_id, payload, status, retries) VALUES (3, 'soul', 'alma-viva', '{\"t\": \"c\"}', 'FAILED', 9)"
	)
	conn.execute(
		"INSERT INTO dead_letters (original_table, original_id, channel, channel_user_id, payload, error_reason) "
		"VALUES ('outbox', 1, 'soul', 'alma-viva', '{\"t\": \"a\"}', 'no_live_body; gave up after 9 attempts (25.0h old)')"
	)
	conn.execute(
		"INSERT INTO dead_letters (original_table, original_id, channel, channel_user_id, payload, error_reason) "
		"VALUES ('outbox', 2, 'soul', 'alma-dormida', '{\"t\": \"b\"}', 'no_live_body; gave up after 9 attempts (25.0h old)')"
	)
	conn.execute(
		"INSERT INTO dead_letters (original_table, original_id, channel, channel_user_id, payload, error_reason) "
		"VALUES ('outbox', 3, 'soul', 'alma-viva', '{\"t\": \"c\"}', 'transport error: connection refused')"
	)
	conn.commit()
	conn.close()
	monkeypatch.setattr("red_pill.core.paths.get_neon_link_db_path", lambda: db)
	# Solo `alma-viva` tiene cuerpo ahora.
	monkeypatch.setattr(
		"red_pill.core.soul_notify.resolve_live_leg",
		lambda soul: "opencode:ses_x" if soul == "alma-viva" else None,
	)
	return db


def _estado(db):
	conn = sqlite3.connect(db)
	try:
		outbox = dict(conn.execute("SELECT id, status FROM outbox").fetchall())
		letters = conn.execute("SELECT original_id FROM dead_letters").fetchall()
	finally:
		conn.close()
	return outbox, {r[0] for r in letters}


def test_revive_la_carta_del_alma_que_ya_tiene_cuerpo(neon_db):
	resultado = mailbox._revive_soul_dead_letters()

	assert resultado == {"checked": 3, "revived": 1, "skipped": 2}
	outbox, letras = _estado(neon_db)
	assert outbox[1] == "PENDING", "la carta vuelve a la cola"
	assert 1 not in letras


def test_no_revive_la_del_alma_que_sigue_sin_cuerpo(neon_db):
	mailbox._revive_soul_dead_letters()

	outbox, letras = _estado(neon_db)
	assert outbox[2] == "FAILED"
	assert 2 in letras


def test_no_revive_un_fallo_real_de_transporte(neon_db):
	mailbox._revive_soul_dead_letters()

	outbox, letras = _estado(neon_db)
	assert outbox[3] == "FAILED"
	assert 3 in letras


def test_dry_run_no_toca_nada(neon_db):
	resultado = mailbox._revive_soul_dead_letters(dry_run=True)

	assert resultado["revived"] == 0
	outbox, letras = _estado(neon_db)
	assert outbox[1] == "FAILED"
	assert 1 in letras


def test_reconcile_reporta_las_revivadas(neon_db, monkeypatch):
	# `reconcile` abre la session.db; con un fichero temporal basta.
	import red_pill.core.paths as paths

	session_db = neon_db.parent / "session.db"
	monkeypatch.setattr(paths, "get_session_db", lambda: session_db)

	report = mailbox.reconcile(dry_run=True)

	assert "revived" in report and "dead_letters_checked" in report
