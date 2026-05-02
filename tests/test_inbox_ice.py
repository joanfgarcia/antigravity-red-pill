import base64
import os
import sqlite3
import tempfile

import pytest

import red_pill.config as cfg
from red_pill.core.inbox import MinionInbox


@pytest.fixture
def temp_db():
	fd, path = tempfile.mkstemp()
	os.close(fd)
	yield path
	os.remove(path)


def test_inbox_ice_disabled(temp_db):
	cfg.ICE_MODE_ENABLED = False
	inbox = MinionInbox(db_path=temp_db)
	inbox.drop_report("event-1", "test", "success", '{"key": "value"}')

	# Verify raw JSON is in db
	with sqlite3.connect(temp_db) as conn:
		cursor = conn.cursor()
		cursor.execute("SELECT content FROM inbox WHERE event_id='event-1'")
		content = cursor.fetchone()[0]
		assert content == '{"key": "value"}'

	unread = inbox.get_unread()
	assert len(unread) == 1
	assert unread[0]["content"] == '{"key": "value"}'


def test_inbox_ice_enabled(temp_db):
	cfg.ICE_MODE_ENABLED = True
	inbox = MinionInbox(db_path=temp_db)

	if inbox.mls_group is None:
		pytest.skip("pure-mls not available or failed to load")

	inbox.drop_report("event-2", "test", "success", '{"key": "secret"}')

	# Verify base64 blob is in db
	with sqlite3.connect(temp_db) as conn:
		cursor = conn.cursor()
		cursor.execute("SELECT content FROM inbox WHERE event_id='event-2'")
		content = cursor.fetchone()[0]
		assert content != '{"key": "secret"}'
		# Should be base64 decodable
		try:
			base64.b64decode(content)
		except Exception:
			pytest.fail("Content is not base64 encoded")

	# Verify we can decrypt it
	unread = inbox.get_unread()
	assert len(unread) == 1
	assert unread[0]["content"] == '{"key": "secret"}'

	cfg.ICE_MODE_ENABLED = False
