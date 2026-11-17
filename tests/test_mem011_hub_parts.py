"""MEM-011 · F1 — el plan de partes es determinista y no deja hojas sin rama.

Fija: el mapeo `engrama -> polaroid -> parte`, la estabilidad del id de la parte
al crecer la sesión, y que una sesión que cabe en una polaroid no genere partes.
"""

import time

import pytest
from qdrant_client.http import models

from red_pill.memory import MemoryManager
from red_pill.metabolism.hub_parts import (
	PolaroidRange,
	part_point_id,
	plan_session_parts,
	polaroid_index_of,
)

_PREFIX = "00000000-0000-0000-0000-00000000cc"


def _member(n: int, lines: str, chars: int = 100) -> tuple:
	payload = {
		"session_id": "probe:ses_mem011",
		"source_lines": f"memento/index.md#{lines}",
		"content": "x" * chars,
		"node_type": "memento_engram",
		"created_at": time.time(),
	}
	return (f"{_PREFIX}{n:02d}", payload)


@pytest.fixture()
def polaroids(monkeypatch):
	"""Tres polaroids con rangos de línea contiguos (sin tocar el disco)."""

	def fake_for_session(session_id, root=None):
		return [
			PolaroidRange(key="0001-0040", lo=10, hi=100),
			PolaroidRange(key="0041-0080", lo=101, hi=200),
			PolaroidRange(key="0081-0120", lo=201, hi=300),
		]

	monkeypatch.setattr("red_pill.metabolism.hub_parts.polaroids_for_session", fake_for_session)
	return None


def test_mapeo_engrama_polaroid_parte(polaroids):
	members = [_member(1, "l20-30"), _member(2, "l120-150"), _member(3, "l250-260")]
	plan = plan_session_parts("probe:ses_mem011", members, budget=1000)
	assert plan["polaroids"] == 3
	assert plan["unmapped"] == 0
	# 3 polaroids de 100 chars con presupuesto 1000 → una sola parte: no se materializa.
	assert plan["needs_parts"] is False
	assert [len(p.members) for p in plan["parts"]] == [3]


def test_presupuesto_parte_y_mapeo(polaroids):
	members = [
		_member(1, "l20-30", 400),
		_member(2, "l120-150", 400),
		_member(3, "l250-260", 400),
	]
	plan = plan_session_parts("probe:ses_mem011", members, budget=500)
	assert plan["needs_parts"] is True
	assert [list(p.polaroid_keys) for p in plan["parts"]] == [["0001-0040"], ["0041-0080"], ["0081-0120"]]
	assert [len(p.members) for p in plan["parts"]] == [1, 1, 1]


def test_polaroid_no_se_reparte(polaroids):
	# Dos hojas de la MISMA polaroid, y presupuesto que forzaría a partirlas si la
	# unidad fuera la hoja: deben viajar juntas.
	members = [_member(1, "l20-30", 400), _member(2, "l90-99", 400), _member(3, "l120-150", 400)]
	plan = plan_session_parts("probe:ses_mem011", members, budget=500)
	assert plan["needs_parts"] is True
	assert len(plan["parts"][0].members) == 2  # las dos de la polaroid 1
	assert plan["parts"][0].polaroid_keys == ["0001-0040"]


def test_id_de_parte_estable_al_crecer(polaroids):
	# La clave es la PRIMERA polaroid: añadir polaroids al final no cambia el id
	# de las partes anteriores (solo la última crece).
	before = plan_session_parts("probe:ses_mem011", [_member(1, "l20-30", 400), _member(2, "l120-150", 400)], budget=500)
	assert [part_point_id("work_memories", "probe:ses_mem011", p.part_key) for p in before["parts"]] == [
		part_point_id("work_memories", "probe:ses_mem011", "0001-0040"),
		part_point_id("work_memories", "probe:ses_mem011", "0041-0080"),
	]


def test_sin_polaroids_no_hay_partes(monkeypatch):
	monkeypatch.setattr("red_pill.metabolism.hub_parts.polaroids_for_session", lambda session_id, root=None: [])
	plan = plan_session_parts("probe:ses_mem011", [_member(1, "l20-30")], budget=500)
	assert plan["polaroids"] == 0
	assert plan["needs_parts"] is False
	assert plan["unmapped"] == 1


def test_sesion_sin_split_es_una_polaroid_implicita(monkeypatch):
	monkeypatch.setattr(
		"red_pill.metabolism.hub_parts.polaroids_for_session",
		lambda session_id, root=None: [PolaroidRange(key="index", lo=None, hi=None)],
	)
	plan = plan_session_parts("probe:ses_mem011", [_member(1, "l20-30"), _member(2, "l40-50")], budget=500)
	assert plan["polaroids"] == 1
	assert plan["needs_parts"] is False
	assert plan["unmapped"] == 0


def test_indice_por_rango():
	pols = [PolaroidRange("a", 10, 100), PolaroidRange("b", 101, 200)]
	assert polaroid_index_of("memento/index.md#l20-30", pols) == 0
	assert polaroid_index_of("memento/index.md#l190-210", pols) == 1
	assert polaroid_index_of("", pols) is None


def test_marcado_de_parte_no_rompe_el_recall():
	"""La parte marcada `hubbed=True` + `hub_id=<raíz>` es lo que el reaper cuenta."""
	memory = MemoryManager()
	collection = "work_memories"
	memory._ensure_collection(collection)
	root = "00000000-0000-0000-0000-00000000cd01"
	part = part_point_id(collection, "probe:ses_mem011", "0001-0040")
	memory.client.upsert(
		collection_name=collection,
		points=[
			models.PointStruct(
				id=root,
				vector=[0.1] * 384,
				payload={"node_type": "synthesis_hub", "lazarus_phase": "synthesis_hub", "hub_role": "root"},
			),
			models.PointStruct(
				id=part,
				vector=[0.1] * 384,
				payload={
					"node_type": "synthesis_hub",
					"lazarus_phase": "synthesis_hub",
					"hub_role": "part",
					"hubbed": True,
					"hub_id": root,
				},
			),
		],
	)
	points, _ = memory.client.scroll(
		collection_name=collection,
		scroll_filter=models.Filter(must=[models.FieldCondition(key="hub_id", match=models.MatchValue(value=root))]),
		with_payload=True,
		limit=10,
	)
	assert [str(p.id) for p in points] == [part]


def test_exclusion_estructural_acepta_matchany():
	"""El rescate keyword debe excluir miembros por `hub_id` (MatchAny), no saltarse."""
	from qdrant_client.http import models as qm

	memory = MemoryManager()
	exclusions = [
		qm.FieldCondition(key="hub_id", match=qm.MatchAny(any=["h1", "h2"])),
		qm.FieldCondition(key="lazarus_phase", match=qm.MatchValue(value="texture_shadow")),
	]
	assert memory._excluded_by({"hub_id": "h2"}, exclusions) is True
	assert memory._excluded_by({"lazarus_phase": "texture_shadow"}, exclusions) is True
	assert memory._excluded_by({"hub_id": "h3"}, exclusions) is False
	assert memory._excluded_by({}, exclusions) is False
