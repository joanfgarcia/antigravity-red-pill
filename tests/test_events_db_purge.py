"""events_db_purge: limpieza del events.db de neon-link (outbox FAILED + dead_letters)."""

import asyncio
import sqlite3
from unittest.mock import MagicMock

from red_pill.swarm.agents.janitor_plugins import events_db_purge as mod


def _db(path):
	conn = sqlite3.connect(path)
	conn.executescript(
		"""
		CREATE TABLE inbox (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT);
		CREATE TABLE outbox (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT);
		CREATE TABLE dead_letters (id INTEGER PRIMARY KEY, created_at TEXT);
		CREATE TABLE processed_firebase_messages (id INTEGER PRIMARY KEY, processed_at TEXT);
		INSERT INTO outbox VALUES (1, 'SENT', datetime('now','-10 days'));
		INSERT INTO outbox VALUES (2, 'FAILED', datetime('now','-10 days'));
		INSERT INTO outbox VALUES (3, 'FAILED', datetime('now','-40 days'));
		INSERT INTO outbox VALUES (4, 'PENDING', datetime('now','-40 days'));
		INSERT INTO dead_letters VALUES (1, datetime('now','-10 days'));
		INSERT INTO dead_letters VALUES (2, datetime('now','-40 days'));
		"""
	)
	conn.commit()
	conn.close()


def test_purges_failed_outbox_and_dead_letters_on_their_own_ttl(tmp_path, monkeypatch):
	db = tmp_path / "events.db"
	_db(db)
	monkeypatch.setattr(mod, "get_neon_link_db_path", lambda: db)
	janitor = MagicMock()

	res = asyncio.run(mod.EventsDbPurgePlugin().execute(janitor, {}))

	conn = sqlite3.connect(db)
	outbox = {r[0] for r in conn.execute("SELECT id FROM outbox")}
	dead = {r[0] for r in conn.execute("SELECT id FROM dead_letters")}
	conn.close()
	# SENT > 7d se va; FAILED solo tras 30d (margen de redrive); PENDING nunca.
	assert outbox == {2, 4}
	assert dead == {1}
	assert res["db_events_purged"] == 3
