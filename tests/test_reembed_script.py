"""
Hito 7: unit tests for scripts/reembed_collections.py pure logic.
No real Qdrant — client and embedding engine are mocked.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from reembed_collections import load_cursor, reembed_collection, save_cursor  # noqa: E402


def test_cursor_roundtrip(tmp_path):
	path = tmp_path / "reembed_cursor.json"
	assert load_cursor(path) == {}  # missing file → empty
	save_cursor(path, {"work_memories": "offset-abc"})
	assert load_cursor(path) == {"work_memories": "offset-abc"}


def _rec(rid, content):
	r = MagicMock()
	r.id = rid
	r.payload = {"content": content} if content is not None else {}
	return r


def test_reembed_execute_skips_contentless_and_paginates(tmp_path):
	client = MagicMock()
	client.collection_exists.return_value = True
	# Batch 1: one good, one without content (skipped). Batch 2: one good, end.
	client.scroll.side_effect = [
		([_rec(1, "hola mundo"), _rec(2, None)], "off1"),
		([_rec(3, "otro engrama")], None),
	]
	engine = MagicMock()
	engine.get_vector.return_value = [0.1] * 384

	cursor_path = tmp_path / "cursor.json"
	res = reembed_collection(client, engine, "work_memories", batch_size=256, cursor={}, cursor_path=cursor_path, dry_run=False)

	assert res == {"reembedded": 2, "skipped": 1}
	assert client.update_vectors.call_count == 2  # one write per non-empty batch
	assert engine.get_vector.call_count == 2  # contentless record never embedded
	# Finished collection → cursor entry cleared.
	assert load_cursor(cursor_path) == {}


def test_reembed_dry_run_writes_nothing(tmp_path):
	client = MagicMock()
	client.collection_exists.return_value = True
	client.count.return_value = MagicMock(count=42)
	engine = MagicMock()

	res = reembed_collection(client, engine, "work_memories", batch_size=256, cursor={}, cursor_path=tmp_path / "c.json", dry_run=True)

	assert res == {"reembedded": 0, "skipped": 0}
	client.update_vectors.assert_not_called()
	client.scroll.assert_not_called()
	engine.get_vector.assert_not_called()


def test_reembed_missing_collection_is_noop(tmp_path):
	client = MagicMock()
	client.collection_exists.return_value = False
	engine = MagicMock()

	res = reembed_collection(client, engine, "ghost", batch_size=256, cursor={}, cursor_path=tmp_path / "c.json", dry_run=False)

	assert res == {"reembedded": 0, "skipped": 0}
	client.scroll.assert_not_called()
