"""Tests del interceptor 12_session_sync (RFC_CONSCIENCIA Fase 2 / D16).

Cubre los tres modos (SILENT/MINIMAL/HEADER), el default SILENT con cero I/O,
la caché TTL, el aviso de pendientes y la degradación a "" si el registro
falla (el interceptor NUNCA puede tumbar ni frenar el turno).

El módulo empieza con dígitos: se importa vía importlib (misma convención que
tests/test_interceptor_content_field.py).
"""

import asyncio
import importlib
import time
from unittest.mock import MagicMock, patch

from red_pill.core.session_liveness import SessionSignal

mod = importlib.import_module("red_pill.interceptors.12_session_sync")


def _conf_stub(values):
	"""_conf() determinista: devuelve lo de `values`, el resto default."""

	def f(name, default):
		return values.get(name, default)

	return f


def _signal(provider="opencode", session="sess-a", *, start_offset=5.0, end_mtime=None):
	return SessionSignal(
		provider=provider,
		session_id=session,
		start_mtime=time.time() - start_offset,
		end_mtime=end_mtime,
	)


def _run(plugin, prompt="hola", mode="silent", conf=None):
	values = {"SESSION_SYNC_MODE": mode}
	if conf:
		values.update(conf)
	with (
		patch.object(mod, "_conf", _conf_stub(values)),
		patch.object(mod, "_my_originator", return_value="opencode:me"),
	):
		return asyncio.run(plugin.execute(prompt))


# ── Default SILENT: "" y cero I/O ──────────────────────────────────────────


def test_default_mode_is_silent():
	with patch.object(mod, "_conf", _conf_stub({})):
		assert mod._mode() == "silent"


def test_unknown_mode_falls_back_to_silent():
	with patch.object(mod, "_conf", _conf_stub({"SESSION_SYNC_MODE": "ruido"})):
		assert mod._mode() == "silent"


def test_silent_returns_empty_with_zero_io():
	p = mod.SessionSyncPlugin()
	boom = AssertionError("SILENT no debe consultar NADA")
	with (
		patch.object(p, "_live_signals", side_effect=boom),
		patch.object(p, "_global_turn", side_effect=boom),
		patch.object(p, "_registry_rows", side_effect=boom),
		patch.object(p, "_digest", side_effect=boom),
	):
		out = _run(p, mode="silent")
	assert out == ""


# ── MINIMAL: una línea con otras vivas + turno global ──────────────────────


def test_minimal_single_line():
	p = mod.SessionSyncPlugin()
	with (
		patch.object(p, "_live_signals", return_value=[_signal(session="a"), _signal(session="b")]),
		patch.object(p, "_global_turn", return_value=7),
	):
		out = _run(p, mode="minimal")
	assert "\n" not in out
	assert "2 otra(s) viva(s)" in out
	assert "global_turn=7" in out


def test_minimal_reports_zero_when_alone():
	p = mod.SessionSyncPlugin()
	with (
		patch.object(p, "_live_signals", return_value=[]),
		patch.object(p, "_global_turn", return_value=3),
	):
		out = _run(p, mode="minimal")
	assert "0 otra(s) viva(s)" in out
	assert "global_turn=3" in out


# ── HEADER: bloque por misión con origen/rol/in_flight + pendientes ───────


def test_header_blocks_grouped_by_mission():
	p = mod.SessionSyncPlugin()
	rows = {
		"opencode:a": {"originator": "opencode:a", "mission_id": "repo:next", "role": "job", "updated_at": time.time()},
		"claude:b": {"originator": "claude:b", "mission_id": "repo:sharing", "role": "task", "updated_at": time.time()},
	}
	with (
		patch.object(p, "_live_signals", return_value=[_signal(provider="opencode", session="a"), _signal(provider="claude", session="b", end_mtime=time.time())]),
		patch.object(p, "_global_turn", return_value=42),
		patch.object(p, "_registry_rows", return_value=rows),
		patch.object(p, "_pending_notice", return_value=""),
	):
		out = _run(p, mode="header")
	assert "global_turn=42" in out
	assert "2 otra(s) viva(s)" in out
	assert "## 'repo:next' (1)" in out
	assert "## 'repo:sharing' (1)" in out
	assert "job" in out and "task" in out
	# in_flight (start > end / sin end) → "en vuelo"; con .end posterior → "activa"
	assert "en vuelo" in out
	assert "activa" in out


