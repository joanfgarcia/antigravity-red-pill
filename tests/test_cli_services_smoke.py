"""Smoke tests for cli_services handlers (SHARD-PV-02).

No edge cases: only the COMMON dispatch path of each handler — that it resolves
its subcommand, builds/prints the expected thing and does NOT explode. Destructive
branches (GDPR purge confirmed, p2p pair, ide backend writes .env, memory
enable/disable) are deliberately avoided.
"""

from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock

import red_pill.cli_services as svc


# ── identity ──────────────────────────────────────────────────────────────────
def test_identity_bootstrap_builds_argv(monkeypatch):
	captured = {}
	monkeypatch.setattr(svc.subprocess, "run", lambda cmd: captured.update(cmd=cmd))
	svc.handle_identity(
		argparse.Namespace(id_cmd="bootstrap", ai_name="Aleth", ai_role="Netrunner", user_name="Joan", user_role="Fixer", skin="cyberpunk")
	)
	cmd = captured["cmd"]
	assert cmd[1].endswith("bootstrap_identity.py")
	assert cmd[cmd.index("--ai-name") + 1] == "Aleth"
	assert cmd[cmd.index("--skin") + 1] == "cyberpunk"


def test_identity_purge_aborted_no_side_effects(monkeypatch, capsys):
	monkeypatch.setattr("builtins.input", lambda _prompt="": "nope")
	svc.handle_identity(argparse.Namespace(id_cmd="purge"))
	assert "Purge aborted" in capsys.readouterr().out


# ── ide ───────────────────────────────────────────────────────────────────────
def test_ide_backend_shows_current(capsys):
	svc.handle_ide(argparse.Namespace(ide_cmd="backend", value=None))
	assert "Current IDE backend" in capsys.readouterr().out


def test_ide_unknown_usage(capsys):
	svc.handle_ide(argparse.Namespace(ide_cmd="bogus", value=None))
	assert "Usage: red-pill ide" in capsys.readouterr().out


# ── runtime ───────────────────────────────────────────────────────────────────
def test_runtime_check_unknown_profile(capsys):
	svc.handle_runtime(argparse.Namespace(runtime_cmd="check", profile="no-existe-xyz-123"))
	assert "no existe" in capsys.readouterr().out


def test_runtime_list_smoke(capsys):
	svc.handle_runtime(argparse.Namespace(runtime_cmd="list"))  # no debe lanzar
	assert capsys.readouterr().out != ""  # imprime algo (runtimes o "sin runtimes")


# ── license ───────────────────────────────────────────────────────────────────
def test_license_json_is_valid(capsys):
	svc.handle_license(argparse.Namespace(json=True))
	payload = json.loads(capsys.readouterr().out)
	assert set(payload) == {"context", "profiles", "catalog"}


# ── telegram ──────────────────────────────────────────────────────────────────
def test_telegram_unknown_usage(capsys):
	svc.handle_telegram(argparse.Namespace(telegram_cmd="bogus"))
	assert "Usage: red-pill telegram" in capsys.readouterr().out


# ── p2p / memory (usage fallback: no side effects) ────────────────────────────
def test_p2p_unknown_usage(capsys):
	svc.handle_p2p(argparse.Namespace(p2p_cmd="bogus"))
	assert "Usage: red-pill p2p" in capsys.readouterr().out


def test_memory_unknown_usage(capsys):
	svc.handle_memory(argparse.Namespace(mem_cmd="bogus"))
	assert "Usage: red-pill memory" in capsys.readouterr().out


# ── session compact-sweep ────────────────────────────────────────────────────
def test_session_compact_sweep_json(monkeypatch, capsys):
	captured = {}

	def fake_sweep(**kwargs):
		captured.update(kwargs)
		return {"enabled": True, "active_min": 15, "scanned": 2, "enqueued": 1}

	monkeypatch.setattr("red_pill.session.compaction_hook.sweep_active_compactions", fake_sweep)
	svc.handle_session(
		argparse.Namespace(session_cmd="compact-sweep", active_min=15, limit=50, db_path="/tmp/session.db", json=True)
	)
	payload = json.loads(capsys.readouterr().out)
	assert payload == {"enabled": True, "active_min": 15, "scanned": 2, "enqueued": 1}
	assert captured == {"active_min": 15, "limit": 50, "db_path": "/tmp/session.db"}


def test_compact_heartbeat_loop_renews_lease():
	class StopAfterOne:
		def __init__(self):
			self.calls = 0

		def wait(self, interval):
			self.calls += 1
			return self.calls > 1

	lease = MagicMock()
	svc._compact_heartbeat_loop(lease, "compact:alma", "alma", "holder", StopAfterOne(), MagicMock())
	lease.heartbeat.assert_called_once_with(
		"compact:alma", source="compactor", continuity_id="alma", holder_originator="holder"
	)
