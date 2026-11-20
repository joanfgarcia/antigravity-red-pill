"""MEM-011 · F3 — el fixture reconstruye el árbol sin escribir en el Búnker.

Lo que se prueba aquí es el instrumento, no el enrutado: que las hojas queden
colgadas de SU parte (una cadena que el recall debe subir en dos saltos) y que
una sesión sin raíz no se re-parente a un padre inexistente.
"""

from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mem011_fixture_probe.py"


def _fixture_module() -> Any:
	spec = importlib.util.spec_from_file_location("mem011_fixture_probe", SCRIPT)
	assert spec is not None and spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def _root(session_id: str) -> Dict[str, Any]:
	from red_pill.metabolism.hub_synthesis import hub_point_id

	return {
		"id": hub_point_id("work_memories", session_id),
		"vector": [0.0, 0.0, 0.0, 0.0],
		"payload": {
			"node_type": "synthesis_hub",
			"lazarus_phase": "synthesis_hub",
			"session_id": session_id,
			"content": "Resumen raíz de la sesión",
		},
	}


def _leaf(point_id: str, session_id: str, content: str) -> Dict[str, Any]:
	return {
		"id": point_id,
		"vector": [0.0, 0.0, 0.0, 0.0],
		"payload": {
			"node_type": "memento_engram",
			"session_id": session_id,
			"source_lines": "memento/index.md#l1-2",
			"content": content,
			"created_at": 1.0,
		},
	}


def _plan_with_parts(monkeypatch: Any) -> None:
	"""Plan determinista de 2 partes (la mitad de miembros cada una)."""
	from red_pill.metabolism import hub_parts

	def fake_plan(session_id: str, members: List[Any], budget: int, root: Any = None) -> Dict[str, Any]:
		half = max(1, len(members) // 2)
		return {
			"polaroids": 2,
			"unmapped": 0,
			"oversized": [],
			"needs_parts": True,
			"parts": [
				hub_parts.PartPlan(index=0, polaroid_keys=["0001-0040"], members=list(members[:half])),
				hub_parts.PartPlan(index=1, polaroid_keys=["0041-0080"], members=list(members[half:])),
			],
		}

	monkeypatch.setattr(hub_parts, "plan_session_parts", fake_plan)


def test_el_fixture_reparenta_cada_hoja_a_su_parte(monkeypatch):
	fp = _fixture_module()
	_plan_with_parts(monkeypatch)
	root = _root("sess-1")
	master = [
		root,
		_leaf("leaf-a", "sess-1", "germen del desk y hashes"),
		_leaf("leaf-b", "sess-1", "límites de documentos KB"),
	]

	stats: Counter = Counter()
	points = fp.build_tree(master, "work_memories", 8000, lambda _t: [0.1, 0.1, 0.1, 0.1], stats)
	by_id = {p["id"]: p for p in points}
	parts = [p for p in points if (p["payload"].get("hub_role") or "") == "part"]

	assert len(parts) == 2
	assert all(part["payload"]["hub_id"] == root["id"] for part in parts)
	assert all(part["payload"]["fixture"] == "mem011" for part in parts)
	assert by_id["leaf-a"]["payload"]["hub_id"] == parts[0]["id"], "la hoja cuelga de SU parte"
	assert by_id["leaf-b"]["payload"]["hub_id"] == parts[1]["id"]
	assert by_id["leaf-a"]["payload"]["hubbed"] is True
	assert stats["with_parts"] == 1 and stats["parts"] == 2


def test_una_sesion_sin_raiz_no_se_reparenta(monkeypatch):
	fp = _fixture_module()
	_plan_with_parts(monkeypatch)
	master = [
		_leaf("leaf-a", "sess-huerfana", "germen del desk"),
		_leaf("leaf-b", "sess-huerfana", "límites de documentos KB"),
	]

	stats: Counter = Counter()
	points = fp.build_tree(master, "work_memories", 8000, lambda _t: [0.1, 0.1, 0.1, 0.1], stats)
	by_id = {p["id"]: p for p in points}

	assert stats["no_root"] == 1
	assert not any((p["payload"].get("hub_role") or "") == "part" for p in points)
	assert "hub_id" not in by_id["leaf-a"]["payload"], "sin raíz no se inventa un padre"


def test_una_sesion_de_una_sola_parte_no_crea_parte(monkeypatch):
	fp = _fixture_module()
	from red_pill.metabolism import hub_parts

	monkeypatch.setattr(
		hub_parts,
		"plan_session_parts",
		lambda *_a, **_k: {"polaroids": 1, "unmapped": 0, "oversized": [], "needs_parts": False, "parts": []},
	)
	root = _root("sess-2")
	master = [root, _leaf("leaf-a", "sess-2", "una sesión corta"), _leaf("leaf-b", "sess-2", "dos turnos")]

	stats: Counter = Counter()
	points = fp.build_tree(master, "work_memories", 8000, lambda _t: [0.1, 0.1, 0.1, 0.1], stats)

	assert stats["single"] == 1 and stats["parts"] == 0
	assert len(points) == len(master), "la mitad del corpus no gana ni pierde puntos"
