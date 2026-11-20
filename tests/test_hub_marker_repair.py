"""MET-001: el marcador huérfano sin hub posible es residuo y se limpia.

La síntesis exige `HUB_MIN_SESSION_MEMBERS` miembros por sesión, así que una
sesión de uno solo **nunca** tendrá hub: su `hubbed=True` con un `hub_id`
inexistente quedó de una poda. La auto-curación borra esas claves (no borra
memoria) y **no toca** la huérfana de una sesión agrupable: esa es una fuga y
debe seguir encendiendo `hub_integrity_ok`.
"""

import uuid

import pytest
from qdrant_client import models

import red_pill.config as cfg
from red_pill.metabolism.hub_synthesis import HUB_MIN_SESSION_MEMBERS, repair_stale_orphan_markers
from red_pill.metabolism.sw_observability import compute_sw_health

DIM = cfg.VECTOR_SIZE
HUB_ID = str(uuid.uuid5(uuid.NAMESPACE_OID, "hub-de-prueba"))


@pytest.fixture()
def mm(memory_manager):
	existing = {c.name for c in memory_manager.client.get_collections().collections}
	for col in ("work_memories", "social_memories"):
		if col not in existing:
			memory_manager.client.create_collection(
				collection_name=col, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE)
			)
	return memory_manager


def _content(pid: str, session_id: str, hub_id: str) -> models.PointStruct:
	return models.PointStruct(
		id=pid,
		vector=[0.1] * DIM,
		payload={
			"content": "un turno",
			"node_type": "memento_engram",
			"session_id": session_id,
			"hubbed": True,
			"hub_id": hub_id,
			"created_at": 1.0,
		},
	)


def _hub() -> models.PointStruct:
	return models.PointStruct(
		id=HUB_ID,
		vector=[0.1] * DIM,
		payload={"content": "rama", "lazarus_phase": "synthesis_hub", "node_type": "synthesis_hub"},
	)


def _payload(mm, pid: str):
	records = mm.client.retrieve(collection_name="work_memories", ids=[pid], with_payload=True)
	return records[0].payload if records else None


def _singleton_marker() -> str:
	return str(uuid.uuid4())


def test_singleton_marker_cleared_but_groupable_orphan_kept(mm):
	solo = _singleton_marker()
	ok = str(uuid.uuid4())
	leak = str(uuid.uuid4())
	mm.client.upsert(
		collection_name="work_memories",
		points=[
			_hub(),
			# Sesión de UN miembro: nunca tendrá hub → residuo de poda.
			_content(solo, "sesion-solo", "hub-fantasma"),
			# Sesión agrupable: uno apunta al hub real y otro a un padre borrado.
			_content(ok, "sesion-grupo", HUB_ID),
			_content(leak, "sesion-grupo", "hub-fantasma"),
		],
	)

	stats = repair_stale_orphan_markers(mm, collections=("work_memories",))

	assert stats["cleared"] == 1
	assert stats["sessions"] == 1
	assert _payload(mm, solo).get("hubbed") is None
	assert _payload(mm, solo).get("hub_id") is None
	# La fuga real sigue intacta: el marcador no se maquilla.
	assert _payload(mm, leak).get("hubbed") is True
	assert _payload(mm, ok).get("hub_id") == HUB_ID

	col = compute_sw_health(mm, collections=("work_memories",))["collections"]["work_memories"]
	assert col["orphan_markers"] == 1
	assert col["orphan_markers_stale"] == 0
	assert col["hub_integrity_ok"] is False, "la fuga de la sesión agrupable debe seguir ringando"


def test_dry_run_counts_without_touching(mm):
	solo = _singleton_marker()
	mm.client.upsert(collection_name="work_memories", points=[_content(solo, "sesion-solo", "hub-fantasma")])

	stats = repair_stale_orphan_markers(mm, collections=("work_memories",), dry_run=True)

	assert stats["cleared"] == 1
	assert stats["dry_run"] is True
	assert _payload(mm, solo).get("hubbed") is True


def test_repair_is_idempotent(mm):
	solo = _singleton_marker()
	mm.client.upsert(collection_name="work_memories", points=[_content(solo, "sesion-solo", "hub-fantasma")])

	first = repair_stale_orphan_markers(mm, collections=("work_memories",))
	second = repair_stale_orphan_markers(mm, collections=("work_memories",))

	assert first["cleared"] == 1
	assert second["cleared"] == 0


def test_valid_marker_in_singleton_session_is_not_touched(mm):
	"""Si el hub EXISTE, el marcador es válido aunque la sesión tenga un miembro."""
	solo = _singleton_marker()
	mm.client.upsert(
		collection_name="work_memories",
		points=[_hub(), _content(solo, "sesion-solo", HUB_ID)],
	)

	stats = repair_stale_orphan_markers(mm, collections=("work_memories",))

	assert stats["cleared"] == 0
	assert _payload(mm, solo).get("hub_id") == HUB_ID


def test_threshold_constant_is_the_synthesis_gate():
	"""El umbral vive una sola vez: si cambia, cambia para síntesis y salud."""
	assert HUB_MIN_SESSION_MEMBERS == 2
