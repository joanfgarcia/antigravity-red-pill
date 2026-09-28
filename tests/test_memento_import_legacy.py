"""Tests del importador legacy → Memento (funciones puras, sin Qdrant)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "memento_import_legacy.py"


def _load():
	spec = importlib.util.spec_from_file_location("memento_import_legacy_under_test", SCRIPT)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


class _Point:
	def __init__(self, payload):
		self.payload = payload


def test_infer_source_por_prefijo_y_fallback():
	m = _load()
	assert m._infer_source("telegram:uuid-1", "antigravity") == "telegram"
	assert m._infer_source("cascade-sin-prefijo", "antigravity") == "antigravity"


def test_group_sessions_ignora_fragmentos_y_sin_sesion():
	m = _load()
	pts = [
		_Point({"session_id": "s1", "type": "chronicle_node", "role": "user", "sequence_index": 2, "raw_content": "b"}),
		_Point({"session_id": "s1", "role": "assistant", "sequence_index": 1, "raw_content": "a"}),
		_Point({"session_id": "s1", "type": "idea_fragment", "role": "user", "sequence_index": 3, "raw_content": "x"}),
		_Point({"role": "user", "raw_content": "sin-sesion"}),
	]
	sessions = m._group_sessions(pts)
	assert list(sessions) == ["s1"]
	assert len(sessions["s1"]) == 2


def test_messages_orden_por_sequence_y_contenido():
	m = _load()
	payloads = [
		{"role": "assistant", "sequence_index": 2, "raw_content": "dos"},
		{"role": "user", "sequence_index": 1, "refined_content": "uno"},
		{"role": "user", "sequence_index": 3, "content": "   "},
	]
	msgs = m._messages(payloads)
	assert [x["content"] for x in msgs] == ["uno", "dos"]
	assert msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant"
