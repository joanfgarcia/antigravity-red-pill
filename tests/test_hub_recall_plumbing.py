"""HUB-RECALL-001: fontanería del hub como índice (D-02/D-07/D-15, flags OFF)."""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any, Dict, List, Tuple

from red_pill.memento.hub_terms import (
	hub_terms_chars,
	is_anchor,
	is_anchor_occurrence,
	select_hub_terms,
	term_idf,
)
from red_pill.metabolism.hub_synthesis import (
	HUB_SYNTH_VERSION,
	_synthesize_one,
	backup_hub_payload,
	hub_input_hash,
	hub_point_id,
	is_stale_hub,
	promote_compact_hub,
	reconcile_hub_blocks,
	refresh_hub_block_state,
	restore_hub_payload,
)


def _fake_client(docs: List[Tuple[str, Dict[str, Any]]]) -> Any:
	class _Client:
		def scroll(self, collection, **kwargs):
			batch = [types.SimpleNamespace(id=pid, payload=payload) for pid, payload in docs]
			limit = int(kwargs.get("limit") or len(batch))
			return batch[:limit], None

		def retrieve(self, collection_name, ids, **kwargs):
			wanted = {str(i) for i in ids}
			return [types.SimpleNamespace(id=pid, payload=payload, vector=None) for pid, payload in docs if str(pid) in wanted]

	return _Client()


def _manager(client: Any, **overrides: Any) -> Any:
	from red_pill.memory import MemoryManager

	manager = object.__new__(MemoryManager)
	manager.client = client
	defaults: Dict[str, Any] = {
		"SW_HUB_KEYWORD_ENABLED": True,
		"SW_HUB_BOOST_ENABLED": True,
		"MEMORY_HUB_KEYWORD_MAX_HUBS": 500,
	}
	defaults.update(overrides)
	manager.cfg = types.SimpleNamespace(**defaults)
	return manager


def test_select_hub_terms_soft_budget_never_splits() -> None:
	text = "OBS-005 neon-link plan estrategia sistema cocina nevera microondas"
	terms = select_hub_terms(text, title="Plan OBS-005", max_chars=20)

	assert terms[0] == "OBS-005"
	total = hub_terms_chars(terms)
	assert total >= 20
	# La última keyword es la que cruza el presupuesto: sin ella no se llega.
	assert total - len(terms[-1]) < 20
	# Nunca se parte una keyword ni se cuelan genéricos de la stoplist.
	assert all(term in text for term in terms)
	assert "plan" not in [term.lower() for term in terms]
	assert "estrategia" not in [term.lower() for term in terms]


def test_select_hub_terms_stops_immediately_at_budget() -> None:
	terms = select_hub_terms("OBS-005 neon-link cocina", max_chars=5)
	assert terms == ["OBS-005"] or hub_terms_chars(terms) >= 5
	# Con total ya >= presupuesto no se añade otra keyword.
	assert hub_terms_chars(terms[:1]) >= 5


def test_is_anchor_prefers_identifiers_and_proper_nouns() -> None:
	assert is_anchor("OBS-005")
	assert is_anchor("v7.22.0")
	assert is_anchor("mcp_server.py")
	assert is_anchor("Initech")
	assert not is_anchor("cocina")
	assert not is_anchor("sistema")


def test_sentence_initial_capital_is_not_an_anchor() -> None:
	# Una palabra que también aparece en minúsculas es común, no un nombre propio.
	lower_seen = {"además", "riesgo", "sistema"}
	assert not is_anchor_occurrence("Además", lower_seen)
	assert not is_anchor_occurrence("Riesgo", lower_seen)
	assert is_anchor_occurrence("OBS-005", lower_seen)
	assert is_anchor_occurrence("Initech", set())
	assert is_anchor_occurrence("CORE", lower_seen)


def test_select_hub_terms_ignores_discourse_markers() -> None:
	terms = select_hub_terms("Además, OBS-005 y el informe. Además, otra cosa.", title="", max_chars=7)
	assert terms[0] == "OBS-005"
	assert "además" not in [term.lower() for term in terms]


def test_hub_terms_chars_matches_sum_of_whole_terms() -> None:
	assert hub_terms_chars(["OBS-005", "neon-link"]) == 16


def test_term_idf_monotonic() -> None:
	assert term_idf(100, 1) > term_idf(100, 10)
	assert term_idf(100, 100) >= 0.0
	assert term_idf(0, 0) == 0.0


