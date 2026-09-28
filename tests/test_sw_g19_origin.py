"""G19 single-writer — procedencia de Telegram en Memento (origin real)."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migrate():
	spec = importlib.util.spec_from_file_location("memento_migrate_g19", Path("scripts/memento_migrate.py"))
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


def test_originator_resuelve_telegram_desde_registro():
	from red_pill.swarm.bridges.opencode import record_opencode_origin

	mod = _load_migrate()
	record_opencode_origin("ses_tg_1", "telegram")
	assert mod._originator_for("opencode", "opencode:ses_tg_1") == "telegram"


def test_originator_fallback_a_la_fuente():
	mod = _load_migrate()
	assert mod._originator_for("opencode", "opencode:ses_desconocida") == "opencode"
