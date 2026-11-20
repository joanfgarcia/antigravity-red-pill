"""MEM-011 · F4 — la cascada del olvido cae de abajo arriba en la MISMA pasada.

Una sola foto de hijos no propaga: si la parte cae, su raíz seguiría viéndola
viva hasta la noche siguiente. El reaper ahora itera niveles y re-cuenta entre
ellos. La guarda anti-carrera (12 h) se respeta en cada nivel.
"""

import time

from qdrant_client.http import models

from red_pill.memory import MemoryManager
from red_pill.metabolism.forgetting import reap_leafless_branches

DAY = 86400.0
_PREFIX = "00000000-0000-0000-0000-00000000dd"


def _hub(pid: str, *, now: float, role: str = "root", parent: str | None = None, age_days: float = 5.0) -> models.PointStruct:
	written = now - age_days * DAY
	payload = {
		"content": "rama",
		"lazarus_phase": "synthesis_hub",
		"node_type": "synthesis_hub",
		"hub_role": role,
		"hub_members_count": 0,
		"created_at": written,
		"hub_members_checked_at": written,
		"reinforcement_score": 0.9,
		"last_recalled_at": written,
		"immune": False,
	}
	if parent:
		payload["hubbed"] = True
		payload["hub_id"] = parent
	return models.PointStruct(id=pid, vector=[0.1] * 384, payload=payload)


def _leaf(pid: str, part: str, now: float) -> models.PointStruct:
	return models.PointStruct(
		id=pid,
		vector=[0.2] * 384,
		payload={
			"content": "hoja",
			"node_type": "memento_engram",
			"hubbed": True,
			"hub_id": part,
			"created_at": now - DAY,
			"immune": False,
		},
	)


def _live(mm: MemoryManager, collection: str) -> set:
	points, _ = mm.client.scroll(collection_name=collection, limit=100, with_payload=False)
	return {str(p.id) for p in points}


def _setup(now: float, extra: list) -> MemoryManager:
	mm = MemoryManager()
	mm._ensure_collection("work_memories")
	mm.client.upsert(collection_name="work_memories", points=extra)
	return mm


def test_cascada_parte_y_raiz_en_la_misma_pasada():
	now = time.time()
	root = f"{_PREFIX}01"
	part = f"{_PREFIX}11"
	mm = _setup(
		now,
		[
			_hub(root, now=now, role="root"),
			_hub(part, now=now, role="part", parent=root),
			# la hoja de la parte se purgó antes (escalera): la parte ya no tiene hijos
		],
	)
	result = reap_leafless_branches(mm, mode="enforce")
	assert result["reaped"] == 2
	assert _live(mm, "work_memories") == set()


def test_raiz_con_otra_parte_viva_sobrevive():
	now = time.time()
	root = f"{_PREFIX}02"
	part_empty = f"{_PREFIX}12"
	part_alive = f"{_PREFIX}13"
	mm = _setup(
		now,
		[
			_hub(root, now=now),
			_hub(part_empty, now=now, role="part", parent=root),
			_hub(part_alive, now=now, role="part", parent=root),
			_leaf(f"{_PREFIX}99", part_alive, now),
		],
	)
	reap_leafless_branches(mm, mode="enforce")
	live = _live(mm, "work_memories")
	assert part_empty not in live
	assert part_alive in live
	assert root in live


def test_guarda_anti_carrera_en_la_parte_recien_escrita():
	now = time.time()
	root = f"{_PREFIX}03"
	part = f"{_PREFIX}14"
	mm = _setup(
		now,
		[
			_hub(root, now=now),
			_hub(part, now=now, role="part", parent=root, age_days=0.0001),  # 8 s
		],
	)
	reap_leafless_branches(mm, mode="enforce")
	live = _live(mm, "work_memories")
	assert part in live  # el hub se escribió antes de marcar sus hojas: no se toca
	assert root in live


def test_dry_run_no_borra_nada():
	now = time.time()
	root = f"{_PREFIX}04"
	part = f"{_PREFIX}15"
	mm = _setup(now, [_hub(root, now=now), _hub(part, now=now, role="part", parent=root)])
	result = reap_leafless_branches(mm, mode="dry_run")
	assert result["candidates"] == 2
	assert result["reaped"] == 0
	assert len(_live(mm, "work_memories")) == 2
