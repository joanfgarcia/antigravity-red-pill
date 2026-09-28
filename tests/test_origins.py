"""AD-034/D15 — registro genérico de orígenes (session→origin) y filtros por provider.

Una sesión `origin=telegram` la renderiza el source `telegram` sea cual sea el
provider (opencode/claude_code/pi/antigravity) que la ejecutó; los sources de
cada provider la ignoran para no duplicar.
"""

from __future__ import annotations

import json

from red_pill.core import origins as org


def test_record_y_read_por_provider(tmp_path, monkeypatch):
	monkeypatch.setattr(org, "get_state_dir", lambda: tmp_path)
	org.record_origin(org.PROVIDER_OPENCODE, "s1", org.TELEGRAM_ORIGIN)
	org.record_origin(org.PROVIDER_PI, "s2", "user")
	assert org.read_origins(org.PROVIDER_OPENCODE)["s1"]["origin"] == "telegram"
	assert org.read_origins(org.PROVIDER_PI)["s2"]["origin"] == "user"
	assert "s1" not in org.read_origins(org.PROVIDER_PI)
	assert org.telegram_sessions(org.PROVIDER_OPENCODE) == {"s1"}
	assert org.telegram_sessions(org.PROVIDER_PI) == set()
	assert org.has_origin(org.PROVIDER_OPENCODE, "s1", "telegram") is True


def test_read_fusiona_registro_legacy_opencode(tmp_path, monkeypatch):
	monkeypatch.setattr(org, "get_state_dir", lambda: tmp_path)
	(tmp_path / "opencode_origins.json").write_text(json.dumps({"old": {"origin": "telegram", "ts": 1}}))
	org.record_origin(org.PROVIDER_OPENCODE, "new", "user")
	origins = org.read_origins(org.PROVIDER_OPENCODE)
	assert origins["old"]["origin"] == "telegram"
	assert origins["new"]["origin"] == "user"


def test_record_ignora_vacios(tmp_path, monkeypatch):
	monkeypatch.setattr(org, "get_state_dir", lambda: tmp_path)
	org.record_origin(org.PROVIDER_PI, "", org.TELEGRAM_ORIGIN)
	org.record_origin("", "sid", org.TELEGRAM_ORIGIN)
	assert org.read_origins() == {}


def test_claude_code_source_excluye_telegram(tmp_path, monkeypatch):
	from red_pill.chronicle_sources import claude_code as cc

	proj = tmp_path / "proj"
	proj.mkdir()
	(proj / "sid1.jsonl").write_text("{}\n{}\n")
	(proj / "sid2.jsonl").write_text("{}\n")
	src = cc.ClaudeCodeSourcePlugin(base_dir=tmp_path)
	monkeypatch.setattr(cc, "telegram_sessions", lambda provider: {"sid1"})
	assert src.discover() == [("sid2", 1)]


def test_pi_source_excluye_telegram(tmp_path, monkeypatch):
	from red_pill.chronicle_sources import pi as pi_src

	sess = tmp_path / "sess"
	sess.mkdir()
	(sess / "sid1.jsonl").write_text("{}\n")
	(sess / "sid2.jsonl").write_text("{}\n{}\n")
	src = pi_src.PiSourcePlugin(base_dir=tmp_path)
	monkeypatch.setattr(pi_src, "telegram_sessions", lambda provider: {"sess/sid1"})
	assert src.discover() == [("sess/sid2", 2)]


def test_antigravity_source_excluye_telegram(tmp_path, monkeypatch):
	from red_pill.chronicle_sources import antigravity as ag

	(tmp_path / "sid1.json").write_text(json.dumps({"step_count": 3}))
	(tmp_path / "sid2.json").write_text(json.dumps({"step_count": 1}))
	src = ag.AntigravitySourcePlugin()
	monkeypatch.setattr(src, "_conversations_dir", lambda: tmp_path)
	monkeypatch.setattr(ag, "telegram_sessions", lambda provider: {"sid1"})
	assert src.discover() == [("sid2", 1)]
