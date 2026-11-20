"""RFC-OLV-001 · F1 — la rama sigue a sus hojas.

Invariante I-01: una rama (hub) con al menos una hoja (miembro) viva no se
erosiona NUNCA: ni decae ni se borra. Antes de este guard, `erode_work_hubs`
borraba ramas con miembros y dejaba los marcadores `hubbed=True` apuntando a un
`hub_id` inexistente: 1.962 en el Búnker el 2026-11-16, invisibles al recall.

El fixture debe MORDER: un hub con β=3,7 sin guard se borra en la misma pasada
(β+0,5 → utilidad ≈0,192 ≤ 0,2), así que revertir el guard hace fallar el test.
"""

import time

from qdrant_client.http import models

from red_pill.memory import MemoryManager
from red_pill.metabolism.maintenance import erode_work_hubs

_HUB_WITH_LEAVES = "00000000-0000-0000-0000-00000000bb01"
_HUB_WITHOUT_LEAVES = "00000000-0000-0000-0000-00000000bb02"
_MEMBER_1 = "00000000-0000-0000-0000-00000000bb11"
_MEMBER_2 = "00000000-0000-0000-0000-00000000bb12"

DAY = 86400.0


def _hub(pid: str, content: str, now: float, beta: float = 3.7) -> models.PointStruct:
	return models.PointStruct(
		id=pid,
		vector=[0.1] * 384,
		payload={
			"content": content,
			"lazarus_phase": "synthesis_hub",
			"utility_alpha": 1.0,
			"utility_beta": beta,
			"reinforcement_score": 1.0 / (1.0 + beta),
			"intensity": 0.5,
			"immune": False,
			"created_at": now - DAY,
			"last_recalled_at": now - DAY,
			"color": "gray",
			"emotion": "neutral",
			"importance": 1.0,
			"hub_members_count": 0,  # miente a propósito: I-03 obliga a contar por scroll
		},
	)


def _member(pid: str, hub_id: str, now: float) -> models.PointStruct:
	return models.PointStruct(
		id=pid,
		vector=[0.2] * 384,
		payload={
			"content": "hoja viva",
			"node_type": "memento_engram",
			"hubbed": True,
			"hub_id": hub_id,
			"immune": False,
			"created_at": now - DAY,
			"last_recalled_at": now - DAY,
			"color": "gray",
			"emotion": "neutral",
			"importance": 1.0,
		},
	)


def _seed(mm: MemoryManager):
	mm._ensure_collection("work_memories")
	now = time.time()
	mm.client.upsert(
		collection_name="work_memories",
		points=[
			_hub(_HUB_WITH_LEAVES, "rama con hojas", now),
			_hub(_HUB_WITHOUT_LEAVES, "rama seca", now),
			_member(_MEMBER_1, _HUB_WITH_LEAVES, now),
			_member(_MEMBER_2, _HUB_WITH_LEAVES, now),
		],
	)


def _get(mm, pid):
	pts = mm.client.retrieve(collection_name="work_memories", ids=[pid], with_payload=True)
	return pts[0].payload if pts else None


def test_branch_with_leaves_survives_and_does_not_decay(memory_manager):
	"""C-01: β=3,7 + 2 hojas. Sin el guard, esta rama muere (utilidad 0,192 ≤ 0,2)."""
	_seed(memory_manager)
	stats = erode_work_hubs(memory_manager)

	hub = _get(memory_manager, _HUB_WITH_LEAVES)
	assert hub is not None, "una rama con hojas vivas no se borra jamás (RFC-OLV-001 I-01)"
	assert hub["utility_beta"] == 3.7, "tampoco decae: su olvido es el de sus hojas"
	assert _get(memory_manager, _MEMBER_1) is not None
	assert _get(memory_manager, _MEMBER_2) is not None
	assert stats["kept_with_leaves"] == 1


def test_control_leafless_branch_still_dies(memory_manager):
	"""C-01 bis: el mismo fixture sin hojas SÍ cae, así que el guard no lo salvó todo."""
	_seed(memory_manager)
	erode_work_hubs(memory_manager)

	assert _get(memory_manager, _HUB_WITHOUT_LEAVES) is None, "una rama seca sigue su curso"
	assert _get(memory_manager, _HUB_WITH_LEAVES) is not None


def test_members_count_is_counted_by_scroll_not_by_payload(memory_manager):
	"""I-03: `hub_members_count: 0` (mentiroso) no puede convertir la rama en seca."""
	_seed(memory_manager)
	erode_work_hubs(memory_manager)

	hub = _get(memory_manager, _HUB_WITH_LEAVES)
	assert hub is not None
	assert hub["utility_beta"] == 3.7, "si se hubiera usado hub_members_count, la rama habría decaído y muerto"


def test_fail_closed_when_members_cannot_be_counted(memory_manager, monkeypatch):
	"""I-02/IP: si no se pueden contar hojas, no se borra nada en esa pasada."""
	_seed(memory_manager)
	import red_pill.metabolism.maintenance as maint

	monkeypatch.setattr(maint, "_count_hub_members", lambda *a, **k: None)
	stats = erode_work_hubs(memory_manager)

	assert stats == {"eroded": 0, "decayed": 0, "kept_with_leaves": 0}
	assert _get(memory_manager, _HUB_WITHOUT_LEAVES) is not None, "fail-closed: la rama seca tampoco se toca"
