"""RFC-OLV-001 · F3 — la escalera del olvido (política en días activos).

El reloj de días activos se inyecta (lista de medianoches), así que estos tests
son deterministas y no dependen de la base de sesiones real.

Cubre: escalón 0 (30), escalón 1 (60), puerta de promoción espaciada (90),
circuito work (105), permastore social (5 años), y las dos guardas del reaper
(anti-carrera y auto-contenido).
"""

import time

from qdrant_client.http import models

from red_pill.memory import MemoryManager
from red_pill.metabolism import forgetting as fog

DAY = 86400.0


def _days(n: int, now: float) -> list:
	"""`n` días activos consecutivos que terminan hoy."""
	return [now - DAY * (n - 1 - i) for i in range(n)]


def _payload(**kw):
	base = {
		"content": "x",
		"immune": False,
		"recall_count": 0,
		"last_recalled_at": time.time(),
		"created_at": time.time(),
	}
	base.update(kw)
	return base


def test_sink_step0_30_active_days():
	now = time.time()
	days = _days(60, now)
	old = now - DAY * 31
	assert fog.classify(_payload(last_recalled_at=old), "work_memories", days, now) == "delete"
	young = now - DAY * 29
	assert fog.classify(_payload(last_recalled_at=young), "work_memories", days, now) == "keep"


def test_sink_step1_60_active_days():
	now = time.time()
	days = _days(90, now)
	one_recall = _payload(recall_count=1, last_recalled_at=now - DAY * 61)
	assert fog.classify(one_recall, "work_memories", days, now) == "delete"
	fresh = _payload(recall_count=1, last_recalled_at=now - DAY * 59)
	assert fog.classify(fresh, "work_memories", days, now) == "keep"


def test_two_spaced_recalls_promote_and_work_circuit_holds_105():
	now = time.time()
	days = _days(400, now)
	recalls = [now - DAY * 300, now - DAY * 200]  # dos días distintos, dentro de 90? no: fuera
	assert fog.classify(_payload(recall_count=2, recall_stamps=recalls, last_recalled_at=now - DAY * 200), "work_memories", days, now) == "delete"

	# Dos recuperaciones espaciadas pero recientes (dentro de 90 días activos):
	spaced = [now - DAY * 80, now - DAY * 40]
	within = _payload(recall_count=2, recall_stamps=spaced, last_recalled_at=now - DAY * 40)
	assert fog.classify(within, "work_memories", days, now) == "promote", "primera vez: se promueve"

	# Ya promovido, el circuito largo aguanta hasta 105 días activos sin tocarlo.
	promoted = dict(within, promoted_at=now - DAY * 40)
	assert fog.classify(promoted, "work_memories", days, now) == "keep"
	# ...y a los 106 días activos sin volver a tocarlo, el circuito largo lo suelta.
	stale = _payload(recall_count=2, recall_stamps=[now - DAY * 300, now - DAY * 160], last_recalled_at=now - DAY * 106)
	stale["recall_stamps"] = [now - DAY * 260, now - DAY * 200]
	assert fog.classify(stale, "work_memories", days, now) == "delete"


def test_two_recalls_same_day_do_not_promote():
	now = time.time()
	days = _days(200, now)
	same_day = [now - DAY * 100, now - DAY * 100 + 3600]
	payload = _payload(recall_count=2, recall_stamps=same_day, last_recalled_at=now - DAY * 100)
	assert fog.classify(payload, "work_memories", days, now) == "delete", "dos golpes en el mismo día no son espaciado (Bjork)"


def test_social_freezes_at_five_years_and_never_deletes():
	"""Permastore: promoted_at + 5 años desde el último recuerdo -> congelado.

	La promoción es una transición (`promoted_at`), no un test rodante: si se
	evaluara «en ventana» cada noche, haría falta ser recordado en los últimos 90
	días activos Y tener 5 años a la vez, que es imposible.
	"""
	now = time.time()
	days = _days(400, now)
	payload = _payload(recall_count=2, promoted_at=now - 6 * 365 * DAY, last_recalled_at=now - 5.5 * 365 * DAY)
	assert fog.classify(payload, "social_memories", days, now) == "freeze"

	young = _payload(recall_count=2, promoted_at=now - 365 * DAY, last_recalled_at=now - 365 * DAY)
	assert fog.classify(young, "social_memories", days, now) == "keep"


def test_branch_is_not_ladder_business():
	now = time.time()
	days = _days(400, now)
	hub = _payload(lazarus_phase="synthesis_hub", last_recalled_at=now - DAY * 300)
	assert fog.classify(hub, "work_memories", days, now) == "keep"


def test_dry_run_writes_nothing(memory_manager: MemoryManager, monkeypatch):
	now = time.time()
	memory_manager._ensure_collection("work_memories")
	pid = "00000000-0000-0000-0000-00000000dd01"
	memory_manager.client.upsert(
		collection_name="work_memories",
		points=[
			models.PointStruct(
				id=pid,
				vector=[0.1] * 384,
				payload=_payload(last_recalled_at=now - DAY * 40, created_at=now - DAY * 40),
			)
		],
	)
	monkeypatch.setattr(fog, "active_days", lambda *a, **k: _days(60, now))
	# `ladder_start` en el pasado simula que la escalera lleva 60 días activos
	# contando; en producción el marcador hace que la primera purga espere (D-16).
	report = fog.run_ladder(memory_manager, mode="dry_run", ladder_start=now - DAY * 60)

	assert report["collections"]["work_memories"]["planned_delete"] == 1
	# Y el reloj histórico (sin la gracia de D-16) lo veía igual: la cifra es
	# visible en dry_run sin arriesgar nada.
	assert report["collections"]["work_memories"]["historical_delete"] >= 1
	assert memory_manager.client.retrieve(collection_name="work_memories", ids=[pid], with_payload=False), "dry_run no borra"

	fog.run_ladder(memory_manager, mode="enforce", ladder_start=now - DAY * 60)
	assert not memory_manager.client.retrieve(collection_name="work_memories", ids=[pid], with_payload=False), "enforce sí borra"


def test_reaper_respects_race_guard_and_self_content(memory_manager: MemoryManager):
	now = time.time()
	memory_manager._ensure_collection("work_memories")
	fresh = "00000000-0000-0000-0000-00000000dd11"
	old = "00000000-0000-0000-0000-00000000dd12"
	selfc = "00000000-0000-0000-0000-00000000dd13"
	base = {"content": "rama", "lazarus_phase": "synthesis_hub", "immune": False}

	def hub(pid, **kw):
		p = dict(base)
		p.update(kw)
		return models.PointStruct(id=pid, vector=[0.1] * 384, payload=p)

	memory_manager.client.upsert(
		collection_name="work_memories",
		points=[
			hub(fresh, created_at=now - 60, hub_members_checked_at=now - 60),
			hub(old, created_at=now - DAY * 5, hub_members_checked_at=now - DAY * 5),
			hub(selfc, created_at=now - DAY * 5, hub_members_checked_at=now - DAY * 5, promoted_from="sequence_chunk"),
		],
	)
	report = fog.reap_leafless_branches(memory_manager, mode="enforce")

	assert report["reaped"] == 1
	assert memory_manager.client.retrieve(collection_name="work_memories", ids=[fresh], with_payload=False), (
		"anti-carrera: un hub recién escrito no se toca"
	)
	assert not memory_manager.client.retrieve(collection_name="work_memories", ids=[old], with_payload=False), "la rama seca y vieja cae"
	assert memory_manager.client.retrieve(collection_name="work_memories", ids=[selfc], with_payload=False), "una auto-contenida no es rama de nadie"
