"""RFC-OLV-001 · guardas finales (ronda adversarial de cierre).

Cubre los huecos que la primera implementación dejó abiertos y que ninguna
lente anterior cubría:

- el reaper NO borra una rama con hojas (el invariante de la RFC);
- el washout NO borra nada, y menos un `permastore`;
- la transición de los legacy (`recall_count>=2` sin `recall_stamps`) promueve;
- un día sin actividad no avanza el reloj;
- un payload con fecha ISO no tumba la pasada;
- delta de huérfanos = 0 tras una pasada completa.
"""

import time
from unittest.mock import MagicMock

from qdrant_client.http import models

from red_pill.config import RedPillConfig
from red_pill.memory import MemoryManager
from red_pill.metabolism import forgetting as fog
from red_pill.metabolism.sleep import run_rhizodb_washout_and_pruning

DAY = 86400.0

HUB_WITH_LEAVES = "00000000-0000-0000-0000-00000000ff01"
MEMBER_OF_HUB = "00000000-0000-0000-0000-00000000ff11"
LEAFLESS_OLD = "00000000-0000-0000-0000-00000000ff02"


def _days(n: int, now: float) -> list:
	return [now - DAY * (n - 1 - i) for i in range(n)]


def _clock(n: int, now: float, started_epoch: int | None = None) -> dict:
	return {"epoch": n, "days": _days(n, now), "started_epoch": n if started_epoch is None else started_epoch}


# ---------------------------------------------------------------------------
# 1. El invariante: una rama con hojas no se borra (ni por el reaper)
# ---------------------------------------------------------------------------


def test_reaper_never_deletes_a_branch_with_leaves(memory_manager: MemoryManager):
	"""Si alguien quita el guard de hojas del reaper, este test cae."""
	now = time.time()
	memory_manager._ensure_collection("work_memories")
	base = {"content": "rama", "lazarus_phase": "synthesis_hub", "immune": False}
	memory_manager.client.upsert(
		collection_name="work_memories",
		points=[
			models.PointStruct(
				id=HUB_WITH_LEAVES, vector=[0.1] * 384, payload=dict(base, created_at=now - DAY * 30, hub_members_checked_at=now - DAY * 30)
			),
			models.PointStruct(
				id=LEAFLESS_OLD, vector=[0.1] * 384, payload=dict(base, created_at=now - DAY * 30, hub_members_checked_at=now - DAY * 30)
			),
			models.PointStruct(
				id=MEMBER_OF_HUB,
				vector=[0.2] * 384,
				payload={"content": "hoja", "node_type": "memento_engram", "hubbed": True, "hub_id": HUB_WITH_LEAVES, "created_at": now - DAY},
			),
		],
	)

	report = fog.reap_leafless_branches(memory_manager, mode="enforce")

	assert report["reaped"] == 1
	assert memory_manager.client.retrieve(collection_name="work_memories", ids=[HUB_WITH_LEAVES], with_payload=False), (
		"una rama con hojas vivas no se borra jamás (RFC-OLV-001 I-01)"
	)
	assert not memory_manager.client.retrieve(collection_name="work_memories", ids=[LEAFLESS_OLD], with_payload=False)


def test_orphan_markers_do_not_grow_after_a_pass(memory_manager: MemoryManager):
	"""C-03: el oráculo es el delta de huérfanos, no el conteo de ramas."""
	now = time.time()
	memory_manager._ensure_collection("work_memories")
	memory_manager.client.upsert(
		collection_name="work_memories",
		points=[
			models.PointStruct(
				id=HUB_WITH_LEAVES,
				vector=[0.1] * 384,
				payload={"content": "rama", "lazarus_phase": "synthesis_hub", "created_at": now - DAY * 40, "hub_members_checked_at": now - DAY * 40},
			),
			models.PointStruct(
				id=MEMBER_OF_HUB,
				vector=[0.2] * 384,
				payload={"content": "hoja", "node_type": "memento_engram", "hubbed": True, "hub_id": HUB_WITH_LEAVES, "created_at": now - DAY},
			),
		],
	)
	fog.reap_leafless_branches(memory_manager, mode="enforce")
	fog.run_ladder(memory_manager, mode="dry_run")

	points = memory_manager.client.scroll(collection_name="work_memories", limit=100, with_payload=True)[0]
	hubs = {str(p.id) for p in points if (p.payload or {}).get("lazarus_phase") == "synthesis_hub"}
	orphans = [p for p in points if (p.payload or {}).get("hubbed") and str((p.payload or {}).get("hub_id")) not in hubs]
	assert orphans == [], "ninguna pasada puede dejar marcadores sin padre"


