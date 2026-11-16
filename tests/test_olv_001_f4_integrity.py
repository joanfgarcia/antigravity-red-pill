"""RFC-OLV-001 · F4 — la señal de integridad dice la verdad.

Antes, `hub_coverage_pct` contaba el flag `hubbed`: un marcador huérfano inflaba
la métrica (99,4 % con un cuarto del contenido sin padre). Ahora cuenta **nodos
que existen** y expone `orphan_markers` / `hub_integrity_ok`.
"""

from qdrant_client.http import models

from red_pill.memory import MemoryManager
from red_pill.metabolism.sw_observability import compute_sw_health

_HUB = "00000000-0000-0000-0000-00000000ee01"
_MEMBER_OK = "00000000-0000-0000-0000-00000000ee11"
_MEMBER_ORPHAN = "00000000-0000-0000-0000-00000000ee12"
_GHOST_HUB = "00000000-0000-0000-0000-00000000eeff"

SESSION = "opencode:ses_f4"


def _content(pid: str, hub_id: str) -> models.PointStruct:
	return models.PointStruct(
		id=pid,
		vector=[0.1] * 384,
		payload={
			"content": "un turno",
			"node_type": "memento_engram",
			"session_id": SESSION,
			"hubbed": True,
			"hub_id": hub_id,
			"created_at": 1.0,
			"last_recalled_at": 1.0,
		},
	)


def test_coverage_counts_existing_nodes_and_flags_orphans(memory_manager: MemoryManager):
	memory_manager._ensure_collection("work_memories")
	memory_manager.client.upsert(
		collection_name="work_memories",
		points=[
			models.PointStruct(
				id=_HUB,
				vector=[0.1] * 384,
				payload={"content": "rama", "lazarus_phase": "synthesis_hub", "node_type": "synthesis_hub"},
			),
			_content(_MEMBER_OK, _HUB),
			_content(_MEMBER_ORPHAN, _GHOST_HUB),  # el padre no existe
		],
	)

	health = compute_sw_health(memory_manager, collections=("work_memories",))
	col = health["collections"]["work_memories"]

	assert col["hubbed_members"] == 2, "los dos se declaran agrupados"
	assert col["orphan_markers"] == 1, "uno apunta a un padre inexistente"
	assert col["hub_integrity_ok"] is False
	assert col["hub_coverage_pct"] == 50.0, "la cobertura cuenta nodos: 1 de 2"


def test_coverage_is_ok_when_all_parents_exist(memory_manager: MemoryManager):
	memory_manager._ensure_collection("work_memories")
	memory_manager.client.upsert(
		collection_name="work_memories",
		points=[
			models.PointStruct(
				id=_HUB,
				vector=[0.1] * 384,
				payload={"content": "rama", "lazarus_phase": "synthesis_hub", "node_type": "synthesis_hub"},
			),
			_content(_MEMBER_OK, _HUB),
		],
	)

	col = compute_sw_health(memory_manager, collections=("work_memories",))["collections"]["work_memories"]
	assert col["orphan_markers"] == 0
	assert col["hub_integrity_ok"] is True
	assert col["hub_coverage_pct"] == 100.0
