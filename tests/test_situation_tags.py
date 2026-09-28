"""RFC-004 P3 — la solera (M8) consume tags en vez de destilar texto.

Puro para `aggregate_tags`; `_upsert_semaphore` con fakes (sin Qdrant real).
"""

from __future__ import annotations

from typing import Any, Dict, List

import red_pill.config as cfg
from red_pill.metabolism.situation_semaphore import (
	_default_merger,
	_upsert_semaphore,
	aggregate_tags,
)


class _FakeClient:
	def __init__(self, prev=None):
		self._prev = prev or []
		self.set_payloads: List[Dict[str, Any]] = []

	def collection_exists(self, name) -> bool:
		return True

	def retrieve(self, coll, ids):
		return self._prev

	def set_payload(self, collection_name, payload, points):
		self.set_payloads.append({"payload": payload, "points": points})


class _FakeMM:
	"""Fake que VALIDA con el esquema real (CreateEngramRequest) TODOS los campos
	del alta (content metadata color emotion intensity): así un typo de chroma o
	un metadata nested falla en test en vez de reventar en producción."""

	def __init__(self, prev=None):
		self.client = _FakeClient(prev)
		self.captured: List[Dict[str, Any]] = []

	def add_memory(self, **kw):
		from red_pill.schemas import CreateEngramRequest

		CreateEngramRequest(
			content=kw.get("text") or "x",
			metadata=kw.get("metadata") or {},
			color=kw.get("color", "gray"),
			emotion=kw.get("emotion", "neutral"),
			intensity=kw.get("intensity", 1.0),
		)
		self.captured.append(kw)
		return "pid"


def _boom(_text):
	raise AssertionError("el destilador NO debe llamarse en modo tag")


# ── aggregate_tags (puro) ──────────────────────────────────────────────────


def test_aggregate_sin_tags_devuelve_none():
	assert aggregate_tags([{"content": "a", "ts": 1}]) is None
	assert aggregate_tags([]) is None
	assert aggregate_tags([{"content": "a", "tag_status": "failed"}]) is None


def test_aggregate_mayoria_por_peso_de_confianza():
	items = [
		{"content": "a", "tag_status": "ok", "tag_emotion": "frustrated", "tag_theme": "work", "tag_confidence": 0.9},
		{"content": "b", "tag_status": "ok", "tag_emotion": "frustrated", "tag_theme": "work", "tag_confidence": 0.8},
		{"content": "c", "tag_status": "degraded", "tag_emotion": "positive", "tag_theme": "meta", "tag_confidence": 0.6},
	]
	agg = aggregate_tags(items)
	assert agg is not None
	assert agg["mood"] == "frustrated"
	assert agg["theme"] == "work"
	assert agg["n"] == 3
	assert agg["theme_counts"] == {"work": 2, "meta": 1}
	assert "work · frustrated (n=3)" == agg["descriptor"]
	assert 0.0 < agg["coverage"] <= 1.0


def test_aggregate_desempate_por_conteo():
	items = [
		{"content": "a", "tag_status": "ok", "tag_emotion": "tense", "tag_theme": "work", "tag_confidence": 0.5},
		{"content": "b", "tag_status": "ok", "tag_emotion": "calm", "tag_theme": "work", "tag_confidence": 0.5},
	]
	agg = aggregate_tags(items)
	assert agg is not None
	assert agg["mood"] in ("tense", "calm")  # empate exacto → determinista por max()
	# con dos iguales, max() elige la primera clave por orden de inserción
	assert agg["mood"] == "tense"


# ── _upsert_semaphore en modo tag / legacy ─────────────────────────────────


