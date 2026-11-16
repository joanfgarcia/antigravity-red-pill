"""RFC-OLV-001 · los dos arreglos del 2026-11-16 (noche).

1. **Ceguera**: el recall ocultaba a los miembros por el flag `hubbed`, así que
   un marcador con padre inexistente quedaba **inrecuperable** y su
   `recall_count` no podía subir nunca. Ahora se excluye por `hub_id` que
   EXISTE: un huérfano vuelve a ser visible y, si se usa, se refuerza.
2. **`limit_sessions`**: el tope contaba la posición en el diccionario, no las
   sesiones sintetizadas; un prefijo de sesiones de un solo miembro se comía el
   cupo y la cola no se visitaba jamás.
"""

from qdrant_client.http import models

from red_pill.memory import MemoryManager
from red_pill.metabolism import hub_synthesis as hs

_HUB = "00000000-0000-0000-0000-00000000ee01"
_GHOST = "00000000-0000-0000-0000-00000000eeff"
_MEMBER_OK = "00000000-0000-0000-0000-00000000ee11"
_MEMBER_ORPHAN = "00000000-0000-0000-0000-00000000ee12"
TEXT_OK = "la marea de octubre en el puerto"
TEXT_ORPHAN = "el pan de payés a las seis de la mañana"


def _seed(memory_manager: MemoryManager) -> None:
	memory_manager._ensure_collection("work_memories")
	memory_manager.client.upsert(
		collection_name="work_memories",
		points=[
			models.PointStruct(
				id=_HUB,
				vector=[0.1] * 384,
				payload={"content": "hub vivo", "lazarus_phase": "synthesis_hub", "node_type": "synthesis_hub"},
			),
			models.PointStruct(
				id=_MEMBER_OK,
				vector=[0.2] * 384,
				payload={
					"content": TEXT_OK,
					"node_type": "memento_engram",
					"session_id": "s",
					"hubbed": True,
					"hub_id": _HUB,
					"reinforcement_score": 1.0,
				},
			),
			models.PointStruct(
				id=_MEMBER_ORPHAN,
				vector=[0.3] * 384,
				payload={
					"content": TEXT_ORPHAN,
					"node_type": "memento_engram",
					"session_id": "s",
					"hubbed": True,
					"hub_id": _GHOST,  # el padre no existe
					"reinforcement_score": 1.0,
				},
			),
		],
	)


def test_orphan_member_is_recallable_again(memory_manager: MemoryManager, monkeypatch):
	"""Un miembro con padre inexistente deja de estar ciego."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "SW_HUBS_ENABLED", True)
	_seed(memory_manager)

	hits = memory_manager.search_and_reinforce("work_memories", TEXT_ORPHAN, limit=5, caller="test")
	ids = {str(getattr(h, "id", "")) for h in hits}
	assert _MEMBER_ORPHAN in ids, "un marcador huérfano debe volver al recall"

	payload = memory_manager.client.retrieve(collection_name="work_memories", ids=[_MEMBER_ORPHAN], with_payload=True)[0].payload or {}
	assert int(payload.get("recall_count") or 0) >= 1, "y al recuperarse tiene que reforzarse"


def test_member_with_live_hub_stays_hidden(memory_manager: MemoryManager, monkeypatch):
	"""El miembro cuyo padre SÍ existe sigue entrando por el hub (no se duplica)."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "SW_HUBS_ENABLED", True)
	_seed(memory_manager)

	hits = memory_manager.search_and_reinforce("work_memories", TEXT_OK, limit=5, caller="test")
	ids = {str(getattr(h, "id", "")) for h in hits}
	assert _MEMBER_OK not in ids, "un miembro agrupado en un hub vivo no compite con su padre"


