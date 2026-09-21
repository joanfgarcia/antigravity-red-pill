"""M0 single-writer — captura de sesión/afinidad + gate de purga (CONVENTIONS RULE 4).

Fija lo que introduce el primer hito: `session_id`+`affinity` viajan de la
captura a `interaction_memories`, y el TTL deja de purgar a ciegas cuando
`SW_PURGE_GATE_ENABLED` (solo purga sesiones ya renderizadas en Memento).
"""

import json
import time

import pytest

from red_pill.core.affinity import derive_affinity, parse_affinity
from red_pill.core.queue_manager import MemoryQueueManager


@pytest.fixture
def queue(tmp_path):
	return MemoryQueueManager(db_path=str(tmp_path / "bunker_queue.db"))


# ── Afinidad determinista ──────────────────────────────────────────────────


def test_affinity_workdir_y_mission():
	assert derive_affinity(workdir="/x/ia/sharing", mission_id="BIT-003") == ["ws:sharing", "mission:BIT-003"]


def test_affinity_explicito_y_dedup():
	assert derive_affinity(workdir="/x/sharing", explicit=["ws:sharing", "rfc:BIT"]) == ["ws:sharing", "rfc:BIT"]


def test_affinity_vacio_es_silent():
	assert derive_affinity() == []


def test_parse_affinity_json_csv_y_none():
	assert parse_affinity('["ws:sharing","mission:X"]') == ["ws:sharing", "mission:X"]
	assert parse_affinity("ws:a,mission:B") == ["ws:a", "mission:B"]
	assert parse_affinity(None) == []
	assert parse_affinity([]) == []


# ── La cola transporta sesión + afinidad ────────────────────────────────────


def test_cola_transporta_sesion_y_afinidad(queue):
	queue.enqueue_memory("p", "r", "assistant", originator="opencode", session_id="ses_abc", affinity=["ws:sharing", "mission:BIT"])
	item = queue.dequeue_pending(limit=1)[0]
	assert item["session_id"] == "ses_abc"
	assert json.loads(item["affinity"]) == ["ws:sharing", "mission:BIT"]


def test_cola_sin_sesion_sigue_funcionando(queue):
	queue.enqueue_memory("p", "r", "assistant", originator="claude_code")
	item = queue.dequeue_pending(limit=1)[0]
	assert item["session_id"] is None
	assert item["affinity"] is None


# ── El engrama guarda sesión + afinidad ─────────────────────────────────────


def test_record_interaction_pair_guarda_sesion_y_afinidad():
	from qdrant_client.http import models

	from red_pill.memory import MemoryManager

	mem = MemoryManager()
	uid = mem.record_interaction_pair("turno", "respuesta", originator="opencode", session_id="ses_sw", affinity=["ws:sharing"])
	assert uid
	point = mem.client.retrieve("interaction_memories", ids=[uid])[0]
	meta = (point.payload or {}).get("metadata") or {}
	assert meta.get("session_id") == "ses_sw"
	assert meta.get("affinity") == ["ws:sharing"]
	mem.client.delete("interaction_memories", points_selector=models.PointIdsList(points=[uid]), wait=True)


# ── Gate de purga: solo sesiones renderizadas ───────────────────────────────


async def test_purge_gate_solo_purga_renderizadas(tmp_path, monkeypatch):
	from qdrant_client.http import models

	import red_pill.config as cfgmod
	from red_pill.memento.registry import MementoRegistry
	from red_pill.memory import MemoryManager
	from red_pill.swarm.agents.janitor_plugins.interaction_ttl import InteractionTTLPlugin

	class FakeJanitor:
		def __init__(self):
			self.lines = []

		def log(self, msg):
			self.lines.append(msg)

	mem = MemoryManager()
	rendered_id = mem.record_interaction_pair("rendered", "r", originator="opencode", session_id="ses_render")
	unrendered_id = mem.record_interaction_pair("unrendered", "r", originator="opencode", session_id="ses_norender")
	old = int(time.time()) - 100 * 3600
	for pid in (rendered_id, unrendered_id):
		mem.client.set_payload("interaction_memories", payload={"timestamp": old}, points=[pid])

	reg_path = tmp_path / "reg.json"
	registry = MementoRegistry(path=reg_path)
	registry.upsert("opencode", "opencode:ses_render", {"dir": "2026-09/opencode/x", "month": "2026-09"})
	registry.save()

	monkeypatch.setattr(cfgmod, "SW_PURGE_GATE_ENABLED", True, raising=False)
	result = await InteractionTTLPlugin().execute(FakeJanitor(), {}, memory_manager=mem, registry_path=reg_path)
	assert result["purged"] == 1 and result.get("gate") is True

	survivors = mem.client.retrieve("interaction_memories", ids=[rendered_id, unrendered_id])
	assert [str(p.id) for p in survivors] == [unrendered_id]
	mem.client.delete("interaction_memories", points_selector=models.PointIdsList(points=[unrendered_id]), wait=True)