def test_tag_mode_no_destila_y_usa_tags(monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", True)
	mm = _FakeMM()
	items = [
		{"content": "a", "ts": 1, "tag_status": "ok", "tag_emotion": "frustrated", "tag_theme": "work", "tag_confidence": 0.9},
		{"content": "b", "ts": 2, "tag_status": "ok", "tag_emotion": "frustrated", "tag_theme": "work", "tag_confidence": 0.8},
		{"content": "c", "ts": 3, "tag_status": "ok", "tag_emotion": "positive", "tag_theme": "meta", "tag_confidence": 0.6},
	]
	ok = _upsert_semaphore(mm, "global", items, _boom, _default_merger, 0.2)
	assert ok is True
	assert len(mm.captured) == 1
	cap = mm.captured[0]
	assert cap["metadata"]["tag_mode"] is True
	assert cap["metadata"]["tag_theme"] == "work"
	assert cap["metadata"]["tag_mood"] == "frustrated"
	assert "work · frustrated" in cap["metadata"]["situation_recent"]
	assert cap["metadata"]["tagged_n"] == 3
	assert cap["metadata"]["affinity"] == "global"
	# el metadata debe pasar el esquema real (metadata sin dicts anidados)
	import json as _json

	assert _json.loads(cap["metadata"]["tag_emotions_json"])["frustrated"] == 2
	assert cap["color"] != cfg.DEFAULT_COLOR  # chroma del tag, no DEFAULT


def test_tag_mode_confianza_cero_no_se_infla(monkeypatch):
	"""tag_confidence 0.0 es válido y no debe convertirse en 0.5."""
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", True)
	mm = _FakeMM()
	items = [{"content": "a", "ts": 1, "tag_status": "ok", "tag_emotion": "tense", "tag_theme": "work", "tag_confidence": 0.0}]
	assert _upsert_semaphore(mm, "global", items, _boom, _default_merger, 0.2) is True
	assert mm.captured[0]["intensity"] == 0.0


def test_metadata_tag_pasa_esquema_real(monkeypatch):
	"""Guardarraíl explícito: el metadata del modo tag valida con el esquema."""
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", True)
	from red_pill.schemas import CreateEngramRequest

	mm = _FakeMM()
	items = [{"content": "a", "ts": 1, "tag_status": "ok", "tag_emotion": "calm", "tag_theme": "meta", "tag_confidence": 0.4}]
	_upsert_semaphore(mm, "global", items, _boom, _default_merger, 0.2)
	meta = mm.captured[0]["metadata"]
	assert all(not isinstance(v, dict) for v in meta.values()), "sin dicts anidados"
	CreateEngramRequest(content="x", metadata=meta)  # no lanza


def test_chroma_del_tag_es_validcolor():
	import typing

	from red_pill.metabolism.situation_semaphore import TAG_EMOTION_CHROMA
	from red_pill.schemas import ValidColor

	allowed = set(typing.get_args(ValidColor))
	assert set(TAG_EMOTION_CHROMA.values()) <= allowed


def test_mood_neutral_fuerza_payload_del_tag(monkeypatch):
	"""mood neutral (== DEFAULT_EMOTION) no debe quedar re-detectado: el set_payload
	post-alta fija emotion/color/intensity del tag (autoritativo)."""
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", True)
	mm = _FakeMM()
	items = [{"content": "a", "ts": 1, "tag_status": "ok", "tag_emotion": "neutral", "tag_theme": "work", "tag_confidence": 0.42}]
	assert _upsert_semaphore(mm, "global", items, _boom, _default_merger, 0.2) is True
	# el payload final se fuerza al tag
	assert mm.client.set_payloads, "debe forzar el payload del tag"
	forced = mm.client.set_payloads[-1]["payload"]
	assert forced["emotion"] == "neutral"
	assert forced["intensity"] == 0.42
	assert forced["color"] == "gray"  # neutral → gray (no re-detectado)


def test_tag_mode_sin_tags_no_consume(monkeypatch):
	"""Modo tag activo + turnos sin etiquetar → NO se actualiza (ni LLM)."""
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", True)
	mm = _FakeMM()
	items = [{"content": "a", "ts": 1, "tag_status": "failed"}, {"content": "b", "ts": 2}]
	ok = _upsert_semaphore(mm, "global", items, _boom, _default_merger, 0.2)
	assert ok is False
	assert mm.captured == []


def test_flag_off_mantiene_destilado_llm(monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", False)

	def _distiller(text):
		return {"situation": "trabajando en el daemon", "emotion": "blue", "intensity": 0.7}

	mm = _FakeMM()
	items = [{"content": "a", "ts": 1, "tag_status": "ok", "tag_emotion": "frustrated", "tag_theme": "work"}]
	ok = _upsert_semaphore(mm, "global", items, _distiller, _default_merger, 0.2)
	assert ok is True
	cap = mm.captured[0]
	assert cap["emotion"] == "blue"
	assert cap["metadata"]["mood"] == "blue"
	assert "tag_mode" not in cap["metadata"]
	assert "trabajando en el daemon" in cap["metadata"]["situation_recent"]


def test_fresh_vacio_no_consume(monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", True)
	mm = _FakeMM(prev=[type("P", (), {"payload": {"window_start": 100}})()])
	items = [{"content": "a", "ts": 5, "tag_status": "ok", "tag_emotion": "calm", "tag_theme": "work"}]
	ok = _upsert_semaphore(mm, "global", items, _boom, _default_merger, 0.2)
	assert ok is False
	assert mm.captured == []
