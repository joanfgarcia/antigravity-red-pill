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


def _clock(n: int, now: float, started_epoch: int | None = None) -> dict:
	"""Estado del reloj monótono: `epoch` días activos acumulados."""
	return {"epoch": n, "days": _days(n, now), "started_epoch": n if started_epoch is None else started_epoch}


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
	clock = _clock(60, now)
	old = _payload(last_recalled_at=now - DAY * 31, active_days_at_recall=60 - 31)
	assert fog.classify(old, "work_memories", clock, now) == "delete"
	young = _payload(last_recalled_at=now - DAY * 29, active_days_at_recall=60 - 29)
	assert fog.classify(young, "work_memories", clock, now) == "keep"


def test_sink_step1_60_active_days():
	now = time.time()
	clock = _clock(90, now)
	one_recall = _payload(recall_count=1, last_recalled_at=now - DAY * 61, active_days_at_recall=90 - 61)
	assert fog.classify(one_recall, "work_memories", clock, now) == "delete"
	fresh = _payload(recall_count=1, last_recalled_at=now - DAY * 59, active_days_at_recall=90 - 59)
	assert fog.classify(fresh, "work_memories", clock, now) == "keep"


def test_two_spaced_recalls_promote_and_work_circuit_holds_105():
	now = time.time()
	clock = _clock(400, now)
	# Dos recuperaciones, pero fuera de la ventana de 90 días activos.
	recalls = [now - DAY * 300, now - DAY * 200]
	out = _payload(recall_count=2, recall_stamps=recalls, last_recalled_at=now - DAY * 200, active_days_at_recall=200)
	assert fog.classify(out, "work_memories", clock, now) == "delete"

	# Dos recuperaciones espaciadas y recientes: primera vez, se promueve.
	spaced = [now - DAY * 80, now - DAY * 40]
	within = _payload(recall_count=2, recall_stamps=spaced, last_recalled_at=now - DAY * 40, active_days_at_recall=360)
	assert fog.classify(within, "work_memories", clock, now) == "promote", "primera vez: se promueve"

	# Ya promovido, el circuito largo aguanta hasta 105 días activos sin tocarlo.
	promoted = dict(within, promoted_at=now - DAY * 40)
	assert fog.classify(promoted, "work_memories", clock, now) == "keep"

	# ...y pasados los 105 días activos, el circuito largo lo suelta.
	stale = _payload(recall_count=2, last_recalled_at=now - DAY * 106, active_days_at_recall=400 - 106, promoted_at=now - DAY * 300)
	assert fog.classify(stale, "work_memories", clock, now) == "delete"


def test_two_recalls_same_day_do_not_promote():
	now = time.time()
	clock = _clock(200, now)
	same_day = [now - DAY * 100, now - DAY * 100 + 3600]
	payload = _payload(recall_count=2, recall_stamps=same_day, last_recalled_at=now - DAY * 100, active_days_at_recall=200 - 100)
	assert fog.classify(payload, "work_memories", clock, now) == "delete", "dos golpes en el mismo día no son espaciado (Bjork)"


def test_social_freezes_at_five_years_and_never_deletes():
	"""Permastore: promoted_at + 5 años desde el último recuerdo -> congelado.

	La promoción es una transición (`promoted_at`), no un test rodante: si se
	evaluara «en ventana» cada noche, haría falta ser recordado en los últimos 90
	días activos Y tener 5 años a la vez, que es imposible.
	"""
	now = time.time()
	clock = _clock(400, now)
	payload = _payload(recall_count=2, promoted_at=now - 6 * 365 * DAY, last_recalled_at=now - 5.5 * 365 * DAY)
	assert fog.classify(payload, "social_memories", clock, now) == "freeze"

	young = _payload(recall_count=2, promoted_at=now - 365 * DAY, last_recalled_at=now - 365 * DAY)
	assert fog.classify(young, "social_memories", clock, now) == "keep"


def test_branch_is_not_ladder_business():
	now = time.time()
	clock = _clock(400, now)
	hub = _payload(lazarus_phase="synthesis_hub", last_recalled_at=now - DAY * 300)
	assert fog.classify(hub, "work_memories", clock, now) == "keep"


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
				payload=_payload(last_recalled_at=now - DAY * 40, created_at=now - DAY * 40, active_days_at_recall=60 - 40),
			)
		],
	)
	monkeypatch.setattr(fog, "active_day_clock", lambda *a, **k: _clock(60, now))
	# El reloj inyectado simula que la escalera lleva 60 días activos contando;
	# en producción el marcador hace que la primera purga espere (D-16).
	report = fog.run_ladder(memory_manager, mode="dry_run")

	assert report["collections"]["work_memories"]["planned_delete"] == 1
	# El punto ya tiene contador (post-F2), así que el «reloj histórico» no aporta
	# una cifra distinta: solo se calcula para los legacy, sin contador (R3-C-05).
	assert report["collections"]["work_memories"]["historical_delete"] == 0
	assert memory_manager.client.retrieve(collection_name="work_memories", ids=[pid], with_payload=False), "dry_run no borra"

	fog.run_ladder(memory_manager, mode="enforce")
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


def test_ramp_caps_purges_per_cycle(memory_manager, monkeypatch):
	"""R4-02: nunca se purga el corpus de golpe; la rampa limita por pasada."""
	from qdrant_client.http import models

	import red_pill.config as cfg

	now = time.time()
	clock = _clock(200, now, started_epoch=0)
	monkeypatch.setattr(fog, "active_day_clock", lambda *a, **k: clock)
	monkeypatch.setattr(cfg, "SW_FORGETTING_MAX_PURGES_PER_CYCLE", 2)
	memory_manager._ensure_collection("work_memories")
	points = []
	for i in range(5):
		points.append(
			models.PointStruct(
				id=f"00000000-0000-0000-0000-00000000ab0{i}",
				vector=[0.1] * 384,
				payload={
					"content": f"viejo {i}",
					"node_type": "memento_engram",
					"recall_count": 0,
					"last_recalled_at": now - DAY * 100,
					"created_at": now - DAY * 100,
				},
			)
		)
	memory_manager.client.upsert(collection_name="work_memories", points=points)

	report = fog.run_ladder(memory_manager, mode="enforce")
	col = report["collections"]["work_memories"]
	assert col["planned_delete"] == 5
	assert col["applied_delete"] == 2, "la rampa no puede llevarse los cinco de golpe"
	assert col["deferred"] == 3
	remaining = memory_manager.client.scroll(collection_name="work_memories", limit=100, with_payload=False)[0]
	assert len(remaining) == 3
