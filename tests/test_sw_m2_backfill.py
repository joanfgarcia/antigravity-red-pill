"""M2 single-writer — backfill de fechas de los engramas ascendidos (G9)."""

from __future__ import annotations

import datetime
import importlib.util
from pathlib import Path


def _load_module():
	spec = importlib.util.spec_from_file_location("memento_backfill_dates", Path("scripts/memento_backfill_dates.py"))
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


def _epoch(iso: str) -> float:
	return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def test_backfill_fija_fecha_de_sesion_y_mueve_ascended_at():
	mod = _load_module()
	state = {"registry": {"opencode": {"opencode:ses_a": {"created_at": "2026-08-12T20:35:06.300000Z"}}}}
	points = [
		("p1", {"origin": "memento", "source": "opencode", "session_id": "opencode:ses_a", "created_at": 1789000000.0}),
	]
	plan = mod.plan_backfill(points, state)
	assert len(plan) == 1
	upd = plan[0]["payload"]
	assert upd["created_at"] == _epoch("2026-08-12T20:35:06.300000Z")
	assert upd["ascended_at"] == 1789000000.0
	assert upd["node_type"] == "memento_engram"


def test_backfill_es_idempotente_y_omite_lo_que_no_puede():
	mod = _load_module()
	state = {"registry": {"opencode": {"opencode:ses_a": {"created_at": "2026-08-12T20:35:06.300000Z"}}}}
	points = [
		("p1", {"origin": "memento", "session_id": "opencode:ses_a", "source": "opencode", "created_at": 1.0, "backfilled_dates": True}),
		("p2", {"origin": "memento", "session_id": "opencode:ses_unknown", "source": "opencode", "created_at": 2.0}),
		("p3", {"origin": "interactive", "created_at": 3.0}),
	]
	assert mod.plan_backfill(points, state) == []


def test_backfill_preserva_ascended_at_desde_iso_y_setea_last_reinforced():
	mod = _load_module()
	state = {"registry": {"opencode": {"opencode:ses_a": {"created_at": "2026-08-12T20:35:06.300000Z"}}}}
	points = [("p1", {"origin": "memento", "source": "opencode", "session_id": "opencode:ses_a", "created_at": "2026-09-17T14:06:34+00:00"})]
	plan = mod.plan_backfill(points, state)
	upd = plan[0]["payload"]
	asc = _epoch("2026-09-17T14:06:34+00:00")
	assert upd["backfilled_dates"] is True
	assert upd["ascended_at"] == asc
	assert upd["last_reinforced_at"] == asc
	assert upd["created_at"] == _epoch("2026-08-12T20:35:06.300000Z")


def test_backfill_salta_lo_ya_backfilleado_por_ascended_at():
	"""Compat: la 1ª pasada no puso el marcador, solo `ascended_at` → no re-procesar."""
	mod = _load_module()
	state = {"registry": {"opencode": {"opencode:ses_a": {"created_at": "2026-08-12T20:35:06.300000Z"}}}}
	points = [("p1", {"origin": "memento", "source": "opencode", "session_id": "opencode:ses_a", "created_at": 1789000000.0, "ascended_at": 1789000000.0})]
	assert mod.plan_backfill(points, state) == []
