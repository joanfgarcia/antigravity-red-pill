"""
Hito 8: unit tests for scripts/quarantine_fragments.py.
No real Qdrant — client is mocked. Verifies the upsert→verify→delete ordering
(no data loss) and that dry-run writes nothing.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from quarantine_fragments import dry_run_collection, quarantine_collection  # noqa: E402


def _rec(rid, parent_id):
	r = MagicMock()
	r.id = rid
	r.vector = [0.1] * 384
	r.payload = {"content": f"frag {rid}", "parent_id": parent_id, "_is_fragment": True, "immune": True}
	return r


def test_quarantine_moves_and_deletes_in_safe_order():
	client = MagicMock()
	client.collection_exists.return_value = True
	client.scroll.side_effect = [
		([_rec("a", "p1"), _rec("b", "p1")], "off1"),
		([_rec("c", "p2")], None),
	]
	# Verification retrieve returns as many points as requested → upsert confirmed.
	client.retrieve.side_effect = lambda **kw: [object() for _ in kw["ids"]]

	res = quarantine_collection(client, "work_memories", batch_size=128, now=1234.0)

	assert res["moved"] == 3
	assert res["failed"] == 0
	assert res["orphan_parents"] == 2  # p1, p2

	# Per batch: upsert to archive BEFORE delete from source.
	names = [c[0] for c in client.mock_calls]
	assert names.index("upsert") < names.index("delete")

	# The moved points must be de-immunized and tagged.
	first_upsert_points = client.upsert.call_args_list[0].kwargs["points"]
	assert all(p.payload["immune"] is False for p in first_upsert_points)
	assert all(p.payload["_quarantined_from"] == "work_memories" for p in first_upsert_points)
	assert all(p.payload["_quarantined_at"] == 1234.0 for p in first_upsert_points)


def test_quarantine_does_not_delete_when_verification_fails():
	client = MagicMock()
	client.collection_exists.return_value = True
	client.scroll.side_effect = [([_rec("a", "p1")], None)]
	client.retrieve.return_value = []  # verification fails: nothing landed

	res = quarantine_collection(client, "work_memories", batch_size=128, now=1.0)

	assert res["moved"] == 0
	assert res["failed"] == 1
	client.delete.assert_not_called()  # source preserved


def test_dry_run_writes_nothing():
	client = MagicMock()
	client.collection_exists.return_value = True
	client.scroll.side_effect = [([_rec("a", "p1"), _rec("b", "p2")], None)]

	res = dry_run_collection(client, "work_memories")

	assert res["fragments"] == 2
	assert res["orphan_parents"] == 2
	client.upsert.assert_not_called()
	client.delete.assert_not_called()
