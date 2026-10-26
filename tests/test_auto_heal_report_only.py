"""AD-085 — Auto-Healer y SyntaxGuard en report-only por defecto."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from red_pill.metabolism.sentinel_plugins.check_syntax import SyntaxGuardCheck
from red_pill.rituals import auto_heal_ritual


def test_auto_heal_ritual_report_only(monkeypatch):
	monkeypatch.setattr(
		"red_pill.config.get_config",
		lambda: SimpleNamespace(AUTO_HEAL_ENABLED=False),
	)
	inbox_cls = MagicMock()
	monkeypatch.setattr("red_pill.rituals.MinionInbox", inbox_cls)
	asyncio.run(auto_heal_ritual(SimpleNamespace()))
	inbox_cls.assert_not_called()


def test_syntax_guard_report_only_does_not_restore_git(monkeypatch):
	guard = SyntaxGuardCheck()
	cfg = SimpleNamespace(AUTO_HEAL_ENABLED=False, APP_ROOT="/tmp")
	finding = SimpleNamespace(metadata={"file": "/tmp/x.py", "rel_path": "x.py"})
	run = MagicMock()
	monkeypatch.setattr("red_pill.metabolism.sentinel_plugins.check_syntax.subprocess.run", run)
	assert guard.heal(cfg, finding) is False
	run.assert_not_called()
