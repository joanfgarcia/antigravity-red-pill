import os
import sqlite3
from typing import Generator

import pytest

from red_pill.core.inbox import MinionInbox


@pytest.fixture
def temp_inbox(tmp_path) -> Generator[MinionInbox, None, None]:
	"""Provides a fresh MinionInbox connected to a temporary SQLite database."""
	db_path = os.path.join(tmp_path, "test_minion_inbox.db")
	inbox = MinionInbox(db_path=db_path)
	yield inbox
	try:
		if os.path.exists(db_path):
			import gc

			gc.collect()
			os.remove(db_path)
	except PermissionError:
		pass


def test_inbox_initialization(temp_inbox: MinionInbox):
	"""Verify the SQLite database and table are created successfully."""
	assert os.path.exists(temp_inbox.db_path)
	with sqlite3.connect(temp_inbox.db_path) as conn:
		cursor = conn.cursor()
		cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inbox'")
		assert cursor.fetchone() is not None


def test_drop_and_get_unread(temp_inbox: MinionInbox):
	"""Verify that dropped reports are saved and appear as unread."""
	temp_inbox.drop_report(event_id="evt_123", source="AgentSmith", status="success", content="Audit complete")
	temp_inbox.drop_report(event_id="evt_456", source="Keymaker", status="failed", content="Storage full")

	unread = temp_inbox.get_unread(limit=10)
	assert len(unread) == 2

	# Ordered by timestamp DESC, so latest (evt_456) should be first
	assert unread[0]["event_id"] == "evt_456"
	assert unread[0]["source"] == "Keymaker"
	assert unread[0]["status"] == "failed"
	assert unread[0]["is_read"] == 0

	assert unread[1]["event_id"] == "evt_123"


def test_drop_report_idempotente_por_event_id(temp_inbox: MinionInbox):
	"""D2: el mismo event_id dos veces registra UNA sola fila (reintento del minion)."""
	temp_inbox.drop_report(event_id="evt_dup", source="AgentSmith", status="success", content="primera")
	temp_inbox.drop_report(event_id="evt_dup", source="AgentSmith", status="success", content="segunda")

	with sqlite3.connect(temp_inbox.db_path) as conn:
		rows = conn.execute("SELECT content FROM inbox WHERE event_id = ?", ("evt_dup",)).fetchall()
	assert len(rows) == 1, "el segundo drop no debe duplicar la fila"
	assert rows[0][0] == "primera", "queda la primera versión (fire-and-forget)"

	# Un event_id distinto sí entra: la idempotencia es por id, no global.
	temp_inbox.drop_report(event_id="evt_otro", source="AgentSmith", status="success", content="tercera")
	assert len(temp_inbox.get_unread(limit=10)) == 2


def test_drop_report_idempotente_bajo_carrera(temp_inbox: MinionInbox):
	"""D2 en concurrente: dos minions con el MISMO event_id a la vez → una fila.

	Un SELECT previo seguido de INSERT no bastaría aquí: la ventana entre ambos
	permite el duplicado. Por eso el filtro vive en la propia sentencia.
	"""
	import threading

	def _drop():
		# Conexión/instancia propia, como harían dos procesos minion distintos.
		MinionInbox(db_path=temp_inbox.db_path).drop_report(
			event_id="evt_race", source="AgentSmith", status="success", content="carrera"
		)

	threads = [threading.Thread(target=_drop) for _ in range(8)]
	for t in threads:
		t.start()
	for t in threads:
		t.join()

	with sqlite3.connect(temp_inbox.db_path) as conn:
		n = conn.execute("SELECT COUNT(*) FROM inbox WHERE event_id = ?", ("evt_race",)).fetchone()[0]
	assert n == 1, f"el mismo event_id bajo carrera debe registrarse una sola vez (got {n})"


def test_mark_as_read(temp_inbox: MinionInbox):
	"""Verify that reading a report hides it from get_unread."""
	temp_inbox.drop_report(event_id="evt_789", source="Oracle", status="success", content="Data found")
	unread = temp_inbox.get_unread()
	assert len(unread) == 1

	report_id = unread[0]["id"]
	temp_inbox.mark_as_read([report_id])

	# Fetching unread again should be empty
	assert len(temp_inbox.get_unread()) == 0


def test_purge_read(temp_inbox: MinionInbox):
	"""Verify that purge_read permanently deletes read reports."""
	temp_inbox.drop_report(event_id="evt_001", source="Sys", status="up", content="Ping")
	temp_inbox.drop_report(event_id="evt_002", source="Sys", status="down", content="Pong")

	all_reports = temp_inbox.get_unread()
	assert len(all_reports) == 2

	# Mark only one as read
	report_to_purge = [r for r in all_reports if r["event_id"] == "evt_001"][0]["id"]
	temp_inbox.mark_as_read([report_to_purge])

	temp_inbox.purge_read()

	# The unread one should still exist
	remaining = temp_inbox.get_unread()
	assert len(remaining) == 1
	assert remaining[0]["event_id"] == "evt_002"

	# Verify the read one is physically gone
	with sqlite3.connect(temp_inbox.db_path) as conn:
		cursor = conn.cursor()
		cursor.execute("SELECT COUNT(*) FROM inbox")
		count = cursor.fetchone()[0]
		assert count == 1