def test_limit_sessions_counts_synthesised_sessions(monkeypatch):
	"""El tope se gasta en sesiones sintetizadas, no en la posición del dict."""
	from types import SimpleNamespace

	groups = {
		"solo-1": [(1, {"content": "a"})],
		"solo-2": [(2, {"content": "b"})],
		"par-3": [(3, {"content": "c"}), (4, {"content": "d"})],
		"par-4": [(5, {"content": "e"}), (6, {"content": "f"})],
		"par-5": [(7, {"content": "g"}), (8, {"content": "h"})],
	}

	points = []
	for members in groups.values():
		points.extend((pid, payload) for pid, payload in members)

	mm = SimpleNamespace(
		client=SimpleNamespace(
			collection_exists=lambda *a, **k: True,
			scroll=lambda collection=None, **kw: ([SimpleNamespace(id=p, payload=pl) for p, pl in points], None),
		)
	)
	monkeypatch.setattr(hs, "group_by_session", lambda pts: groups)
	seen: list[str] = []

	def fake_synth(_mm, _col, session_id, *_a, **_k):
		seen.append(session_id)
		return "written"

	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "SW_HUBS_ENABLED", True)
	monkeypatch.setattr(hs, "_synthesize_one", fake_synth)
	stats = hs.synthesize_session_hubs(mm, collections=("work_memories",), limit_sessions=2)

	assert seen == ["par-3", "par-4"], f"el cupo debe gastarse en sesiones válidas, no en las de un miembro: {seen}"
	assert stats["sessions"] == 2


def test_limit_sessions_does_not_spend_on_skips(monkeypatch):
	"""Un skip por hash no gasta cupo: si no, el mismo prefijo se come la noche."""
	from types import SimpleNamespace

	groups = {
		"ya-hecha-1": [(1, {"content": "a"}), (2, {"content": "b"})],
		"ya-hecha-2": [(3, {"content": "c"}), (4, {"content": "d"})],
		"nueva-3": [(5, {"content": "e"}), (6, {"content": "f"})],
	}
	points = [pt for members in groups.values() for pt in members]
	mm = SimpleNamespace(
		client=SimpleNamespace(
			collection_exists=lambda *a, **k: True,
			scroll=lambda collection=None, **kw: ([SimpleNamespace(id=p, payload=pl) for p, pl in points], None),
		)
	)
	monkeypatch.setattr(hs, "group_by_session", lambda pts: groups)
	seen: list[str] = []

	def fake_synth(_mm, _col, session_id, *_a, **_k):
		seen.append(session_id)
		return "skipped" if session_id.startswith("ya-hecha") else "written"

	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "SW_HUBS_ENABLED", True)
	monkeypatch.setattr(hs, "_synthesize_one", fake_synth)
	hs.synthesize_session_hubs(mm, collections=("work_memories",), limit_sessions=1)

	assert seen == ["ya-hecha-1", "ya-hecha-2", "nueva-3"], f"dos skips no pueden gastar el cupo: {seen}"


def test_limit_sessions_zero_means_unlimited(monkeypatch):
	"""`0` no puede apagar la síntesis en silencio (el config lo usa como «sin tope»)."""
	from types import SimpleNamespace

	groups = {"a": [(1, {"content": "a"}), (2, {"content": "b"})], "b": [(3, {"content": "c"}), (4, {"content": "d"})]}
	points = [pt for members in groups.values() for pt in members]
	mm = SimpleNamespace(
		client=SimpleNamespace(
			collection_exists=lambda *a, **k: True,
			scroll=lambda collection=None, **kw: ([SimpleNamespace(id=p, payload=pl) for p, pl in points], None),
		)
	)
	monkeypatch.setattr(hs, "group_by_session", lambda pts: groups)
	seen: list[str] = []
	monkeypatch.setattr(hs, "_synthesize_one", lambda _mm, _col, sid, *_a, **_k: (seen.append(sid), "written")[1])
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "SW_HUBS_ENABLED", True)
	hs.synthesize_session_hubs(mm, collections=("work_memories",), limit_sessions=0)
	assert seen == ["a", "b"], "0 debe significar sin tope, no «ninguna»"
