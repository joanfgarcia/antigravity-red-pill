"""P1: Axon model + normalize_associations — mixed-format tolerance."""

from red_pill.schemas import Axon, normalize_associations


def test_legacy_string_list():
	axons = normalize_associations(["id-1", "id-2"])
	assert [a.id for a in axons] == ["id-1", "id-2"]
	assert all(a.target_collection is None and a.association_type == "legacy" for a in axons)


def test_object_axon():
	axons = normalize_associations([{"id": "id-9", "target_collection": "work_memories", "weight": 0.85, "association_type": "temporal_semantic"}])
	assert axons[0].target_collection == "work_memories"
	assert axons[0].weight == 0.85
	assert axons[0].is_cross("social_memories") is True
	assert axons[0].is_cross("work_memories") is False


def test_mixed_list_no_str_dict_corruption():
	raw = ["plain-id", {"id": "obj-id", "weight": 0.7, "association_type": "temporal_semantic"}]
	axons = normalize_associations(raw)
	assert [a.id for a in axons] == ["plain-id", "obj-id"]
	assert "{" not in axons[1].id  # the old str(dict) corruption


def test_garbage_tolerated():
	assert normalize_associations(None) == []
	assert normalize_associations("not-a-list") == []
	axons = normalize_associations([None, "", {"no_id": True}, "ok-id", {"id": "", "weight": 1}])
	assert [a.id for a in axons] == ["ok-id"]


def test_weight_clamped():
	axons = normalize_associations([{"id": "x", "weight": 7.5}, {"id": "y", "weight": -1}, {"id": "z", "weight": "bad"}])
	assert [a.weight for a in axons] == [1.0, 0.0, 1.0]


def test_to_payload_roundtrip():
	legacy = normalize_associations(["plain-id"])[0]
	assert legacy.to_payload() == "plain-id"  # lazy migration: legacy stays string
	cross = Axon(id="c1", target_collection="work_memories", weight=0.6, association_type="temporal_semantic")
	restored = normalize_associations([cross.to_payload()])[0]
	assert restored.id == "c1" and restored.target_collection == "work_memories" and restored.weight == 0.6