def test_is_stale_hub_version_and_budget() -> None:
	assert is_stale_hub({"hub_synth_version": 2})
	assert is_stale_hub({"hub_synth_version": HUB_SYNTH_VERSION - 1})
	# `hub_summary_over_budget` es el target (900), no el tope duro (1.000):
	# un v3 de 950 chars es válido y no debe re-sintetizarse en bucle.
	assert not is_stale_hub(
		{
			"hub_synth_version": HUB_SYNTH_VERSION,
			"hub_summary_over_budget": True,
			"hub_title": "t",
			"content": "t\n" + ("x" * 950),
		},
		hard_limit=1000,
	)
	assert is_stale_hub(
		{
			"hub_synth_version": HUB_SYNTH_VERSION,
			"hub_title": "t",
			"content": "t\n" + ("x" * 1001),
		},
		hard_limit=1000,
	)
	assert not is_stale_hub(
		{
			"hub_synth_version": HUB_SYNTH_VERSION,
			"hub_title": "t",
			"content": "t\nresumen corto",
		},
		hard_limit=1000,
	)


def test_hub_keyword_hits_ranks_terms_and_falls_back_to_content() -> None:
	client = _fake_client(
		[
			("hub-a", {"node_type": "synthesis_hub", "hub_title": "Obs", "hub_terms": ["OBS-005", "neon-link"]}),
			("hub-b", {"node_type": "synthesis_hub", "hub_title": "Cocina", "hub_terms": ["cocina", "nevera"]}),
			# Hub viejo sin hub_terms: cae a `content` (D-11: sin migrar).
			("hub-c", {"node_type": "synthesis_hub", "hub_title": "Legacy", "content": "hablamos de neon-link"}),
		]
	)
	manager = _manager(client)
	hits = manager._hub_keyword_hits("OBS-005 neon-link", "work_memories", limit=5)
	ids = [pid for pid, _ in hits]

	assert "hub-a" in ids
	assert ids[0] == "hub-a"
	assert "hub-c" in ids
	assert "hub-b" not in ids
	assert all(score > 0 for _, score in hits)


def test_hub_keyword_hits_disabled_by_flag() -> None:
	client = _fake_client([("hub-a", {"node_type": "synthesis_hub", "hub_terms": ["OBS-005"]})])
	manager = _manager(client, SW_HUB_KEYWORD_ENABLED=False)
	assert manager._hub_keyword_hits("OBS-005", "work_memories") == []