# ---------------------------------------------------------------------------
# 2. El washout ya no borra, y respeta permastore
# ---------------------------------------------------------------------------


def _point(pid: str, payload: dict) -> MagicMock:
	p = MagicMock()
	p.id = pid
	p.payload = payload
	return p


def test_washout_does_not_delete_and_respects_permastore(monkeypatch, tmp_path):
	monkeypatch.setattr(fog, "active_day_clock", lambda *a, **k: _clock(1, time.time()))
	monkeypatch.setattr("red_pill.metabolism.maintenance._washout_state_path", lambda: tmp_path / "w.json")
	now = time.time()
	# Score alto a propósito: así el único motivo para no tocarlo es `permastore`
	# (con 0.04 se saltaría por el umbral de poda y la guarda no se probaría).
	frozen = _point("congelado", {"reinforcement_score": 0.9, "stability": 50.0, "immune": False, "permastore": True, "last_recalled_at": now})
	weak = _point("debil", {"reinforcement_score": 0.9, "stability": 50.0, "immune": False, "last_recalled_at": now})

	mm = MagicMock()
	mm.client.collection_exists.return_value = True
	mm.client.scroll.return_value = ([frozen, weak], None)

	run_rhizodb_washout_and_pruning(mm)

	assert not mm.client.delete.called, "la única ruta que decide borrar es la escalera (D-22)"
	updated = []
	for call in mm.client.batch_update_points.call_args_list:
		for op in call[1]["update_operations"]:
			updated.extend(op.set_payload.points)
	assert "congelado" not in updated, "un permastore no se puntúa ni se toca"
	assert "debil" in updated, "el gemelo sin permastore sí se renormaliza"


# ---------------------------------------------------------------------------
# 3. Transición legacy y reloj de días activos
# ---------------------------------------------------------------------------


def test_legacy_with_two_recalls_promotes_instead_of_dying():
	now = time.time()
	clock = _clock(400, now, started_epoch=0)
	payload = {"recall_count": 3, "last_recalled_at": now - DAY * 70, "created_at": now - DAY * 400}

	# Un stamp (el que siembra la migración de §8.2) NO debe apagar la guarda.
	seeded = dict(payload, recall_stamps=[now - DAY * 70])
	assert fog.classify(payload, "work_memories", clock, now) == "promote", "sin stamps: promueve"
	assert fog.classify(seeded, "work_memories", clock, now) == "promote", "con el stamp sembrado: también"

	# Pero si el último recuerdo está FUERA de la ventana de 90 días activos, no:
	ancient = {"recall_count": 3, "last_recalled_at": now - DAY * 300, "created_at": now - DAY * 400}
	assert fog.classify(ancient, "work_memories", clock, now) == "delete", "fuera de ventana: no promueve"


def test_idle_days_do_not_advance_the_clock():
	"""C-07: 30 días de calendario sin actividad no suman un solo día activo."""
	now = time.time()
	# Reloj: 10 días activos antes del hueco y hoy. El epoch solo avanza por días
	# activos, así que 30 días naturales de vacaciones suman 1, no 31.
	clock = {"epoch": 11, "days": _days(10, now - DAY * 30) + [now], "started_epoch": 0}
	payload = {"recall_count": 0, "active_days_at_recall": 1, "last_recalled_at": now - DAY * 30}
	assert fog.classify(payload, "work_memories", clock, now) == "keep", "la ausencia no cobra"


