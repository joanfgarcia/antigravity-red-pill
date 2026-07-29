"""Lógica pura del colapso de duplicados de archive_memories (jul 2026).

El drama: ids deterministas que incluían content[:100] + contenido derivando
entre exportaciones + semanas de re-ingesta total nocturna = cientos de copias
del mismo mensaje lógico. Aquí se fija el contrato del colapso: un punto por
(session, idx, role), fragments huérfanos fuera, axón secuencial reconstruido.
"""

from red_pill.tools.dedup_archive import choose_keepers, forward_axons, orphan_fragments


def _node(pid, session, idx, role, created_at):
	return {"id": pid, "payload": {"session_id": session, "sequence_index": idx, "role": role, "created_at": created_at, "type": "chronicle_node"}}


def test_choose_keepers_is_deterministic_and_keeps_one_per_key():
	points = [
		_node("aaa", "s1", 0, "user", 100.0),
		_node("bbb", "s1", 0, "user", 100.0),  # empate en created_at → gana el id menor
		_node("ccc", "s1", 0, "user", 50.0),
		_node("ddd", "s1", 1, "assistant", 100.0),
	]
	keepers, drop = choose_keepers(points)

	assert keepers[("s1", 0, "user")]["id"] == "aaa"
	assert sorted(drop) == ["bbb", "ccc"]
	assert keepers[("s1", 1, "assistant")]["id"] == "ddd"  # sin duplicados: intacto

	# Determinista: otra pasada sobre los mismos datos elige lo mismo
	keepers2, drop2 = choose_keepers(list(reversed(points)))
	assert keepers2[("s1", 0, "user")]["id"] == "aaa" and sorted(drop2) == sorted(drop)


def test_choose_keepers_prefers_latest_created_at():
	points = [_node("zzz", "s1", 3, "user", 900.0), _node("aaa", "s1", 3, "user", 100.0)]
	keepers, drop = choose_keepers(points)
	assert keepers[("s1", 3, "user")]["id"] == "zzz" and drop == ["aaa"]


def test_points_without_key_are_never_touched():
	legacy = {"id": "leg", "payload": {"content": "vieja época, sin session_id"}}
	keepers, drop = choose_keepers([legacy])
	assert keepers == {} and drop == []


def test_choose_keepers_prefers_copies_referenced_by_fragments():
	"""La copia con fragments gana aunque pierda por created_at o por id: podar
	el árbol entero para quedarse con un gemelo sin hijos sería tirar la
	segmentación que costó LLM."""
	points = [_node("aaa", "s1", 0, "user", 999.0), _node("zzz", "s1", 0, "user", 1.0)]
	keepers, drop = choose_keepers(points, preferred_ids=frozenset({"zzz"}))
	assert keepers[("s1", 0, "user")]["id"] == "zzz" and drop == ["aaa"]


def test_orphan_fragments_follow_their_parent():
	fragments = [
		{"id": "f1", "payload": {"parent_id": "kept", "type": "idea_fragment"}},
		{"id": "f2", "payload": {"parent_id": "dropped", "type": "idea_fragment"}},
	]
	assert orphan_fragments(fragments, surviving_ids={"kept"}) == ["f2"]


def test_execute_deletes_uuid_ids_verbatim(monkeypatch):
	"""Los point ids del archivo son UUIDs string: el selector de borrado debe
	pasarlos tal cual — una coacción a int revienta en el primer batch y dejaría
	la herramienta de la Legión rota justo donde importa."""
	from unittest.mock import MagicMock

	import red_pill.tools.dedup_archive as mod

	uid_keep = "3da688f6-0dba-4dad-93aa-c9694b3e92e6"
	uid_drop = "90d422af-689a-42d1-8110-979cc9e6d9cf"
	client = MagicMock()
	client.get_collection.return_value.points_count = 2
	client.scroll.side_effect = [
		(
			[
				MagicMock(id=uid_keep, payload={"type": "chronicle_node", "session_id": "s1", "sequence_index": 0, "role": "user", "created_at": 2}),
				MagicMock(id=uid_drop, payload={"type": "chronicle_node", "session_id": "s1", "sequence_index": 0, "role": "user", "created_at": 1}),
			],
			None,
		)
	]
	monkeypatch.setattr("qdrant_client.QdrantClient", lambda *a, **kw: client)

	mod.run(execute=True, snapshot=False)

	deleted = client.delete.call_args.kwargs.get("points_selector") or client.delete.call_args.args[1]
	assert deleted == [uid_drop]  # UUID string, tal cual


def test_forward_axons_chain_survivors_in_sequence_order():
	keepers, _ = choose_keepers(
		[
			_node("n2", "s1", 7, "assistant", 1.0),
			_node("n0", "s1", 0, "user", 1.0),
			_node("n1", "s1", 3, "assistant", 1.0),
			_node("m0", "s2", 0, "user", 1.0),  # sesión aparte: cadena aparte
		]
	)
	links = forward_axons(keepers)
	assert ("n0", "n1") in links and ("n1", "n2") in links
	assert len([link for link in links if link[0].startswith("m")]) == 0  # s2 con un solo nodo: sin axón