def test_header_without_live_sessions():
	p = mod.SessionSyncPlugin()
	with (
		patch.object(p, "_live_signals", return_value=[]),
		patch.object(p, "_global_turn", return_value=0),
		patch.object(p, "_registry_rows", return_value={}),
		patch.object(p, "_pending_notice", return_value=""),
	):
		out = _run(p, mode="header")
	assert "(sin otras sesiones vivas)" in out


def test_pending_notice_counts_events_since_mark():
	p = mod.SessionSyncPlugin()
	reg = MagicMock()
	reg.count_events.return_value = 3
	rows = {
		"opencode:me": {
			"originator": "opencode:me",
			"mission_id": "repo:next",
			"continuity_id": "soul-1",
			"last_seen_event_seq": 10,
			"updated_at": time.time(),
		}
	}
	with (
		patch.object(p, "_get_registry", return_value=reg),
		patch.object(mod, "_my_originator", return_value="opencode:me"),
	):
		notice = p._pending_notice(rows)
	assert "3 evento(s)" in notice
	assert "repo:next" in notice
	reg.count_events.assert_called_once()
	kwargs = reg.count_events.call_args.kwargs
	assert kwargs["since_seq"] == 10
	assert kwargs["viewer_originator"] == "opencode:me"


def test_pending_notice_silent_without_originator():
	p = mod.SessionSyncPlugin()
	with patch.object(mod, "_my_originator", return_value=""):
		assert p._pending_notice({"x": {"mission_id": "m"}}) == ""


# ── Caché TTL ──────────────────────────────────────────────────────────────


def test_cache_avoids_recompute_within_ttl():
	p = mod.SessionSyncPlugin()
	calls = {"n": 0}

	def live():
		calls["n"] += 1
		return [_signal()]

	with (
		patch.object(p, "_live_signals", live),
		patch.object(p, "_global_turn", return_value=1),
		patch.object(mod, "_ttl_s", return_value=60.0),
	):
		first = _run(p, mode="minimal")
		second = _run(p, mode="minimal")
	assert first == second
	assert calls["n"] == 1


def test_cache_expires_after_ttl():
	p = mod.SessionSyncPlugin()
	calls = {"n": 0}

	def live():
		calls["n"] += 1
		return [_signal()]

	with (
		patch.object(p, "_live_signals", live),
		patch.object(p, "_global_turn", return_value=1),
		patch.object(mod, "_ttl_s", return_value=60.0),
	):
		_run(p, mode="minimal")
		p._cache_at = time.monotonic() - 120.0  # caché caducado a propósito
		_run(p, mode="minimal")
	assert calls["n"] == 2


# ── Degradación: un fallo del registro nunca tumba el turno ────────────────


def test_registry_failure_degrades_to_empty():
	p = mod.SessionSyncPlugin()
	with patch.object(p, "_live_signals", side_effect=RuntimeError("session.db bloqueado")):
		out = _run(p, mode="header")
	assert out == ""
	# y no excepciona en el segundo turno tampoco (caché caducado)
	p._cache_at = 0.0
	with patch.object(p, "_live_signals", side_effect=RuntimeError("sigue roto")):
		assert _run(p, mode="minimal") == ""


def test_global_turn_failure_degrades_to_zero():
	p = mod.SessionSyncPlugin()
	with (
		patch.object(p, "_get_registry", side_effect=RuntimeError("sin registro")),
		patch.object(p, "_live_signals", return_value=[_signal()]),
	):
		assert p._global_turn() == 0
		out = _run(p, mode="minimal")
	assert "1 otra(s) viva(s)" in out
	assert "global_turn=0" in out


def test_pending_notice_failure_is_silent():
	p = mod.SessionSyncPlugin()
	reg = MagicMock()
	reg.count_events.side_effect = RuntimeError("boom")
	rows = {"opencode:me": {"originator": "opencode:me", "mission_id": "m", "last_seen_event_seq": 0, "continuity_id": "c"}}
	with patch.object(p, "_get_registry", return_value=reg):
		assert p._pending_notice(rows) == ""


# ── Integración ligera: señales reales de liveness ─────────────────────────


def test_live_signals_excludes_own_originator():
	p = mod.SessionSyncPlugin()
	signals = [_signal(provider="opencode", session="me"), _signal(provider="opencode", session="otra"), _signal(provider="claude", session="vieja", start_offset=10 * 60 * 60)]
	with (
		patch("red_pill.core.session_liveness.list_sessions", return_value=signals),
		patch.object(mod, "_conf", _conf_stub({"SESSION_ACTIVE_MIN": 10})),
		patch.object(mod, "_my_originator", return_value="opencode:me"),
	):
		live = p._live_signals()
	assert [f"{s.provider}:{s.session_id}" for s in live] == ["opencode:otra"]