def test_iso_timestamps_do_not_break_the_pass():
	now = time.time()
	assert fog.classify({"recall_count": 1, "last_recalled_at": "2026-11-01T10:00:00Z"}, "work_memories", _clock(40, now), now) == "keep"


def test_unknown_collection_is_never_decided():
	now = time.time()
	assert fog.classify({"recall_count": 0, "last_recalled_at": now - DAY * 400}, "directive_memories", _clock(40, now), now) == "keep"


# ---------------------------------------------------------------------------
# 4. El modo de la escalera se valida
# ---------------------------------------------------------------------------


def test_ladder_mode_is_normalized_and_validated():
	assert RedPillConfig(SW_FORGETTING_LADDER_MODE="dry-run").SW_FORGETTING_LADDER_MODE == "dry_run"
	assert RedPillConfig(SW_FORGETTING_LADDER_MODE="true").SW_FORGETTING_LADDER_MODE == "enforce"
	assert RedPillConfig(SW_FORGETTING_LADDER_MODE="").SW_FORGETTING_LADDER_MODE == "off"
	try:
		RedPillConfig(SW_FORGETTING_LADDER_MODE="bogus")
	except Exception:
		pass
	else:  # pragma: no cover
		raise AssertionError("un modo inventado debe ser rechazado en config, no degradarse en silencio")


def test_active_day_counter_changes_the_verdict():
	"""D-16 muerde: el legacy se cobra lo real, pero con el techo de la gracia."""
	now = time.time()
	old_legacy = {"recall_count": 0, "last_recalled_at": now - DAY * 40}
	recent = {"recall_count": 0, "last_recalled_at": now - DAY * 2}

	# Recién arrancada (gracia = 0): nadie cae todavía.
	start = _clock(60, now, started_epoch=60)
	assert fog.classify(old_legacy, "work_memories", start, now) == "keep"
	assert fog.classify(recent, "work_memories", start, now) == "keep"

	# 35 días activos después del arranque: el legacy antiguo cae (40 > 30, con
	# techo 35); el usado hace 2 días activos sigue vivo.
	later = _clock(95, now, started_epoch=60)
	assert fog.classify(old_legacy, "work_memories", later, now) == "delete"
	assert fog.classify(recent, "work_memories", later, now) == "keep"

	# Y con contador, el reciente se mide por su índice, no por la gracia.
	counted = dict(recent, active_days_at_recall=93)
	assert fog.classify(counted, "work_memories", later, now) == "keep"
	assert fog.classify(dict(recent, active_days_at_recall=60), "work_memories", later, now) == "delete"


def test_clock_is_monotonic_and_atomic(monkeypatch, tmp_path):
	"""El epoch solo avanza, ignora días viejos y escribe de forma atómica."""
	state = tmp_path / "olvido_active_days.json"
	monkeypatch.setattr(fog, "_state_path", lambda: state)

	now = time.time()
	first = [now - DAY * 2, now - DAY]
	monkeypatch.setattr(fog, "_mirror_days", lambda after=None: first if not after else [])
	clock = fog.active_day_clock(now)
	assert clock and clock["epoch"] == 2 and state.exists()

	# Backfill de días ANTIGUOS: no inflan el epoch.
	older = [now - DAY * 30, now - DAY * 20]

	def _only_newer(after=None):
		# Contrato real: la consulta filtra por `after` en SQL.
		return [d for d in older if after is None or time.strftime("%Y-%m-%d", time.localtime(d)) > after]

	monkeypatch.setattr(fog, "_mirror_days", _only_newer)
	clock = fog.active_day_clock(now)
	assert clock["epoch"] == 2, "un backfill no cobra olvido que no ocurrió"

	# Día nuevo: avanza.
	monkeypatch.setattr(fog, "_mirror_days", lambda after=None: [now])
	clock = fog.active_day_clock(now)
	assert clock["epoch"] == 3