def test_boost_hubs_lifts_hub_inside_top_n_only() -> None:
	hub = types.SimpleNamespace(payload={"node_type": "synthesis_hub", "hub_terms": ["OBS-005"]})
	other = types.SimpleNamespace(payload={"content": "otra cosa"})
	candidates = {"hub": hub, "other": other}
	manager = _manager(_fake_client([]))

	boosted = manager._boost_hubs("OBS-005", [("other", 0.05), ("hub", 0.04)], candidates)
	assert [pid for pid, _ in boosted][0] == "hub"
	assert dict(boosted)["hub"] > 0.04

	# Fuera del top-N no se toca.
	fused = [("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6), ("e", 0.5), ("hub", 0.4)]
	candidates.update({k: other for k in ("a", "b", "c", "d", "e")})
	unchanged = manager._boost_hubs("OBS-005", fused, candidates)
	assert dict(unchanged)["hub"] == 0.4


def test_hub_pointer_for_hub_and_member() -> None:
	from red_pill.mcp_server import _hub_pointer

	hub_line = _hub_pointer(
		{
			"node_type": "synthesis_hub",
			"_point_id": "hub-123",
			"session_id": "ses_1",
			"hub_members_count": 4,
			"hub_partition_ranges": [0, 2, 2, 4],
			"hub_terms": ["OBS-005"],
			"hub_synth_version": 3,
		}
	)
	assert "hub_id=hub-123" in hub_line
	assert "members=4" in hub_line
	assert "ranges=0-2,2-4" in hub_line

	member_line = _hub_pointer({"node_type": "memento_engram", "hub_id": "hub-123", "session_id": "ses_1"})
	assert "hub_id=hub-123" in member_line
	assert "member" in member_line
	assert _hub_pointer({"content": "sin hub"}) == ""


async def test_hub_members_disabled_by_flag(monkeypatch) -> None:
	import red_pill.config as config_module
	from red_pill.mcp_server import handle_hub_members

	monkeypatch.setattr(config_module, "get_config", lambda: types.SimpleNamespace(SW_HUB_MEMBERS_ENABLED=False))
	result = await handle_hub_members({"hub_id": "hub-123"})
	assert "disabled" in result[0].text


def test_recall_and_hub_members_actions_keep_their_handlers() -> None:
	# Regresión: un helper insertado entre el decorador y `handle_recall`
	# registró `_hub_pointer` como handler de recall y dejó la acción muerta.
	from red_pill.mcp_server import handle_recall, registry

	actions = registry._actions["bunker_memory_api"]
	assert actions["recall"]["handler"] is handle_recall
	assert "hub_members" in actions


class _BackupClient:
	"""Cliente Qdrant mínimo con estado para probar backup/restore."""

	def __init__(self, points: Dict[str, Dict[str, Any]]) -> None:
		self.points = points
		self.upserts: List[Any] = []
		self.deleted: List[Tuple[List[str], List[Any]]] = []
		self.set_calls: List[Tuple[Dict[str, Any], List[Any]]] = []

	def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
		return [types.SimpleNamespace(id=pid, payload=dict(self.points[pid]), vector=[0.1, 0.2]) for pid in ids if pid in self.points]

	def collection_exists(self, collection_name):
		return True

	def scroll(self, collection_name, **kwargs):
		points = list(self.points.items())
		flt = kwargs.get("scroll_filter")
		if flt is not None:
			must = getattr(flt, "must", None) or []
			should = getattr(flt, "should", None) or []
			for cond in must:
				key, value = cond.key, cond.match.value
				points = [(pid, pl) for pid, pl in points if pl.get(key) == value]
			if should:
				pairs = [(cond.key, cond.match.value) for cond in should]
				points = [(pid, pl) for pid, pl in points if any(pl.get(key) == value for key, value in pairs)]
		return [types.SimpleNamespace(id=pid, payload=dict(pl)) for pid, pl in points], None

	def upsert(self, collection_name, points, **kwargs):
		self.upserts.append((collection_name, points))
		self.points[str(points[0].id)] = dict(points[0].payload)

	def delete_payload(self, collection_name, keys, points, **kwargs):
		self.deleted.append((list(keys), list(points)))
		for pid in points:
			for key in keys:
				self.points[str(pid)].pop(key, None)

	def set_payload(self, collection_name, payload, points, **kwargs):
		self.set_calls.append((dict(payload), list(points)))
		for pid in points:
			self.points[str(pid)].update(payload)


def test_backup_and_restore_hub_reverts_payload_and_member_marks(tmp_path) -> None:
	collection = "work_memories"
	session_id = "ses_backup"
	hub_id = hub_point_id(collection, session_id)
	client = _BackupClient(
		{
			hub_id: {"node_type": "synthesis_hub", "content": "hub viejo", "hub_synth_version": 0},
			"m1": {"node_type": "memento_engram", "session_id": session_id, "content": "uno", "hubbed": True, "hub_id": hub_id},
			"m2": {"node_type": "memento_engram", "session_id": session_id, "content": "dos"},
		}
	)
	manager = types.SimpleNamespace(client=client)

	path = backup_hub_payload(manager, collection, session_id, backup_dir=str(tmp_path))
	assert path is not None
	assert (tmp_path / Path(path).name).exists()

	# Simula la migración: hub nuevo + ambos miembros marcados.
	client.points[hub_id] = {"node_type": "synthesis_hub", "content": "hub nuevo", "hub_synth_version": 3}
	client.points["m2"].update({"hubbed": True, "hub_id": hub_id})

	assert restore_hub_payload(manager, str(path)) is True
	assert client.points[hub_id]["content"] == "hub viejo"
	assert client.points[hub_id]["hub_synth_version"] == 0
	assert client.points["m1"].get("hubbed") is True
	# m2 no estaba marcado antes: el restore retira hubbed/hub_id.
	assert "hubbed" not in client.points["m2"]
	assert any("hubbed" in keys for keys, _ in client.deleted)


def test_refresh_hub_block_state_blocks_and_unblocks_on_member_promotion() -> None:
	collection = "work_memories"
	session_id = "ses_promotion"
	hub_id = hub_point_id(collection, session_id)
	client = _BackupClient(
		{
			hub_id: {"node_type": "synthesis_hub", "session_id": session_id, "content": "hub", "hub_members_count": 0},
		}
	)
	manager = types.SimpleNamespace(client=client)

	# Isla: 0 miembros.
	state = refresh_hub_block_state(manager, collection, session_id)
	assert state is not None and state["blocked"] is True
	assert state["reason"] == "no_members"
	assert client.points[hub_id]["hub_migration_blocked"] is True

	# Un solo miembro: singleton.
	client.points["m1"] = {"node_type": "memento_engram", "session_id": session_id, "content": "uno"}
	state = refresh_hub_block_state(manager, collection, session_id)
	assert state is not None and state["blocked"] is True
	assert state["reason"] == "singleton"

	# Ascensión de un segundo miembro: se desbloquea y se cuenta.
	client.points["m2"] = {"node_type": "memento_engram", "session_id": session_id, "content": "dos"}
	state = refresh_hub_block_state(manager, collection, session_id)
	assert state is not None and state["blocked"] is False
	assert state["members"] == 2
	assert client.points[hub_id]["hub_migration_blocked"] is False
	assert client.points[hub_id]["hub_members_count"] == 2


def test_reconcile_hub_blocks_marks_islands_and_clears_recovered() -> None:
	collection = "work_memories"
	island = hub_point_id(collection, "ses_island")
	recovered = hub_point_id(collection, "ses_recovered")
	client = _BackupClient(
		{
			island: {"node_type": "synthesis_hub", "session_id": "ses_island", "content": "isla"},
			recovered: {
				"node_type": "synthesis_hub",
				"session_id": "ses_recovered",
				"content": "recuperado",
				"hub_migration_blocked": True,
				"hub_migration_blocked_reason": "no_members",
			},
			"m1": {"node_type": "memento_engram", "session_id": "ses_recovered", "content": "uno"},
			"m2": {"node_type": "memento_engram", "session_id": "ses_recovered", "content": "dos"},
		}
	)
	manager = types.SimpleNamespace(client=client)

	rows = reconcile_hub_blocks(manager, collections=(collection,), apply=True)
	by_id = {row["hub_id"]: row for row in rows}
	assert by_id[island]["blocked"] is True
	assert by_id[island]["reason"] == "no_members"
	assert by_id[recovered]["blocked"] is False
	assert client.points[island]["hub_migration_blocked"] is True
	assert client.points[recovered]["hub_migration_blocked"] is False
	assert client.points[recovered]["hub_members_count"] == 2


def test_promote_compact_hub_metadata_without_touching_content() -> None:
	collection = "work_memories"
	session_id = "ses_compact"
	hub_id = hub_point_id(collection, session_id)
	content = "Titulo compacto del hub\nResumen que ya cabe en el tope duro."
	client = _BackupClient(
		{
			hub_id: {"node_type": "synthesis_hub", "session_id": session_id, "content": content, "hub_synth_version": 2},
			"m1": {"node_type": "memento_engram", "session_id": session_id, "content": "uno"},
			"m2": {"node_type": "memento_engram", "session_id": session_id, "content": "dos"},
		}
	)
	manager = types.SimpleNamespace(client=client)
	assert promote_compact_hub(manager, collection, session_id, hard_limit=1000) == "promoted"
	assert client.points[hub_id]["hub_synth_version"] == HUB_SYNTH_VERSION
	assert client.points[hub_id]["hub_title"] == "Titulo compacto del hub"
	assert client.points[hub_id]["content"] == content
	assert client.points[hub_id]["hub_members_count"] == 2
	assert client.points[hub_id]["hub_terms"]
	assert client.points[hub_id]["hub_promoted_mechanical"] is True


def test_promote_compact_hub_rejects_over_hard() -> None:
	collection = "work_memories"
	session_id = "ses_compact_big"
	hub_id = hub_point_id(collection, session_id)
	client = _BackupClient(
		{
			hub_id: {
				"node_type": "synthesis_hub",
				"session_id": session_id,
				"content": "Titulo\n" + ("x" * 1200),
				"hub_synth_version": 2,
			}
		}
	)
	manager = types.SimpleNamespace(client=client)
	assert promote_compact_hub(manager, collection, session_id, hard_limit=1000) == "over_hard"
	assert client.points[hub_id]["hub_synth_version"] == 2


def test_synthesize_one_skip_clears_blocked_when_members_return() -> None:
	collection = "work_memories"
	session_id = "ses_skip_unblock"
	hub_id = hub_point_id(collection, session_id)
	members = [
		("m1", {"node_type": "memento_engram", "session_id": session_id, "created_at": 1.0}),
		("m2", {"node_type": "memento_engram", "session_id": session_id, "created_at": 2.0}),
	]
	client = _BackupClient(
		{
			hub_id: {
				"node_type": "synthesis_hub",
				"session_id": session_id,
				"hub_input_hash": hub_input_hash([pid for pid, _ in members]),
				"hub_migration_blocked": True,
				"hub_migration_blocked_reason": "singleton",
				"hub_members_count": 1,
			},
		}
	)
	manager = types.SimpleNamespace(client=client)

	result = _synthesize_one(
		manager,
		collection,
		session_id,
		members,
		synthesizer=lambda *_args, **_kwargs: {},
		affect_fn=lambda *_args, **_kwargs: ("neutral", 0.5),
		force=False,
	)
	assert result == "skipped"
	assert client.points[hub_id]["hub_migration_blocked"] is False
	assert client.points[hub_id]["hub_members_count"] == 2
