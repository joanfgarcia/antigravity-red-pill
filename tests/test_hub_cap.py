"""Tope de hubs por ciclo (SW_HUBS_MAX_SESSIONS_PER_CYCLE): plumbing del cap."""

from __future__ import annotations

import red_pill.config as cfg
import red_pill.metabolism.hub_synthesis as hs
import red_pill.metabolism.thread_synthesis as ts
from red_pill.metabolism.phases import consolidation as cons


def _patch(monkeypatch, captured):
	def fake_synth(mm, collections=("work_memories", "social_memories"), limit_sessions=None, synthesizer=None, affect_fn=None):
		captured["limit"] = limit_sessions
		return {"enabled": True, "hubs_written": 1}

	monkeypatch.setattr(hs, "synthesize_session_hubs", fake_synth)
	monkeypatch.setattr(ts, "weave_member_threads", lambda mm: {"enabled": True})


def test_cap_se_pasa_como_limit(monkeypatch):
	captured = {}
	_patch(monkeypatch, captured)
	monkeypatch.setattr(cfg, "SW_HUBS_MAX_SESSIONS_PER_CYCLE", 7)
	cons._run_hub_and_thread(object())
	assert captured["limit"] == 7


def test_cap_cero_es_sin_tope(monkeypatch):
	captured = {}
	_patch(monkeypatch, captured)
	monkeypatch.setattr(cfg, "SW_HUBS_MAX_SESSIONS_PER_CYCLE", 0)
	cons._run_hub_and_thread(object())
	assert captured["limit"] is None
